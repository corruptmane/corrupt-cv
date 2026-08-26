"""NATS helpers for the Python services, built on natsio.

The gateway is the single JetStream authority: it creates the stream, the
durable consumers, and the KV buckets at boot. Python services only bind
to pre-existing entities and publish events — they never create anything.
Binds retry with backoff so compose start order isn't load-bearing.
"""

import asyncio
from collections.abc import Mapping

import natsio
import structlog
from natsio.client import Client
from natsio.jetstream import Consumer, ConsumerNotFoundError, StreamNotFoundError
from natsio.jetstream.context import JetStreamContext
from natsio.kv import BucketNotFoundError, KeyValue
from opentelemetry import propagate, trace
from opentelemetry.context import Context
from opentelemetry.metrics import get_meter
from opentelemetry.trace import SpanKind

STREAM = "CV_EVENTS"
KV_MODEL_CATALOG = "model-catalog"

DURABLE_AI_PROCESSOR = "AI_PROCESSOR"
DURABLE_CV_GENERATOR = "CV_GENERATOR"

EVENT_REQUESTED = "requested"
EVENT_STRUCTURED = "structured"
EVENT_RENDERED = "rendered"
EVENT_FAILED = "failed"

_BIND_RETRY_DELAY_S = 2.0
_BIND_MAX_ATTEMPTS = 90

_PUBLISH_RETRY_DELAYS_S: tuple[float, ...] = (1.0, 3.0)

log = structlog.get_logger("cv_shared.natsx")

_publish_meter = get_meter("cv_shared.natsx")
_published_total = _publish_meter.create_counter(
    "cvgen.messages.published.total",
    description="Job event publish attempts to JetStream, by outcome.",
)
_publish_retries_total = _publish_meter.create_counter(
    "cvgen.messages.publish.retries.total",
    description="Transient publish retries within one delivery budget.",
)


def event_subject(job_id: str, event: str) -> str:
    return f"cv.{job_id}.{event}"


def job_id_from_subject(subject: str) -> str:
    return subject.split(".")[1]


async def connect(url: str, name: str) -> Client:
    return await natsio.connect(url, name=name)


async def bind_pull_consumer(js: JetStreamContext, durable: str) -> Consumer:
    """Bind to an existing durable pull consumer, waiting for the gateway to provision it."""
    for _ in range(_BIND_MAX_ATTEMPTS):
        try:
            stream = await js.stream(STREAM)
            return await stream.consumer(durable)
        except (StreamNotFoundError, ConsumerNotFoundError):
            log.warning("consumer not provisioned yet, retrying", stream=STREAM, durable=durable)
            await asyncio.sleep(_BIND_RETRY_DELAY_S)
    raise RuntimeError(f"durable consumer {durable!r} on stream {STREAM!r} was never provisioned")


async def bind_kv(js: JetStreamContext, bucket: str) -> KeyValue:
    """Bind to an existing KV bucket, waiting for the gateway to provision it."""
    for _ in range(_BIND_MAX_ATTEMPTS):
        try:
            return await js.key_value(bucket)
        except BucketNotFoundError:
            log.warning("kv bucket not provisioned yet, retrying", bucket=bucket)
            await asyncio.sleep(_BIND_RETRY_DELAY_S)
    raise RuntimeError(f"kv bucket {bucket!r} was never provisioned")


def inject_trace_headers(headers: Mapping[str, str] | None = None) -> dict[str, str]:
    out = dict(headers or {})
    propagate.inject(out)
    return out


def extract_trace_context(headers: Mapping[str, str] | None) -> Context:
    return propagate.extract(dict(headers or {}))


async def publish_event(
    js: JetStreamContext,
    job_id: str,
    event: str,
    payload: bytes,
) -> None:
    """Publish a job event with trace propagation and an idempotent per-event msg id."""
    subject = event_subject(job_id, event)
    tracer = trace.get_tracer("cv_shared.natsx")
    with tracer.start_as_current_span(
        f"publish cv.{event}",
        kind=SpanKind.PRODUCER,
        attributes={
            "messaging.system": "nats",
            "messaging.destination.name": subject,
            "cvgen.job_id": job_id,
        },
    ):
        # Inject inside the span so the consumer's extracted parent is this producer span.
        headers = inject_trace_headers()
        try:
            await js.publish(subject, payload, msg_id=f"{job_id}:{event}", headers=headers or None)
        except Exception:
            _published_total.add(1, {"event": event, "outcome": "error"})
            raise
        _published_total.add(1, {"event": event, "outcome": "ok"})


async def publish_with_retry(
    js: JetStreamContext,
    job_id: str,
    event: str,
    payload: bytes,
    *,
    service: str,
    delays_s: tuple[float, ...] = _PUBLISH_RETRY_DELAYS_S,
) -> None:
    """Publish a job event, retrying transient transport errors within this delivery.

    A publish failure would otherwise nak the message and redeliver the whole
    job — re-running the LLM call or render/S3 put just to republish a result
    that already existed. Only conservative connection/transport errors are
    retried (natsio request timeouts subclass builtin TimeoutError); anything
    else, or an exhausted budget, re-raises so the caller's nak semantics apply.
    """
    attempts = len(delays_s) + 1
    for attempt in range(attempts):
        try:
            await publish_event(js, job_id, event, payload)
            return
        except (TimeoutError, ConnectionError, OSError) as exc:
            if attempt + 1 == attempts:
                log.warning(
                    "publish failed, retries exhausted",
                    service=service,
                    job_id=job_id,
                    event_type=event,
                    error=str(exc),
                )
                raise
            log.warning(
                "transient publish error, retrying",
                service=service,
                job_id=job_id,
                event_type=event,
                attempt=attempt,
                error=str(exc),
            )
            _publish_retries_total.add(1, {"event": event})
            await asyncio.sleep(delays_s[attempt])
    raise AssertionError("unreachable")  # pragma: no cover
