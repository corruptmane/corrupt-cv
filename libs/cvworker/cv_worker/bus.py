"""NATS JetStream helpers for the workers: connect, wait for the (gateway-owned)
stream, publish protobuf, and a durable pull-consumer loop that continues the
trace carried in message headers.

Workers never create the stream — the gateway owns it. They poll for its
existence on startup and fail fast if it never appears."""

import asyncio
from collections.abc import Awaitable, Callable

import nats
import structlog
from nats.aio.msg import Msg
from nats.errors import TimeoutError as NatsTimeoutError
from nats.js import JetStreamContext
from nats.js.errors import NotFoundError
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from .telemetry import extract_context

log = structlog.get_logger("cv_worker.bus")
_tracer = trace.get_tracer("cv_worker.bus")

Handler = Callable[[Msg], Awaitable[None]]


class Bus:
    def __init__(self, nc: nats.NATS, js: JetStreamContext, stream: str) -> None:
        self._nc = nc
        self._js = js
        self._stream = stream
        self._ready = False

    @classmethod
    async def connect(cls, url: str, stream: str) -> "Bus":
        nc = await nats.connect(url, max_reconnect_attempts=-1, reconnect_time_wait=1)
        return cls(nc, nc.jetstream(), stream)

    async def wait_for_stream(self, attempts: int = 60, delay: float = 1.0) -> None:
        for _ in range(attempts):
            try:
                await self._js.stream_info(self._stream)
                return
            except NotFoundError:
                await asyncio.sleep(delay)
        raise RuntimeError(
            f"stream {self._stream!r} not found after {attempts} attempts "
            "(the gateway owns stream creation)"
        )

    def is_ready(self) -> bool:
        return self._nc.is_connected and self._ready

    async def publish(self, subject: str, payload: bytes, headers: dict[str, str]) -> None:
        await self._js.publish(subject, payload, headers=headers)

    async def run_consumer(self, durable: str, subject: str, handler: Handler) -> None:
        """Wait for the stream, bind the durable pull consumer, then dispatch each
        message in a CONSUMER span linked to the producer's trace. Runs until cancelled."""
        await self.wait_for_stream()
        psub = await self._js.pull_subscribe(subject, durable=durable)
        self._ready = True
        log.info("consumer started", durable=durable, subject=subject)
        while True:
            try:
                msgs = await psub.fetch(1, timeout=5)
            except NatsTimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            for msg in msgs:
                await self._dispatch(msg, handler)

    async def _dispatch(self, msg: Msg, handler: Handler) -> None:
        parent = extract_context(msg.headers)
        with _tracer.start_as_current_span(
            f"process {msg.subject}", context=parent, kind=SpanKind.CONSUMER
        ):
            try:
                await handler(msg)
                await msg.ack()
            except Exception:
                log.exception("handler failed", subject=msg.subject)
                await msg.nak()

    async def close(self) -> None:
        await self._nc.drain()
