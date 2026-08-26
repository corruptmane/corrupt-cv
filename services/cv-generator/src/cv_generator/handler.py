"""Message handler: JobStructured -> Typst PDF -> S3 -> JobRendered | JobFailed."""

import asyncio
import time
from io import BytesIO
from typing import NoReturn, Protocol

import structlog
import typst
from cv_shared.consumer import TerminalError
from cv_shared.natsx import EVENT_FAILED, EVENT_RENDERED, job_id_from_subject, publish_event, publish_with_retry
from cv_shared.proto_convert import cv_from_proto, failure_detail
from cv_shared.typst_json import cv_to_typst_json
from cvgen.events.v1 import events_pb2
from google.protobuf.message import DecodeError
from natsio.jetstream import JsMsg
from natsio.jetstream.context import JetStreamContext
from opentelemetry import trace
from opentelemetry.metrics import get_meter
from pydantic import ValidationError
from pypdf import PdfReader

from cv_generator.storage import object_key

RENDER_ERROR = "The CV could not be rendered to PDF; please resubmit"
INVALID_INPUT_ERROR = "The submitted data could not be processed; please resubmit"
PAGE_LIMIT_ERROR = "The generated CV exceeded 2 pages; please shorten your career history and resubmit"
PAGE_LIMIT = 2

# Machine failure reasons — metric labels on cvgen.rendering.failures.total.
REASON_INVALID_INPUT = "invalid_input"
REASON_RENDER_FAILED = "render_failed"
REASON_PAGE_LIMIT = "page_limit"

log = structlog.get_logger("cv_generator.handler")
tracer = trace.get_tracer("cv_generator.handler")

_meter = get_meter("cv_generator.handler")
render_compiles = _meter.create_counter(
    "cvgen.render.compiles.total",
    description="Typst compile attempts by outcome.",
)
render_compile_duration = _meter.create_histogram(
    "cvgen.render.compile.duration",
    unit="s",
    description="Typst compile wall time.",
    explicit_bucket_boundaries_advisory=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
render_pages = _meter.create_histogram(
    "cvgen.render.pages",
    description="Pages of the rendered PDF.",
    explicit_bucket_boundaries_advisory=(1, 2, 3, 4, 5, 6, 8, 10),
)
rendering_failures = _meter.create_counter(
    "cvgen.rendering.failures.total",
    description="Rendering-stage job failures by machine reason.",
)
storage_put_duration = _meter.create_histogram(
    "cvgen.storage.put.duration",
    unit="s",
    description="Object storage PDF upload wall time.",
    explicit_bucket_boundaries_advisory=(0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
storage_put_bytes = _meter.create_histogram(
    "cvgen.storage.put.bytes",
    unit="By",
    description="Uploaded PDF size.",
    explicit_bucket_boundaries_advisory=(10240.0, 102400.0, 1048576.0, 5242880.0),
)


class RendererLike(Protocol):
    """Synchronous typst compiler facade; the handler runs it via asyncio.to_thread, off the event loop."""

    def render(self, cv_json: str) -> bytes: ...


class StorageLike(Protocol):
    async def put_pdf(self, key: str, data: bytes) -> None: ...


class JobHandler:
    """Consumes cv.*.structured messages; dependencies are injectable for tests."""

    def __init__(self, *, js: JetStreamContext, renderer: RendererLike, storage: StorageLike) -> None:
        self._js = js
        self._renderer = renderer
        self._storage = storage

    async def __call__(self, msg: JsMsg) -> None:
        # The subject is the identity authority: a poison payload may not parse
        # at all, yet its failure must still land on the right job.
        job_id = job_id_from_subject(msg.subject)
        try:
            structured = events_pb2.JobStructured()
            structured.ParseFromString(msg.data)
            log.info("rendering job", job_id=job_id)

            # Parsing and contract conversion stay inside the guard: malformed
            # protobuf or constraint violations must terminate the job, never
            # nak-loop the same poison payload until MaxDeliveries.
            cv = cv_from_proto(structured.cv)
            cv_json = cv_to_typst_json(cv)
        except (DecodeError, ValidationError, KeyError, ValueError) as exc:
            detail = failure_detail(exc)
            log.warning("unusable job payload", job_id=job_id, detail=detail)
            await self._fail(job_id, INVALID_INPUT_ERROR, reason=REASON_INVALID_INPUT, detail=detail)

        render_started = time.perf_counter()
        try:
            # F13: compile off the event loop. Caveat: typst-py 0.15.0 does NOT release the
            # GIL during compile (no PyO3 allow_threads anywhere in messense/typst-py src),
            # so the worker thread still blocks the interpreter and heartbeats may stall
            # during pathological compiles; realistic compiles are sub-second, severity low.
            # to_thread stays per owner decision: it isolates the blocking call behind the
            # standard offload seam and marginally improves shutdown responsiveness.
            with tracer.start_as_current_span("typst.render"):
                pdf = await asyncio.to_thread(self._renderer.render, cv_json)
        except typst.TypstError as exc:
            render_compiles.add(1, {"outcome": "error"})
            render_compile_duration.record(time.perf_counter() - render_started)
            log.warning("typst rendering failed", job_id=job_id, error=str(exc))
            await self._fail(job_id, RENDER_ERROR, reason=REASON_RENDER_FAILED)
        render_compiles.add(1, {"outcome": "ok"})
        render_compile_duration.record(time.perf_counter() - render_started)

        # W9: the page limit is a property of what rendering produced, so it is
        # checked on the rendered bytes — after the render span, before storage,
        # so a doomed PDF is never uploaded. Stage stays RENDERING.
        page_count = len(PdfReader(BytesIO(pdf)).pages)
        render_pages.record(page_count)
        if page_count > PAGE_LIMIT:
            log.warning("rendered CV exceeds page limit", job_id=job_id, pages=page_count)
            await self._fail(job_id, PAGE_LIMIT_ERROR, reason=REASON_PAGE_LIMIT)

        # Storage errors propagate: nak + redelivery, the overwrite is idempotent. The result
        # publish retries transient transport blips in-delivery first, then propagates likewise.
        key = object_key(job_id)
        put_started = time.perf_counter()
        with tracer.start_as_current_span("s3.put"):
            await self._storage.put_pdf(key, pdf)
        storage_put_duration.record(time.perf_counter() - put_started)
        storage_put_bytes.record(len(pdf))

        rendered = events_pb2.JobRendered(job_id=job_id, pdf_object_key=key)
        rendered.occurred_at.GetCurrentTime()
        await publish_with_retry(
            self._js,
            job_id,
            EVENT_RENDERED,
            rendered.SerializeToString(),
            service="cv-generator",
        )
        log.info("job rendered", job_id=job_id, pdf_object_key=key)

    async def _fail(self, job_id: str, error: str, *, reason: str, detail: str | None = None) -> NoReturn:
        rendering_failures.add(1, {"reason": reason})
        if detail is not None:
            error = f"{error} ({detail})"
        failed = events_pb2.JobFailed(job_id=job_id, stage=events_pb2.JOB_STAGE_RENDERING, error=error)
        failed.occurred_at.GetCurrentTime()
        await publish_event(self._js, job_id, EVENT_FAILED, failed.SerializeToString())
        raise TerminalError(error)
