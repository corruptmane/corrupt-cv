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

log = structlog.get_logger("cv_shared.natsx")


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
        await js.publish(subject, payload, msg_id=f"{job_id}:{event}", headers=headers or None)
