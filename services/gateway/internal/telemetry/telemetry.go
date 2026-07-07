// Package telemetry wires OpenTelemetry traces (OTLP/gRPC push) + metrics
// (Prometheus pull) and a structured slog JSON logger, plus helpers to propagate
// trace context across NATS message headers.
package telemetry

import (
	"context"
	"log/slog"
	"net/http"
	"os"

	"github.com/nats-io/nats.go"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	otelprom "go.opentelemetry.io/otel/exporters/prometheus"
	"go.opentelemetry.io/otel/propagation"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
)

// Setup installs global tracer/meter providers and the slog default logger.
// Traces are pushed via OTLP; metrics are exposed for scraping and the returned
// http.Handler must be served at /metrics on the ops server. Exporters are lazy,
// so an unreachable collector does not block startup.
func Setup(ctx context.Context) (func(context.Context) error, http.Handler, error) {
	res, err := resource.New(ctx,
		resource.WithFromEnv(),
		resource.WithTelemetrySDK(),
		resource.WithHost(),
	)
	if err != nil {
		return nil, nil, err
	}

	traceExp, err := otlptracegrpc.New(ctx)
	if err != nil {
		return nil, nil, err
	}
	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(traceExp),
		sdktrace.WithResource(res),
	)
	otel.SetTracerProvider(tp)

	registry := prometheus.NewRegistry()
	promExp, err := otelprom.New(otelprom.WithRegisterer(registry))
	if err != nil {
		return nil, nil, err
	}
	mp := sdkmetric.NewMeterProvider(
		sdkmetric.WithReader(promExp),
		sdkmetric.WithResource(res),
	)
	otel.SetMeterProvider(mp)

	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{}, propagation.Baggage{},
	))

	setupLogger()

	metricsHandler := promhttp.HandlerFor(registry, promhttp.HandlerOpts{})
	shutdown := func(ctx context.Context) error {
		_ = tp.Shutdown(ctx)
		return mp.Shutdown(ctx)
	}
	return shutdown, metricsHandler, nil
}

func setupLogger() {
	level := slog.LevelInfo
	switch os.Getenv("LOG_LEVEL") {
	case "debug":
		level = slog.LevelDebug
	case "warn":
		level = slog.LevelWarn
	case "error":
		level = slog.LevelError
	}
	h := &contextHandler{Handler: slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: level})}
	slog.SetDefault(slog.New(h).With("service", os.Getenv("OTEL_SERVICE_NAME")))
}

// contextHandler enriches every record with trace_id/span_id when the context
// carries an active span.
type contextHandler struct{ slog.Handler }

func (h *contextHandler) Handle(ctx context.Context, r slog.Record) error {
	if sc := trace.SpanContextFromContext(ctx); sc.IsValid() {
		r.AddAttrs(
			slog.String("trace_id", sc.TraceID().String()),
			slog.String("span_id", sc.SpanID().String()),
		)
	}
	return h.Handler.Handle(ctx, r)
}

func (h *contextHandler) WithAttrs(as []slog.Attr) slog.Handler {
	return &contextHandler{Handler: h.Handler.WithAttrs(as)}
}

func (h *contextHandler) WithGroup(name string) slog.Handler {
	return &contextHandler{Handler: h.Handler.WithGroup(name)}
}

// --- NATS header trace propagation ---

type natsCarrier struct{ h nats.Header }

func (c natsCarrier) Get(key string) string { return c.h.Get(key) }
func (c natsCarrier) Set(key, val string)   { c.h.Set(key, val) }
func (c natsCarrier) Keys() []string {
	keys := make([]string, 0, len(c.h))
	for k := range c.h {
		keys = append(keys, k)
	}
	return keys
}

// InjectNATS writes the active trace context into NATS headers (publisher side).
func InjectNATS(ctx context.Context, h nats.Header) {
	otel.GetTextMapPropagator().Inject(ctx, natsCarrier{h})
}

// ExtractNATS returns a context continuing the trace carried by NATS headers
// (consumer side).
func ExtractNATS(ctx context.Context, h nats.Header) context.Context {
	return otel.GetTextMapPropagator().Extract(ctx, natsCarrier{h})
}
