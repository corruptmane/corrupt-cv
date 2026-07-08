"""Message handler: JobRequested -> LLM structuring -> JobStructured | JobFailed."""

import asyncio
from typing import NoReturn

import structlog
from cv_shared.consumer import TerminalError
from cv_shared.models import CV
from cv_shared.natsx import EVENT_FAILED, EVENT_STRUCTURED, publish_event
from cv_shared.proto_convert import cv_to_proto
from cvgen.catalog.v1 import catalog_pb2
from cvgen.events.v1 import events_pb2
from nats.aio.msg import Msg
from nats.js import JetStreamContext
from nats.js.errors import KeyNotFoundError
from nats.js.kv import KeyValue
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.models import Model
from valkey.asyncio import Valkey

from ai_processor.agent import generate_cv
from ai_processor.providers import UnsupportedProviderError, build_model

API_KEY_MISSING_ERROR = "API key no longer available; please resubmit"
UNKNOWN_MODEL_ERROR = "Unknown model selection; please choose a model from the catalog and resubmit"
INTERNAL_ERROR = "CV structuring failed unexpectedly; please resubmit"
AUTH_ERROR = "The AI provider rejected the API key; please check it and resubmit"
BAD_REQUEST_ERROR = "The AI provider rejected the request; please try a different model"
BAD_OUTPUT_ERROR = "The AI model returned an unusable response; please resubmit"
UNAVAILABLE_ERROR = "The AI provider is temporarily unavailable; please resubmit later"

_TRANSIENT_STATUSES = frozenset({408, 429})

log = structlog.get_logger("ai_processor.handler")


def apikey_key(job_id: str) -> str:
    return f"cv:apikey:{job_id}"


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, ModelHTTPError):
        return exc.status_code in _TRANSIENT_STATUSES or exc.status_code >= 500
    # Non-HTTP ModelAPIError covers connection/read failures inside the provider SDK.
    return isinstance(exc, ModelAPIError | TimeoutError | OSError)


class JobHandler:
    """Consumes cv.*.requested messages; dependencies are injectable for tests."""

    def __init__(
        self,
        *,
        js: JetStreamContext,
        kv: KeyValue,
        valkey: Valkey,
        retry_delays_s: tuple[float, ...] = (1.0, 3.0),
    ) -> None:
        self._js = js
        self._kv = kv
        self._valkey = valkey
        self._retry_delays_s = retry_delays_s

    async def __call__(self, msg: Msg) -> None:
        request = events_pb2.JobRequested()
        request.ParseFromString(msg.data)
        job_id = request.job_id
        log.info("processing job", job_id=job_id, model_key=request.model_key)

        entry = await self._model_entry(job_id, request.model_key)
        api_key = None
        if entry.provider != catalog_pb2.PROVIDER_FAKE:
            api_key = await self._claim_api_key(job_id)

        try:
            model = build_model(entry, api_key)
        except UnsupportedProviderError:
            log.warning("catalog entry has unsupported provider", job_id=job_id, model_key=request.model_key)
            await self._fail(job_id, UNKNOWN_MODEL_ERROR)
        del api_key  # held in the model/provider for this attempt only
        cv = await self._structure(job_id, model, request)

        structured = events_pb2.JobStructured(job_id=job_id, cv=cv_to_proto(cv))
        structured.occurred_at.GetCurrentTime()
        await publish_event(self._js, job_id, EVENT_STRUCTURED, structured.SerializeToString())
        log.info("job structured", job_id=job_id)

    async def _model_entry(self, job_id: str, model_key: str) -> catalog_pb2.ModelCatalogEntry:
        try:
            kv_entry = await self._kv.get(model_key)
        except KeyNotFoundError:
            await self._fail(job_id, UNKNOWN_MODEL_ERROR)
        if kv_entry.value is None:
            await self._fail(job_id, UNKNOWN_MODEL_ERROR)
        entry = catalog_pb2.ModelCatalogEntry()
        entry.ParseFromString(kv_entry.value)
        return entry

    async def _claim_api_key(self, job_id: str) -> str:
        raw = await self._valkey.getdel(apikey_key(job_id))
        if raw is None:
            await self._fail(job_id, API_KEY_MISSING_ERROR)
        return raw.decode() if isinstance(raw, bytes) else str(raw)

    async def _structure(self, job_id: str, model: Model, request: events_pb2.JobRequested) -> CV:
        attempts = len(self._retry_delays_s) + 1
        for attempt in range(attempts):
            try:
                return await generate_cv(
                    model,
                    personal_info=request.personal_info,
                    career_text=request.career_text,
                    job_description=request.job_description,
                )
            except UnexpectedModelBehavior:
                log.warning("model returned unusable output", job_id=job_id)
                await self._fail(job_id, BAD_OUTPUT_ERROR)
            except Exception as exc:
                if not _is_transient(exc):
                    if isinstance(exc, ModelHTTPError):
                        error = AUTH_ERROR if exc.status_code in (401, 403) else BAD_REQUEST_ERROR
                        log.warning("provider rejected request", job_id=job_id, status=exc.status_code)
                        await self._fail(job_id, error)
                    # The API key was already claimed via GETDEL, so a nak/redelivery
                    # can never succeed — it would only misreport the failure as a
                    # missing key. Terminate with the real reason instead.
                    log.exception("unexpected structuring failure", job_id=job_id)
                    await self._fail(job_id, INTERNAL_ERROR)
                if attempt + 1 == attempts:
                    log.warning("provider unavailable, retries exhausted", job_id=job_id, error=str(exc))
                    await self._fail(job_id, UNAVAILABLE_ERROR)
                log.warning("transient provider error, retrying", job_id=job_id, attempt=attempt, error=str(exc))
                await asyncio.sleep(self._retry_delays_s[attempt])
        raise AssertionError("unreachable")  # pragma: no cover

    async def _fail(self, job_id: str, error: str) -> NoReturn:
        failed = events_pb2.JobFailed(job_id=job_id, stage=events_pb2.JOB_STAGE_PROCESSING, error=error)
        failed.occurred_at.GetCurrentTime()
        await publish_event(self._js, job_id, EVENT_FAILED, failed.SerializeToString())
        raise TerminalError(error)
