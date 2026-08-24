"""OpenTelemetry setup: OTLP/HTTP traces + logs, driven entirely by standard OTEL_* env vars."""

import os

from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_configured = False
_tracer_provider: TracerProvider | None = None
_logger_provider: LoggerProvider | None = None


def active_logger_provider() -> LoggerProvider | None:
    """The SDK LoggerProvider when OTel log export is active, else None."""
    return _logger_provider


def setup_otel(service_name: str) -> None:
    """No-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set (and the SDK isn't disabled). Idempotent."""
    global _configured, _tracer_provider, _logger_provider
    if _configured:
        return
    if os.environ.get("OTEL_SDK_DISABLED", "").lower() == "true":
        return
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return

    resource = Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME") or service_name})

    # _configured flips only AFTER both providers are built and registered: a
    # failure here (bad endpoint env, exporter construction error) must leave
    # the gate open so a later call can retry instead of silently doing nothing.
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(logger_provider)

    _tracer_provider = tracer_provider
    _logger_provider = logger_provider
    _configured = True


def shutdown() -> None:
    """Shut down the providers from setup_otel, flushing their batch processors. Safe when never configured."""
    global _configured, _tracer_provider, _logger_provider
    if not _configured:
        return
    _configured = False
    if _tracer_provider is not None:
        _tracer_provider.shutdown()
        _tracer_provider = None
    if _logger_provider is not None:
        _logger_provider.shutdown()
        _logger_provider = None
