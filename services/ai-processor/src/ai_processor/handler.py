"""Message handler: JobRequested -> LLM structuring -> JobStructured | JobFailed."""

import asyncio
from typing import NoReturn

import structlog
from cv_shared.consumer import TerminalError
from cv_shared.models import CV
from cv_shared.natsx import EVENT_FAILED, EVENT_STRUCTURED, job_id_from_subject, publish_event, publish_with_retry
from cv_shared.proto_convert import cv_to_proto, failure_detail, personal_info_from_proto
from cvgen.catalog.v1 import catalog_pb2
from cvgen.events.v1 import events_pb2
from google.protobuf.message import DecodeError
from natsio.jetstream import JsMsg
from natsio.jetstream.context import JetStreamContext
from natsio.kv import KeyNotFoundError, KeyValue
from pydantic import ValidationError
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
INVALID_INPUT_ERROR = "The submitted data could not be processed; please resubmit"
CREDITS_EXHAUSTED_ERROR = "The AI provider account is out of credits; please top up the account and resubmit"

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

    async def __call__(self, msg: JsMsg) -> None:
        # The subject is the identity authority: a poison payload may not parse
        # at all, yet its failure must still land on the right job.
        job_id = job_id_from_subject(msg.subject)
        try:
            request = events_pb2.JobRequested()
            request.ParseFromString(msg.data)
            log.info("processing job", job_id=job_id, model_key=request.model_key)

            # Parsing and the personal-info contract check stay inside the guard
            # AND ahead of the API-key claim: a malformed or contract-violating
            # request must terminate the job instead of nak-looping the poison
            # payload or burning the one-shot key on a doomed attempt.
            personal_info_from_proto(request.personal_info)

            entry = await self._model_entry(job_id, request.model_key)
            api_key = None
            if entry.provider != catalog_pb2.PROVIDER_FAKE:
                api_key = await self._claim_api_key(job_id)
        except (DecodeError, ValidationError, KeyError, ValueError) as exc:
            detail = failure_detail(exc)
            log.warning("unusable job request", job_id=job_id, detail=detail)
            await self._fail(job_id, INVALID_INPUT_ERROR, detail=detail)

        try:
            model = build_model(entry, api_key)
        except UnsupportedProviderError:
            log.warning("catalog entry has unsupported provider", job_id=job_id, model_key=request.model_key)
            await self._fail(job_id, UNKNOWN_MODEL_ERROR)
        del api_key  # held in the model/provider for this attempt only
        cv = await self._structure(job_id, model, request)

        structured = events_pb2.JobStructured(job_id=job_id, cv=cv_to_proto(cv))
        structured.occurred_at.GetCurrentTime()
        await publish_with_retry(
            self._js,
            job_id,
            EVENT_STRUCTURED,
            structured.SerializeToString(),
            service="ai-processor",
            delays_s=self._retry_delays_s,
        )
        log.info("job structured", job_id=job_id)

    async def _model_entry(self, job_id: str, model_key: str) -> catalog_pb2.ModelCatalogEntry:
        try:
            kv_entry = await self._kv.get(model_key)
        except KeyNotFoundError:
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
            except UnexpectedModelBehavior as exc:
                log.warning("model returned unusable output", job_id=job_id, error=str(exc))
                await self._fail(job_id, BAD_OUTPUT_ERROR)
            except Exception as exc:
                if not _is_transient(exc):
                    if isinstance(exc, ModelHTTPError):
                        if exc.status_code in (401, 403):
                            error = AUTH_ERROR
                        elif exc.status_code == 402:
                            error = CREDITS_EXHAUSTED_ERROR
                        else:
                            error = BAD_REQUEST_ERROR
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

    async def _fail(self, job_id: str, error: str, *, detail: str | None = None) -> NoReturn:
        if detail is not None:
            error = f"{error} ({detail})"
        failed = events_pb2.JobFailed(job_id=job_id, stage=events_pb2.JOB_STAGE_PROCESSING, error=error)
        failed.occurred_at.GetCurrentTime()
        await publish_event(self._js, job_id, EVENT_FAILED, failed.SerializeToString())
        raise TerminalError(error)
