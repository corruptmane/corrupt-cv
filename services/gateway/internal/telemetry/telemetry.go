// Package telemetry wires OpenTelemetry traces, metrics and logs for
// the gateway. Everything is driven by the standard OTEL_* environment
// variables and mirrors the Python services' conventions: telemetry is
// a strict no-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set, exporters
// are OTLP over HTTP and constructed arglessly (the SDK derives the
// per-signal URLs from the endpoint), the resource carries
// service.name from OTEL_SERVICE_NAME (fallback "gateway"), and trace
// context crosses NATS via W3C "traceparent"/"tracestate" headers.
package telemetry

import (
	"context"
	"errors"
	"os"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploghttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/log/global"
	"go.opentelemetry.io/otel/propagation"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.41.0"
)

// ScopeName is the instrumentation scope for gateway-authored spans,
// metrics and bridged logs.
const ScopeName = "cvgen.gateway"

// Enabled reports whether telemetry export is configured. It is the
// single switch: when false, Setup does nothing and callers must keep
// instrumentation off their hot paths.
func Enabled() bool {
	return os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT") != ""
}

// Setup installs the global TracerProvider, MeterProvider,
// LoggerProvider and W3C propagator, all exporting via OTLP/HTTP. It
// returns a shutdown function that flushes and stops every provider.
// When telemetry is disabled (Enabled() == false) it constructs
// nothing and returns a working no-op shutdown.
func Setup(ctx context.Context) (func(context.Context) error, error) {
	if !Enabled() {
		return func(context.Context) error { return nil }, nil
	}

	res, err := newResource()
	if err != nil {
		return nil, err
	}

	var shutdowns []func(context.Context) error
	shutdown := func(ctx context.Context) error {
		var errs []error
		// Reverse order: logs last so shutdown-time logs still flush.
		for i := len(shutdowns) - 1; i >= 0; i-- {
			errs = append(errs, shutdowns[i](ctx))
		}
		return errors.Join(errs...)
	}
	fail := func(err error) (func(context.Context) error, error) {
		_ = shutdown(ctx)
		return nil, err
	}

	// Traces.
	traceExp, err := otlptracehttp.New(ctx)
	if err != nil {
		return fail(err)
	}
	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(traceExp),
		sdktrace.WithResource(res),
	)
	shutdowns = append(shutdowns, tp.Shutdown)
	otel.SetTracerProvider(tp)

	// Metrics.
	metricExp, err := otlpmetrichttp.New(ctx)
	if err != nil {
		return fail(err)
	}
	mp := sdkmetric.NewMeterProvider(
		sdkmetric.WithReader(sdkmetric.NewPeriodicReader(metricExp)),
		sdkmetric.WithResource(res),
	)
	shutdowns = append(shutdowns, mp.Shutdown)
	otel.SetMeterProvider(mp)

	// Logs.
	logExp, err := otlploghttp.New(ctx)
	if err != nil {
		return fail(err)
	}
	lp := sdklog.NewLoggerProvider(
		sdklog.WithProcessor(sdklog.NewBatchProcessor(logExp)),
		sdklog.WithResource(res),
	)
	shutdowns = append(shutdowns, lp.Shutdown)
	global.SetLoggerProvider(lp)

	// W3C trace context + baggage, matching the Python default.
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	))

	return shutdown, nil
}

// newResource builds the shared resource: SDK defaults plus
// service.name from OTEL_SERVICE_NAME, falling back to "gateway".
func newResource() (*resource.Resource, error) {
	name := os.Getenv("OTEL_SERVICE_NAME")
	if name == "" {
		name = "gateway"
	}
	return resource.Merge(
		resource.Default(),
		resource.NewSchemaless(semconv.ServiceNameKey.String(name)),
	)
}
