"""Message handler: JobStructured -> Typst PDF -> S3 -> JobRendered | JobFailed."""

from typing import NoReturn, Protocol

import structlog
import typst
from cv_shared.consumer import TerminalError
from cv_shared.natsx import EVENT_FAILED, EVENT_RENDERED, publish_event
from cv_shared.proto_convert import cv_from_proto
from cv_shared.typst_json import cv_to_typst_json
from cvgen.events.v1 import events_pb2
from nats.aio.msg import Msg
from nats.js import JetStreamContext
from opentelemetry import trace

from cv_generator.storage import object_key

RENDER_ERROR = "The CV could not be rendered to PDF; please resubmit"

log = structlog.get_logger("cv_generator.handler")
tracer = trace.get_tracer("cv_generator.handler")


class RendererLike(Protocol):
    def render(self, cv_json: str) -> bytes: ...


class StorageLike(Protocol):
    async def put_pdf(self, key: str, data: bytes) -> None: ...


class JobHandler:
    """Consumes cv.*.structured messages; dependencies are injectable for tests."""

    def __init__(self, *, js: JetStreamContext, renderer: RendererLike, storage: StorageLike) -> None:
        self._js = js
        self._renderer = renderer
        self._storage = storage

    async def __call__(self, msg: Msg) -> None:
        structured = events_pb2.JobStructured()
        structured.ParseFromString(msg.data)
        job_id = structured.job_id
        log.info("rendering job", job_id=job_id)

        cv = cv_from_proto(structured.cv)
        cv_json = cv_to_typst_json(cv)
        try:
            with tracer.start_as_current_span("typst.render"):
                pdf = self._renderer.render(cv_json)
        except typst.TypstError as exc:
            log.warning("typst rendering failed", job_id=job_id, error=str(exc))
            await self._fail(job_id, RENDER_ERROR)

        # Storage/NATS errors propagate: nak + redelivery, the overwrite is idempotent.
        key = object_key(job_id)
        with tracer.start_as_current_span("s3.put"):
            await self._storage.put_pdf(key, pdf)

        rendered = events_pb2.JobRendered(job_id=job_id, pdf_object_key=key)
        rendered.occurred_at.GetCurrentTime()
        await publish_event(self._js, job_id, EVENT_RENDERED, rendered.SerializeToString())
        log.info("job rendered", job_id=job_id, pdf_object_key=key)

    async def _fail(self, job_id: str, error: str) -> NoReturn:
        failed = events_pb2.JobFailed(job_id=job_id, stage=events_pb2.JOB_STAGE_RENDERING, error=error)
        failed.occurred_at.GetCurrentTime()
        await publish_event(self._js, job_id, EVENT_FAILED, failed.SerializeToString())
        raise TerminalError(error)
