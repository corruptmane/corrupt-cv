"""Generic pull-consume loop with ack-deadline heartbeats and trace propagation."""

import asyncio
import time
from collections.abc import Awaitable, Callable

import structlog
from natsio.jetstream import Consumer, JsMsg
from opentelemetry import trace
from opentelemetry.metrics import get_meter
from opentelemetry.trace import SpanKind, Status, StatusCode

from cv_shared.natsx import extract_trace_context, job_id_from_subject

Handler = Callable[[JsMsg], Awaitable[None]]

_meter = get_meter("cv_shared.consumer")
_consumed_total = _meter.create_counter(
    "cvgen.messages.consumed.total",
    description="Messages pulled from JetStream, by terminal dispatch outcome.",
)
_handle_duration = _meter.create_histogram(
    "cvgen.messages.handle.duration",
    unit="s",
    description="Handler wall time per message, including the ack/term/nak round trip.",
)


class TerminalError(Exception):
    """Raised by handlers to stop redelivery; the handler has already reported the failure."""


async def _heartbeat(msg: JsMsg, interval_s: float) -> None:
    while True:
        await asyncio.sleep(interval_s)
        await msg.in_progress()


async def run_pull_loop(
    consumer: Consumer,
    handler: Handler,
    *,
    service: str,
    stop_event: asyncio.Event | None = None,
    heartbeat_s: float = 30.0,
    fetch_timeout_s: float = 5.0,
    nak_delay_s: float = 10.0,
) -> None:
    """Fetch messages one at a time and dispatch to handler until cancelled or stopped.

    handler returns → ack; handler raises TerminalError → term (no
    redelivery); anything else → nak with delay. While the handler runs,
    in_progress() heartbeats extend the ack deadline past ack_wait for
    long LLM calls.

    Drain semantics: once stop_event is set, the loop finishes the
    in-flight message (through ack/term/nak) and then returns instead of
    fetching again, so a shutdown signal never abandons a half-handled
    job to redelivery.
    """
    log = structlog.get_logger(service)
    tracer = trace.get_tracer(service)
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            # A quiet interval yields an empty list, not an exception; the
            # defensive catch covers request-level natsio timeouts (which
            # subclass the builtin TimeoutError).
            msgs = await consumer.fetch(1, timeout=fetch_timeout_s)
        except TimeoutError:
            continue
        for msg in msgs:
            ctx = extract_trace_context(msg.headers)
            event = msg.subject.rsplit(".", 1)[-1]
            with tracer.start_as_current_span(
                f"consume {msg.subject}",
                context=ctx,
                kind=SpanKind.CONSUMER,
                attributes={
                    "messaging.system": "nats",
                    "messaging.destination.name": msg.subject,
                    "cvgen.job_id": job_id_from_subject(msg.subject),
                    "cvgen.event": event,
                },
            ) as span:
                heartbeat = asyncio.create_task(_heartbeat(msg, heartbeat_s))
                started = time.perf_counter()
                try:
                    await handler(msg)
                except TerminalError as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    log.warning("terminal failure", subject=msg.subject, error=str(exc))
                    await msg.term(str(exc))
                    outcome = "term"
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    log.exception("handler failed, nak for redelivery", subject=msg.subject)
                    await msg.nak(delay=nak_delay_s)
                    outcome = "nak"
                else:
                    # Residual window: an external cancel landing between handler
                    # return and this ack abandons the message un-acked (it will
                    # be redelivered); accepted at a 90s drain budget rather than
                    # shielding the ack.
                    await msg.ack()
                    outcome = "ack"
                finally:
                    heartbeat.cancel()
                # Reached only when a terminal action completed without raising;
                # a failed ack/term/nak propagates uncounted like before.
                _handle_duration.record(time.perf_counter() - started, {"event": event})
                _consumed_total.add(1, {"event": event, "outcome": outcome})
