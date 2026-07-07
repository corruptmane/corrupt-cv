package telemetry

import (
	"context"

	"github.com/nats-io/nats.go"
	"go.opentelemetry.io/otel"
)

// natsHeaderCarrier adapts nats.Header for OTel textmap propagation.
// It deliberately avoids nats.Header's Get/Set, which canonicalise
// keys MIME-style ("Traceparent"): NATS headers are case-sensitive and
// the Python services look up the lowercase W3C keys verbatim.
type natsHeaderCarrier nats.Header

func (c natsHeaderCarrier) Get(key string) string {
	if vs := c[key]; len(vs) > 0 {
		return vs[0]
	}
	return ""
}

func (c natsHeaderCarrier) Set(key, value string) {
	c[key] = []string{value}
}

func (c natsHeaderCarrier) Keys() []string {
	keys := make([]string, 0, len(c))
	for k := range c {
		keys = append(keys, k)
	}
	return keys
}

// InjectNATS writes the trace context from ctx ("traceparent",
// "tracestate") into the NATS headers.
func InjectNATS(ctx context.Context, h nats.Header) {
	otel.GetTextMapPropagator().Inject(ctx, natsHeaderCarrier(h))
}

// ExtractNATS returns ctx extended with the trace context carried in
// the NATS headers, if any.
func ExtractNATS(ctx context.Context, h nats.Header) context.Context {
	return otel.GetTextMapPropagator().Extract(ctx, natsHeaderCarrier(h))
}
