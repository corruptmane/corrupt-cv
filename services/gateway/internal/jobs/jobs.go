// Package jobs keeps the jobs table in sync with the event stream: it
// runs the GATEWAY_EVENTS durable consume loop, watches MAX_DELIVERIES
// advisories to fail poisoned jobs, and periodically sweeps jobs that
// stopped progressing.
package jobs

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/nats-io/nats.go"
	natsjs "github.com/nats-io/nats.go/jetstream"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/metric"
	oteltrace "go.opentelemetry.io/otel/trace"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	eventsv1 "github.com/corruptmane/cv/services/gateway/gen/cvgen/events/v1"
	"github.com/corruptmane/cv/services/gateway/internal/jetstream"
	"github.com/corruptmane/cv/services/gateway/internal/store"
	"github.com/corruptmane/cv/services/gateway/internal/telemetry"
)

// advisorySubject matches server advisories emitted when any CV_EVENTS
// consumer exhausts its delivery attempts.
const advisorySubject = "$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES." + jetstream.StreamName + ".>"

// maxDeliveriesError is the user-safe error stored on jobs whose
// events could not be processed within MaxDeliver attempts.
const maxDeliveriesError = "processing failed repeatedly"

// Runner owns the background goroutines that project events into the
// jobs table.
type Runner struct {
	js  natsjs.JetStream
	st  *store.Store
	log *slog.Logger

	tracer      oteltrace.Tracer
	jobsTotal   metric.Int64Counter
	jobDuration metric.Float64Histogram

	consumeCtx natsjs.ConsumeContext
	advisory   *nats.Subscription
	stopOnce   sync.Once
}

// NewRunner builds a Runner. Tracer and instruments come from the
// globals installed by telemetry.Setup; when telemetry is disabled
// they are the SDK's no-ops.
func NewRunner(js natsjs.JetStream, st *store.Store, log *slog.Logger) *Runner {
	meter := otel.Meter(telemetry.ScopeName)
	jobsTotal, err := meter.Int64Counter("cvgen.jobs.total",
		metric.WithDescription("Jobs that reached a terminal status."))
	if err != nil {
		log.Warn("create cvgen.jobs.total counter", "error", err)
	}
	jobDuration, err := meter.Float64Histogram("cvgen.job.duration",
		metric.WithUnit("s"),
		metric.WithDescription("Time from job creation to its terminal event."))
	if err != nil {
		log.Warn("create cvgen.job.duration histogram", "error", err)
	}
	return &Runner{
		js:          js,
		st:          st,
		log:         log,
		tracer:      otel.Tracer(telemetry.ScopeName),
		jobsTotal:   jobsTotal,
		jobDuration: jobDuration,
	}
}

// recordTerminal updates the job metrics for one terminal transition.
// The duration ends at the event's occurred_at when present, else now.
func (r *Runner) recordTerminal(ctx context.Context, status string, createdAt time.Time, occurredAt *timestamppb.Timestamp) {
	end := time.Now()
	if occurredAt.IsValid() {
		end = occurredAt.AsTime()
	}
	attrs := metric.WithAttributes(attribute.String("status", status))
	r.jobsTotal.Add(ctx, 1, attrs)
	r.jobDuration.Record(ctx, end.Sub(createdAt).Seconds(), attrs)
}

// Start launches the consume loop, the advisory subscription, and the
// sweeper. ctx controls the sweeper's lifetime; Stop tears down the
// NATS subscriptions.
func (r *Runner) Start(ctx context.Context) error {
	cons, err := r.js.Consumer(ctx, jetstream.StreamName, jetstream.ConsumerGatewayEvt)
	if err != nil {
		return fmt.Errorf("bind %s consumer: %w", jetstream.ConsumerGatewayEvt, err)
	}
	cc, err := cons.Consume(r.handleMsg)
	if err != nil {
		return fmt.Errorf("start %s consume loop: %w", jetstream.ConsumerGatewayEvt, err)
	}
	r.consumeCtx = cc

	sub, err := r.js.Conn().Subscribe(advisorySubject, r.handleAdvisory)
	if err != nil {
		cc.Stop()
		return fmt.Errorf("subscribe advisories: %w", err)
	}
	r.advisory = sub

	go r.sweep(ctx)
	return nil
}

// Stop drains the consume loop and advisory subscription. Safe to
// call more than once.
func (r *Runner) Stop() {
	r.stopOnce.Do(func() {
		if r.consumeCtx != nil {
			r.consumeCtx.Drain()
			select {
			case <-r.consumeCtx.Closed():
			case <-time.After(5 * time.Second):
			}
		}
		if r.advisory != nil {
			_ = r.advisory.Drain()
		}
	})
}

// handleMsg applies one stream event to the jobs table. Malformed
// messages are terminated (redelivery cannot fix them); database
// errors nak for redelivery.
func (r *Runner) handleMsg(msg natsjs.Msg) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	jobID, event, ok := jetstream.ParseSubject(msg.Subject())
	if !ok {
		r.log.Warn("unparseable event subject", "subject", msg.Subject())
		_ = msg.Term()
		return
	}

	// Continue the trace the publisher injected into the headers.
	ctx = telemetry.ExtractNATS(ctx, msg.Headers())
	ctx, span := r.tracer.Start(ctx, "consume cv."+event,
		oteltrace.WithSpanKind(oteltrace.SpanKindConsumer),
		oteltrace.WithAttributes(
			attribute.String("messaging.system", "nats"),
			attribute.String("messaging.destination.name", msg.Subject()),
			attribute.String("cvgen.job_id", jobID),
			attribute.String("cvgen.event", event),
		),
	)
	defer span.End()

	log := r.log.With("job_id", jobID, "event", event)

	var applyErr error
	switch event {
	case jetstream.EventRequested:
		// Job rows are created as 'pending' before publish; nothing to do.

	case jetstream.EventStructured:
		var ev eventsv1.JobStructured
		if err := proto.Unmarshal(msg.Data(), &ev); err != nil {
			log.WarnContext(ctx, "malformed JobStructured payload", "error", err)
			_ = msg.Term()
			return
		}
		cvJSON, err := protojson.Marshal(ev.GetCv())
		if err != nil {
			log.WarnContext(ctx, "cannot encode cv to protojson", "error", err)
			_ = msg.Term()
			return
		}
		applyErr = r.st.MarkRendering(ctx, jobID, cvJSON)

	case jetstream.EventRendered:
		var ev eventsv1.JobRendered
		if err := proto.Unmarshal(msg.Data(), &ev); err != nil {
			log.WarnContext(ctx, "malformed JobRendered payload", "error", err)
			_ = msg.Term()
			return
		}
		createdAt, applied, err := r.st.MarkCompleted(ctx, jobID, ev.GetPdfObjectKey())
		applyErr = err
		if err == nil && applied {
			r.recordTerminal(ctx, "completed", createdAt, ev.GetOccurredAt())
		}

	case jetstream.EventFailed:
		var ev eventsv1.JobFailed
		if err := proto.Unmarshal(msg.Data(), &ev); err != nil {
			log.WarnContext(ctx, "malformed JobFailed payload", "error", err)
			_ = msg.Term()
			return
		}
		createdAt, applied, err := r.st.MarkFailed(ctx, jobID, ev.GetError())
		applyErr = err
		if err == nil && applied {
			r.recordTerminal(ctx, "failed", createdAt, ev.GetOccurredAt())
		}

	default:
		log.WarnContext(ctx, "unknown event suffix")
		_ = msg.Term()
		return
	}

	if applyErr != nil {
		span.SetStatus(codes.Error, applyErr.Error())
		log.ErrorContext(ctx, "apply event to jobs table", "error", applyErr)
		_ = msg.Nak()
		return
	}
	if err := msg.Ack(); err != nil {
		log.WarnContext(ctx, "ack event", "error", err)
	}
	log.DebugContext(ctx, "event applied")
}

// maxDeliveriesAdvisory is the subset of the server's
// io.nats.jetstream.advisory.v1.max_deliver schema we need.
type maxDeliveriesAdvisory struct {
	Stream     string `json:"stream"`
	Consumer   string `json:"consumer"`
	StreamSeq  uint64 `json:"stream_seq"`
	Deliveries int    `json:"deliveries"`
}

// handleAdvisory fails the job whose event exhausted its deliveries.
// The advisory only carries the stream sequence, so the original
// message is fetched back from the stream to recover the job id.
func (r *Runner) handleAdvisory(m *nats.Msg) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	var adv maxDeliveriesAdvisory
	if err := json.Unmarshal(m.Data, &adv); err != nil {
		r.log.Warn("malformed max-deliveries advisory", "error", err)
		return
	}
	log := r.log.With("consumer", adv.Consumer, "stream_seq", adv.StreamSeq, "deliveries", adv.Deliveries)

	stream, err := r.js.Stream(ctx, jetstream.StreamName)
	if err != nil {
		log.Error("lookup stream for advisory", "error", err)
		return
	}
	raw, err := stream.GetMsg(ctx, adv.StreamSeq)
	if err != nil {
		// Message may have aged out (MaxAge 24h); nothing to recover.
		log.Warn("fetch advisory message from stream", "error", err)
		return
	}
	jobID, event, ok := jetstream.ParseSubject(raw.Subject)
	if !ok {
		log.Warn("advisory message has unparseable subject", "subject", raw.Subject)
		return
	}
	createdAt, applied, err := r.st.MarkFailed(ctx, jobID, maxDeliveriesError)
	if err != nil {
		log.Error("mark job failed after max deliveries", "job_id", jobID, "error", err)
		return
	}
	if applied {
		r.recordTerminal(ctx, "failed", createdAt, nil)
	}
	log.Info("job failed after exhausted deliveries", "job_id", jobID, "event", event)
}

// sweep fails jobs stuck without progress for over 10 minutes, once a
// minute, until ctx is cancelled.
func (r *Runner) sweep(ctx context.Context) {
	ticker := time.NewTicker(time.Minute)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			swept, err := r.st.SweepStuck(ctx, 10*time.Minute)
			if err != nil {
				if ctx.Err() == nil {
					r.log.Error("sweep stuck jobs", "error", err)
				}
				continue
			}
			if swept > 0 {
				r.log.Info("swept stuck jobs", "count", swept)
			}
		}
	}
}
