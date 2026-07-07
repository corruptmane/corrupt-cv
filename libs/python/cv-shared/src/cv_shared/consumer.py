"""Generic pull-consume loop with ack-deadline heartbeats and trace propagation."""

import asyncio
from collections.abc import Awaitable, Callable

import structlog
from nats.aio.msg import Msg
from nats.js import JetStreamContext
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from cv_shared.natsx import extract_trace_context, job_id_from_subject

Handler = Callable[[Msg], Awaitable[None]]


class TerminalError(Exception):
    """Raised by handlers to stop redelivery; the handler has already reported the failure."""


async def _heartbeat(msg: Msg, interval_s: float) -> None:
    while True:
        await asyncio.sleep(interval_s)
        await msg.in_progress()


async def run_pull_loop(
    psub: JetStreamContext.PullSubscription,
    handler: Handler,
    *,
    service: str,
    heartbeat_s: float = 30.0,
    fetch_timeout_s: float = 5.0,
    nak_delay_s: float = 10.0,
) -> None:
    """Fetch messages one at a time and dispatch to handler until cancelled.

    handler returns → ack; handler raises TerminalError → term (no
    redelivery); anything else → nak with delay. While the handler runs,
    in_progress() heartbeats extend the ack deadline past ack_wait for
    long LLM calls.
    """
    log = structlog.get_logger(service)
    tracer = trace.get_tracer(service)
    while True:
        try:
            msgs = await psub.fetch(1, timeout=fetch_timeout_s)
        except TimeoutError:
            continue
        for msg in msgs:
            ctx = extract_trace_context(msg.headers)
            with tracer.start_as_current_span(
                f"consume {msg.subject}",
                context=ctx,
                kind=SpanKind.CONSUMER,
                attributes={
                    "messaging.system": "nats",
                    "messaging.destination.name": msg.subject,
                    "cvgen.job_id": job_id_from_subject(msg.subject),
                    "cvgen.event": msg.subject.rsplit(".", 1)[-1],
                },
            ) as span:
                heartbeat = asyncio.create_task(_heartbeat(msg, heartbeat_s))
                try:
                    await handler(msg)
                except TerminalError as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    log.warning("terminal failure", subject=msg.subject, error=str(exc))
                    await msg.term()
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    log.exception("handler failed, nak for redelivery", subject=msg.subject)
                    await msg.nak(delay=nak_delay_s)
                else:
                    await msg.ack()
                finally:
                    heartbeat.cancel()
