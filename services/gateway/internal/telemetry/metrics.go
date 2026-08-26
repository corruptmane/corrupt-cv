// Instrument constructors that fall back to no-op implementations
// instead of surfacing creation errors. A rejected name or conflicting
// instrument must never take the process down — nor leave a nil
// instrument behind that panics on first use. The fallback instruments
// come from the noop meter provider, whose constructors never fail.
package telemetry

import (
	"go.opentelemetry.io/otel/metric"
	"go.opentelemetry.io/otel/metric/noop"
)

var fallbackMeter = noop.NewMeterProvider().Meter("cvgen.fallback")

// Int64Counter returns name's counter from meter, or a no-op counter.
func Int64Counter(meter metric.Meter, name string, opts ...metric.Int64CounterOption) metric.Int64Counter {
	c, err := meter.Int64Counter(name, opts...)
	if err != nil {
		c, _ = fallbackMeter.Int64Counter(name)
		return c
	}
	return c
}

// Float64Histogram returns name's histogram from meter, or a no-op one.
func Float64Histogram(meter metric.Meter, name string, opts ...metric.Float64HistogramOption) metric.Float64Histogram {
	h, err := meter.Float64Histogram(name, opts...)
	if err != nil {
		h, _ = fallbackMeter.Float64Histogram(name)
		return h
	}
	return h
}

// Int64Histogram returns name's histogram from meter, or a no-op one.
func Int64Histogram(meter metric.Meter, name string, opts ...metric.Int64HistogramOption) metric.Int64Histogram {
	h, err := meter.Int64Histogram(name, opts...)
	if err != nil {
		h, _ = fallbackMeter.Int64Histogram(name)
		return h
	}
	return h
}

// Int64Gauge returns name's gauge from meter, or a no-op one.
func Int64Gauge(meter metric.Meter, name string, opts ...metric.Int64GaugeOption) metric.Int64Gauge {
	g, err := meter.Int64Gauge(name, opts...)
	if err != nil {
		g, _ = fallbackMeter.Int64Gauge(name)
		return g
	}
	return g
}

// Int64ObservableGauge returns name's observable gauge from meter, or a
// no-op one.
func Int64ObservableGauge(meter metric.Meter, name string, opts ...metric.Int64ObservableGaugeOption) metric.Int64ObservableGauge {
	g, err := meter.Int64ObservableGauge(name, opts...)
	if err != nil {
		g, _ = fallbackMeter.Int64ObservableGauge(name)
		return g
	}
	return g
}
