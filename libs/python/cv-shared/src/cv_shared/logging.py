"""structlog JSON logging with OTel trace correlation and optional OTel log export."""

import logging
import sys

import structlog
from opentelemetry import trace
from opentelemetry._logs import Logger, SeverityNumber

from cv_shared import otel

_SEVERITY: dict[str, SeverityNumber] = {
    "debug": SeverityNumber.DEBUG,
    "info": SeverityNumber.INFO,
    "warning": SeverityNumber.WARN,
    "warn": SeverityNumber.WARN,
    "error": SeverityNumber.ERROR,
    "exception": SeverityNumber.ERROR,
    "critical": SeverityNumber.FATAL,
    "fatal": SeverityNumber.FATAL,
}

# "event" becomes the body, "level" the severity; trace_id/span_id/timestamp are
# carried natively by the OTel LogRecord, so exporting them as attributes too
# would only duplicate data.
_NON_ATTRIBUTE_KEYS = frozenset({"event", "level", "timestamp", "trace_id", "span_id"})

# (provider, logger) cache so the bridge doesn't hit the provider lock per log call.
_otel_logger_cache: tuple[object, Logger] | None = None


def _add_trace_ids(_logger: object, _method: str, event_dict: structlog.typing.EventDict) -> structlog.typing.EventDict:
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def _otel_attribute(value: object) -> str | bool | int | float:
    if isinstance(value, str | bool | int | float):
        return value
    return str(value)


def _emit_otel_log(_logger: object, method: str, event_dict: structlog.typing.EventDict) -> structlog.typing.EventDict:
    """Bridge every structlog event into the OTel logs pipeline; passthrough when OTel is off."""
    provider = otel.active_logger_provider()
    if provider is None:
        return event_dict

    global _otel_logger_cache
    if _otel_logger_cache is None or _otel_logger_cache[0] is not provider:
        _otel_logger_cache = (provider, provider.get_logger("cv_shared.logging"))
    otel_logger = _otel_logger_cache[1]

    level = str(event_dict.get("level", method))
    attributes = {
        k: _otel_attribute(v) for k, v in event_dict.items() if k not in _NON_ATTRIBUTE_KEYS and v is not None
    }
    otel_logger.emit(
        severity_number=_SEVERITY.get(level, SeverityNumber.INFO),
        severity_text=level.upper(),
        body=str(event_dict.get("event", "")),
        attributes=attributes or None,
    )
    return event_dict


def setup_logging(level: str = "INFO") -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_trace_ids,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _emit_otel_log,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level.upper()]),
        logger_factory=structlog.PrintLoggerFactory(sys.stderr),
        cache_logger_on_first_use=True,
    )
