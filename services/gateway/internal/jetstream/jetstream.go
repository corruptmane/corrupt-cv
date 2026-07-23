// Package jetstream provisions and uses the gateway's NATS JetStream
// entities. The gateway is the single authority for stream, consumer
// and KV bucket creation; the Python workers only bind to what exists.
package jetstream

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/nats-io/nats.go"
	natsjs "github.com/nats-io/nats.go/jetstream"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	oteltrace "go.opentelemetry.io/otel/trace"
	"google.golang.org/protobuf/proto"

	eventsv1 "github.com/corruptmane/cv/services/gateway/gen/cvgen/events/v1"
	"github.com/corruptmane/cv/services/gateway/internal/telemetry"
)

// Contract constants shared by every service in the pipeline.
const (
	StreamName         = "CV_EVENTS"
	CatalogBucket      = "model-catalog"
	ConsumerAIProc     = "AI_PROCESSOR"
	ConsumerCVGen      = "CV_GENERATOR"
	ConsumerGatewayEvt = "GATEWAY_EVENTS"

	// EventRequested et al. are the per-job subject suffixes.
	EventRequested  = "requested"
	EventStructured = "structured"
	EventRendered   = "rendered"
	EventFailed     = "failed"
)

// Subject returns the per-job subject "cv.{job_id}.{event}".
func Subject(jobID, event string) string {
	return fmt.Sprintf("cv.%s.%s", jobID, event)
}

// MsgID returns the dedup id "{job_id}:{event}" for the Nats-Msg-Id
// header.
func MsgID(jobID, event string) string {
	return fmt.Sprintf("%s:%s", jobID, event)
}

// ParseSubject splits "cv.{job_id}.{event}" into its parts.
func ParseSubject(subject string) (jobID, event string, ok bool) {
	parts := strings.Split(subject, ".")
	if len(parts) != 3 || parts[0] != "cv" {
		return "", "", false
	}
	return parts[1], parts[2], true
}

// Provision creates or updates the CV_EVENTS stream, the three durable
// pull consumers, and the model-catalog KV bucket. It must complete
// before the gateway starts serving traffic. It returns the KV bucket
// so the caller can seed the catalog.
func Provision(ctx context.Context, js natsjs.JetStream) (natsjs.KeyValue, error) {
	_, err := js.CreateOrUpdateStream(ctx, natsjs.StreamConfig{
		Name:       StreamName,
		Subjects:   []string{"cv.*.*"},
		Retention:  natsjs.LimitsPolicy,
		Storage:    natsjs.FileStorage,
		MaxAge:     24 * time.Hour,
		Duplicates: 2 * time.Minute,
	})
	if err != nil {
		return nil, fmt.Errorf("create stream %s: %w", StreamName, err)
	}

	consumers := []natsjs.ConsumerConfig{
		{
			Durable:       ConsumerAIProc,
			FilterSubject: "cv.*." + EventRequested,
			AckPolicy:     natsjs.AckExplicitPolicy,
			// No BackOff list: a JetStream backoff schedule REPLACES AckWait
			// as the redelivery timer (backoff[0] would shrink the effective
			// ack deadline to 10s and spuriously redeliver mid-LLM-call).
			// AckWait + in_progress heartbeats govern instead.
			AckWait:    120 * time.Second,
			MaxDeliver: 3,
		},
		{
			Durable:       ConsumerCVGen,
			FilterSubject: "cv.*." + EventStructured,
			AckPolicy:     natsjs.AckExplicitPolicy,
			AckWait:       60 * time.Second,
			MaxDeliver:    3,
		},
		{
			Durable: ConsumerGatewayEvt,
			FilterSubjects: []string{
				"cv.*." + EventRequested,
				"cv.*." + EventStructured,
				"cv.*." + EventRendered,
				"cv.*." + EventFailed,
			},
			AckPolicy:  natsjs.AckExplicitPolicy,
			AckWait:    30 * time.Second,
			MaxDeliver: 5,
		},
	}
	for _, cfg := range consumers {
		if _, err := js.CreateOrUpdateConsumer(ctx, StreamName, cfg); err != nil {
			return nil, fmt.Errorf("create consumer %s: %w", cfg.Durable, err)
		}
	}

	kv, err := js.CreateOrUpdateKeyValue(ctx, natsjs.KeyValueConfig{
		Bucket:  CatalogBucket,
		History: 1,
	})
	if err != nil {
		return nil, fmt.Errorf("create kv bucket %s: %w", CatalogBucket, err)
	}
	return kv, nil
}

// Publisher publishes gateway-originated job events.
type Publisher struct {
	js natsjs.JetStream
}

// NewPublisher wraps a JetStream context.
func NewPublisher(js natsjs.JetStream) *Publisher {
	return &Publisher{js: js}
}

// PublishJobRequested publishes a JobRequested event to
// cv.{job_id}.requested with the dedup Nats-Msg-Id header, wrapped in
// a PRODUCER span whose context is injected into the NATS headers so
// the pipeline's workers continue the trace.
func (p *Publisher) PublishJobRequested(ctx context.Context, ev *eventsv1.JobRequested) error {
	subject := Subject(ev.GetJobId(), EventRequested)
	ctx, span := otel.Tracer(telemetry.ScopeName).Start(ctx, "publish cv."+EventRequested,
		oteltrace.WithSpanKind(oteltrace.SpanKindProducer),
		oteltrace.WithAttributes(
			attribute.String("messaging.system", "nats"),
			attribute.String("messaging.destination.name", subject),
			attribute.String("cvgen.job_id", ev.GetJobId()),
		),
	)
	defer span.End()

	data, err := proto.Marshal(ev)
	if err != nil {
		span.SetStatus(codes.Error, err.Error())
		return fmt.Errorf("marshal JobRequested: %w", err)
	}
	msg := &nats.Msg{
		Subject: subject,
		Data:    data,
		Header:  nats.Header{},
	}
	msg.Header.Set("Nats-Msg-Id", MsgID(ev.GetJobId(), EventRequested))
	telemetry.InjectNATS(ctx, msg.Header)
	if _, err := p.js.PublishMsg(ctx, msg); err != nil {
		span.SetStatus(codes.Error, err.Error())
		return fmt.Errorf("publish %s: %w", msg.Subject, err)
	}
	return nil
}

// OrderedJobConsumer creates the per-SSE-connection ephemeral ordered
// consumer over every event of one job, from the beginning of the
// stream. The caller must delete it via DeleteOrderedConsumer when the
// connection ends.
func OrderedJobConsumer(ctx context.Context, js natsjs.JetStream, jobID string) (natsjs.Consumer, error) {
	cons, err := js.OrderedConsumer(ctx, StreamName, natsjs.OrderedConsumerConfig{
		FilterSubjects: []string{fmt.Sprintf("cv.%s.>", jobID)},
		DeliverPolicy:  natsjs.DeliverAllPolicy,
	})
	if err != nil {
		return nil, fmt.Errorf("create ordered consumer for job %s: %w", jobID, err)
	}
	return cons, nil
}

// DeleteOrderedConsumer removes the ephemeral ordered consumer that
// backs an SSE connection. Best effort: ordered consumers are also
// cleaned up server-side via their inactive threshold.
func DeleteOrderedConsumer(ctx context.Context, js natsjs.JetStream, cons natsjs.Consumer) error {
	name := cons.CachedInfo().Name
	if name == "" {
		return nil
	}
	if err := js.DeleteConsumer(ctx, StreamName, name); err != nil {
		return fmt.Errorf("delete ordered consumer %s: %w", name, err)
	}
	return nil
}
