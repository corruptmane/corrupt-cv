"""OpenTelemetry wiring: traces over OTLP/gRPC (push to the collector), metrics
via a Prometheus reader (pulled from the ops server's /metrics), and W3C
trace-context propagation across NATS headers.

Exporters never block startup; an unreachable collector just drops spans."""

from opentelemetry import metrics, propagate, trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def setup_telemetry() -> None:
    # Resource auto-reads OTEL_SERVICE_NAME + OTEL_RESOURCE_ATTRIBUTES from env.
    resource = Resource.create()

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    # PrometheusMetricReader registers with the default prometheus_client
    # registry; the ops server exposes it at /metrics for VictoriaMetrics to scrape.
    metrics.set_meter_provider(
        MeterProvider(resource=resource, metric_readers=[PrometheusMetricReader()])
    )


def inject_headers() -> dict[str, str]:
    """Serialize the active trace context into NATS-publishable headers."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


def extract_context(headers: dict[str, str] | None) -> Context:
    """Reconstruct a parent context from received NATS headers."""
    return propagate.extract(headers or {})
