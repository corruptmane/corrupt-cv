"""structlog-based JSON logging to stdout, enriched with OTel trace/span ids.

Both app logs (``structlog.get_logger()``) and stdlib library logs (nats, etc.)
flow through one ProcessorFormatter so every line is JSON. Vector ships them to
VictoriaLogs (see observability/vector.yaml)."""

import logging
import sys
from typing import Any

import structlog
from opentelemetry import trace


def _add_trace_context(_logger: Any, _name: str, event: dict[str, Any]) -> dict[str, Any]:
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.is_valid:
        event["trace_id"] = format(ctx.trace_id, "032x")
        event["span_id"] = format(ctx.span_id, "016x")
    return event


def configure_logging(service: str, level: str = "info") -> None:
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        _add_trace_context,
        structlog.processors.TimeStamper(fmt="iso", key="time"),
    ]

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            structlog.processors.EventRenamer("msg"),
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    structlog.contextvars.bind_contextvars(service=service)
