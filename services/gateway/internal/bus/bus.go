// Package bus wraps NATS JetStream: stream provisioning, protobuf publishing,
// the durable gateway-persist consumer, and per-job ephemeral consumers for SSE.
package bus

import (
	"context"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/nats-io/nats.go/jetstream"
)

type Bus struct {
	nc     *nats.Conn
	js     jetstream.JetStream
	stream string
}

func Connect(ctx context.Context, url, stream string) (*Bus, error) {
	nc, err := nats.Connect(url, nats.MaxReconnects(-1), nats.ReconnectWait(time.Second))
	if err != nil {
		return nil, err
	}
	js, err := jetstream.New(nc)
	if err != nil {
		nc.Close()
		return nil, err
	}
	b := &Bus{nc: nc, js: js, stream: stream}
	if err := b.ensureStream(ctx); err != nil {
		nc.Close()
		return nil, err
	}
	return b, nil
}

func (b *Bus) ensureStream(ctx context.Context) error {
	_, err := b.js.CreateOrUpdateStream(ctx, jetstream.StreamConfig{
		Name:      b.stream,
		Subjects:  []string{"cv.>"},
		Retention: jetstream.LimitsPolicy,
		MaxAge:    time.Hour,
		Storage:   jetstream.FileStorage,
	})
	return err
}

// Publish sends a protobuf payload on subject with the given headers
// (trace context is injected by the caller).
func (b *Bus) Publish(ctx context.Context, subject string, data []byte, hdr nats.Header) error {
	_, err := b.js.PublishMsg(ctx, &nats.Msg{Subject: subject, Data: data, Header: hdr})
	return err
}

// ConsumePersist binds the durable gateway-persist consumer (result events of
// every job) and starts consuming. The gateway projects these into Postgres.
func (b *Bus) ConsumePersist(ctx context.Context, handler jetstream.MessageHandler) (jetstream.ConsumeContext, error) {
	cons, err := b.js.CreateOrUpdateConsumer(ctx, b.stream, jetstream.ConsumerConfig{
		Durable:        "gateway-persist",
		FilterSubjects: []string{"cv.*.structured", "cv.*.completed", "cv.*.failed"},
		AckPolicy:      jetstream.AckExplicitPolicy,
	})
	if err != nil {
		return nil, err
	}
	return cons.Consume(handler)
}

// JobEvents creates an ephemeral ordered consumer that replays then live-tails
// every event for a single job (used by the SSE endpoint). DeliverAll avoids a
// race where a terminal event lands before the browser connects.
func (b *Bus) JobEvents(ctx context.Context, jobID string, handler jetstream.MessageHandler) (jetstream.ConsumeContext, error) {
	cons, err := b.js.OrderedConsumer(ctx, b.stream, jetstream.OrderedConsumerConfig{
		FilterSubjects: []string{"cv." + jobID + ".>"},
		DeliverPolicy:  jetstream.DeliverAllPolicy,
	})
	if err != nil {
		return nil, err
	}
	return cons.Consume(handler)
}

// Connected reports whether the NATS connection is live (used by readiness).
func (b *Bus) Connected() bool { return b.nc.IsConnected() }

func (b *Bus) Close() { _ = b.nc.Drain() }
