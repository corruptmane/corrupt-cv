package telemetry

import (
	"bytes"
	"context"
	"log/slog"
	"strings"
	"testing"

	"github.com/nats-io/nats.go"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/trace"
)

// TestSetupDisabled: with no OTLP endpoint configured, Setup is a
// no-op that still hands back a working shutdown func.
func TestSetupDisabled(t *testing.T) {
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")

	if Enabled() {
		t.Fatal("Enabled() = true with empty OTEL_EXPORTER_OTLP_ENDPOINT")
	}
	shutdown, err := Setup(context.Background())
	if err != nil {
		t.Fatalf("Setup: %v", err)
	}
	if shutdown == nil {
		t.Fatal("Setup returned nil shutdown func")
	}
	if err := shutdown(context.Background()); err != nil {
		t.Fatalf("shutdown: %v", err)
	}
	// Idempotent: calling it again must also succeed.
	if err := shutdown(context.Background()); err != nil {
		t.Fatalf("second shutdown: %v", err)
	}
}

// TestFanoutHandlerWritesBothSinks: one record lands in every enabled
// sink, and per-sink level filtering still applies.
func TestFanoutHandlerWritesBothSinks(t *testing.T) {
	var a, b bytes.Buffer
	h := NewFanoutHandler(
		slog.NewJSONHandler(&a, &slog.HandlerOptions{Level: slog.LevelInfo}),
		slog.NewJSONHandler(&b, &slog.HandlerOptions{Level: slog.LevelWarn}),
	)
	log := slog.New(h).With("job_id", "j1")

	log.Info("hello info")
	log.Warn("hello warn")

	for _, want := range []string{"hello info", "hello warn", "job_id"} {
		if !strings.Contains(a.String(), want) {
			t.Errorf("sink a missing %q; got %s", want, a.String())
		}
	}
	if strings.Contains(b.String(), "hello info") {
		t.Errorf("sink b (warn-level) received info record: %s", b.String())
	}
	if !strings.Contains(b.String(), "hello warn") {
		t.Errorf("sink b missing warn record: %s", b.String())
	}
}

// TestNATSCarrierLowercaseKeys: the W3C keys must land in the NATS
// header map verbatim ("traceparent"), not MIME-canonicalised — the
// Python consumers look them up case-sensitively.
func TestNATSCarrierLowercaseKeys(t *testing.T) {
	sc := trace.NewSpanContext(trace.SpanContextConfig{
		TraceID:    trace.TraceID{0x01},
		SpanID:     trace.SpanID{0x02},
		TraceFlags: trace.FlagsSampled,
	})
	ctx := trace.ContextWithSpanContext(context.Background(), sc)

	h := nats.Header{}
	propagation.TraceContext{}.Inject(ctx, natsHeaderCarrier(h))

	if got := h["traceparent"]; len(got) != 1 || got[0] == "" {
		t.Fatalf(`header "traceparent" not set verbatim; header map: %v`, h)
	}
	if _, bad := h["Traceparent"]; bad {
		t.Fatalf("header key was MIME-canonicalised: %v", h)
	}

	// Round trip through extract.
	out := propagation.TraceContext{}.Extract(context.Background(), natsHeaderCarrier(h))
	if got := trace.SpanContextFromContext(out); got.TraceID() != sc.TraceID() {
		t.Fatalf("extract round-trip: got trace id %s, want %s", got.TraceID(), sc.TraceID())
	}
}

// TestInstrumentHelpersFallBackToNoop: a name the SDK rejects must yield
// usable no-op instruments — never nil (first-use panic) and never an
// error that takes the process down. The no-ops also record nothing into
// the real provider they were requested from.
func TestInstrumentHelpersFallBackToNoop(t *testing.T) {
	reader := sdkmetric.NewManualReader()
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader))
	t.Cleanup(func() { _ = mp.Shutdown(context.Background()) })
	meter := mp.Meter("test")

	const bad = "invalid name" // spaces violate the instrument-name spec

	c := Int64Counter(meter, bad)
	fh := Float64Histogram(meter, bad)
	ih := Int64Histogram(meter, bad)
	g := Int64Gauge(meter, bad)
	if c == nil || fh == nil || ih == nil || g == nil {
		t.Fatal("a fallback helper returned a nil instrument")
	}

	ctx := context.Background()
	c.Add(ctx, 1)
	fh.Record(ctx, 0.5)
	ih.Record(ctx, 2)

	var rm metricdata.ResourceMetrics
	if err := reader.Collect(ctx, &rm); err != nil {
		t.Fatalf("collect: %v", err)
	}
	if len(rm.ScopeMetrics) != 0 {
		t.Fatalf("fallback instruments recorded into the real provider: %+v", rm.ScopeMetrics)
	}
}
