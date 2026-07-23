"""OTel wiring tests: setup gating, the structlog→OTel log bridge, and NATS span semantics."""

import asyncio
from typing import Any, cast

import pytest
import structlog
from cv_shared import logging as cv_logging
from cv_shared import otel
from cv_shared.consumer import TerminalError, run_pull_loop
from cv_shared.natsx import publish_event
from natsio.jetstream import Consumer
from natsio.jetstream.context import JetStreamContext
from opentelemetry import trace
from opentelemetry._logs import SeverityNumber
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

JOB_ID = "7a1e5d70-9c2b-4f4e-8a3d-2b1c0d9e8f7a"


@pytest.fixture(autouse=True)
def _fresh_otel_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(otel, "_configured", False)
    monkeypatch.setattr(otel, "_logger_provider", None)
    monkeypatch.setattr(cv_logging, "_otel_logger_cache", None)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)


@pytest.fixture
def span_exporter(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    """Route trace.get_tracer to a private provider so tests never mutate the global one."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace, "get_tracer", lambda name, *a, **kw: provider.get_tracer(name))
    return exporter


# --- setup_otel gating ---


def test_setup_otel_without_endpoint_is_noop() -> None:
    before = trace.get_tracer_provider()
    otel.setup_otel("test-service")
    assert trace.get_tracer_provider() is before
    assert otel.active_logger_provider() is None


def test_setup_otel_disabled_env_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    before = trace.get_tracer_provider()
    otel.setup_otel("test-service")
    assert trace.get_tracer_provider() is before
    assert otel.active_logger_provider() is None


def test_setup_otel_with_endpoint_configures_and_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "env-name")
    set_providers: list[TracerProvider] = []
    monkeypatch.setattr(otel.trace, "set_tracer_provider", set_providers.append)
    set_log_providers: list[LoggerProvider] = []
    monkeypatch.setattr(otel, "set_logger_provider", set_log_providers.append)

    otel.setup_otel("arg-name")
    otel.setup_otel("arg-name")  # idempotent: no second provider

    assert len(set_providers) == 1
    assert len(set_log_providers) == 1
    assert otel.active_logger_provider() is set_log_providers[0]
    # OTEL_SERVICE_NAME wins over the argument.
    assert set_providers[0].resource.attributes["service.name"] == "env-name"
    assert set_log_providers[0].resource.attributes["service.name"] == "env-name"
    set_providers[0].shutdown()
    set_log_providers[0].shutdown()


# --- structlog → OTel logs bridge ---


def _event_dict() -> structlog.typing.EventDict:
    return {
        "event": "job structured",
        "level": "warning",
        "timestamp": "2026-01-01T00:00:00Z",
        "trace_id": "0" * 32,
        "span_id": "0" * 16,
        "job_id": JOB_ID,
        "attempt": 2,
        "detail": {"nested": True},
    }


def test_log_bridge_is_passthrough_when_inactive() -> None:
    event_dict = _event_dict()
    assert cv_logging._emit_otel_log(None, "warning", event_dict) is event_dict


def test_log_bridge_forwards_event_when_active(monkeypatch: pytest.MonkeyPatch) -> None:
    exporter = InMemoryLogRecordExporter()
    provider = LoggerProvider()
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    monkeypatch.setattr(otel, "_logger_provider", provider)

    tracer = TracerProvider().get_tracer("test")
    event_dict = _event_dict()
    with tracer.start_as_current_span("parent") as span:
        out = cv_logging._emit_otel_log(None, "warning", event_dict)

    assert out is event_dict  # stderr JSON pipeline sees the event unchanged
    (readable,) = exporter.get_finished_logs()
    record = readable.log_record
    assert record.body == "job structured"
    assert record.severity_number == SeverityNumber.WARN
    assert record.severity_text == "WARNING"
    assert record.attributes == {"job_id": JOB_ID, "attempt": 2, "detail": "{'nested': True}"}
    assert record.trace_id == span.get_span_context().trace_id
    assert record.span_id == span.get_span_context().span_id


# --- NATS span semantics ---


class FakeMsg:
    def __init__(self, subject: str) -> None:
        self.subject = subject
        self.headers: dict[str, str] | None = None
        self.data = b""
        self.acked = False
        self.termed = False
        self.naks: list[float | None] = []

    async def ack(self) -> None:
        self.acked = True

    async def term(self, reason: str | None = None) -> None:
        self.termed = True
        self.term_reason = reason

    async def nak(self, delay: float | None = None) -> None:
        self.naks.append(delay)

    async def in_progress(self) -> None:
        pass


class FakeConsumer:
    def __init__(self, msgs: list[FakeMsg]) -> None:
        self._msgs = list(msgs)

    async def fetch(self, max_messages: int, timeout: float) -> list[FakeMsg]:  # noqa: ASYNC109 - mirrors natsio fetch()
        if not self._msgs:
            raise asyncio.CancelledError
        return [self._msgs.pop(0)]


async def _run_loop(msg: FakeMsg, handler: Any) -> None:
    consumer = cast(Consumer, FakeConsumer([msg]))
    with pytest.raises(asyncio.CancelledError):
        await run_pull_loop(consumer, handler, service="test-service", fetch_timeout_s=0.01)


async def test_consume_span_kind_and_attributes(span_exporter: InMemorySpanExporter) -> None:
    msg = FakeMsg(f"cv.{JOB_ID}.requested")

    async def handler(_msg: Any) -> None:
        pass

    await _run_loop(msg, handler)

    assert msg.acked
    (span,) = span_exporter.get_finished_spans()
    assert span.name == f"consume cv.{JOB_ID}.requested"
    assert span.kind == SpanKind.CONSUMER
    assert span.attributes == {
        "messaging.system": "nats",
        "messaging.destination.name": f"cv.{JOB_ID}.requested",
        "cvgen.job_id": JOB_ID,
        "cvgen.event": "requested",
    }
    assert span.status.status_code == StatusCode.UNSET


async def test_consume_span_records_terminal_error(span_exporter: InMemorySpanExporter) -> None:
    msg = FakeMsg(f"cv.{JOB_ID}.requested")

    async def handler(_msg: Any) -> None:
        raise TerminalError("bad model output")

    await _run_loop(msg, handler)

    assert msg.termed
    (span,) = span_exporter.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description == "bad model output"
    assert [e.name for e in span.events] == ["exception"]


async def test_consume_span_records_nak_error(span_exporter: InMemorySpanExporter) -> None:
    msg = FakeMsg(f"cv.{JOB_ID}.requested")

    async def handler(_msg: Any) -> None:
        raise ConnectionError("s3 down")

    await _run_loop(msg, handler)

    assert msg.naks == [10.0]
    (span,) = span_exporter.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    assert [e.name for e in span.events] == ["exception"]


async def test_publish_event_producer_span_parents_injected_context(span_exporter: InMemorySpanExporter) -> None:
    published: list[tuple[str, bytes, dict[str, str], str | None]] = []

    class FakeJetStream:
        async def publish(
            self,
            subject: str,
            payload: bytes,
            *,
            headers: dict[str, str],
            msg_id: str | None = None,
        ) -> None:
            published.append((subject, payload, headers, msg_id))

    await publish_event(cast(JetStreamContext, FakeJetStream()), JOB_ID, "structured", b"payload")

    (span,) = span_exporter.get_finished_spans()
    assert span.name == "publish cv.structured"
    assert span.kind == SpanKind.PRODUCER
    assert span.attributes == {
        "messaging.system": "nats",
        "messaging.destination.name": f"cv.{JOB_ID}.structured",
        "cvgen.job_id": JOB_ID,
    }

    (subject, payload, headers, msg_id) = published[0]
    assert subject == f"cv.{JOB_ID}.structured"
    assert payload == b"payload"
    assert msg_id == f"{JOB_ID}:structured"
    # inject happened inside the span: downstream consumers parent onto the producer span
    ctx = span.get_span_context()
    assert ctx is not None
    assert headers["traceparent"].startswith(f"00-{ctx.trace_id:032x}-{ctx.span_id:016x}-")
