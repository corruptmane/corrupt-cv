"""The CV structuring agent: one shared Agent, per-request model injection."""

import hashlib
import json
from collections.abc import Sequence

import structlog
from cv_shared.models import CV, Education, Experience, Language, Project, Skill
from cv_shared.proto_convert import personal_info_from_proto
from cvgen.cv.v1 import cv_pb2
from opentelemetry import trace
from pydantic import BaseModel, ValidationError
from pydantic_ai import Agent, ModelSettings, capture_run_messages
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models import Model

from ai_processor.prompts import SYSTEM_PROMPT, user_prompt

log = structlog.get_logger("ai_processor.agent")


class GeneratedCV(BaseModel):
    """The model's output contract: professional content only.

    Contact data is deliberately absent — the request proto is authoritative
    and merged in after validation, so weak models can never fail the job on
    fields whose values would be discarded anyway.
    """

    summary: str
    experience: list[Experience]
    education: list[Education]
    skills: list[Skill]
    projects: list[Project] = []
    languages: list[Language] = []


cv_agent = Agent[None, GeneratedCV](output_type=GeneratedCV, instructions=SYSTEM_PROMPT, retries=3)
tracer = trace.get_tracer("ai_processor.agent")

_DIGEST_HEX_CHARS = 12


async def generate_cv(
    model: Model,
    *,
    personal_info: cv_pb2.PersonalInfo,
    career_text: str,
    job_description: str,
) -> CV:
    """Run the agent and merge its output with the request's contact data.

    The model produces professional content only: personal_info never
    enters its output contract, so the request's proto is authoritative
    by construction rather than by post-hoc overwrite.
    """
    info = personal_info_from_proto(personal_info)
    prompt = user_prompt(
        info.model_dump_json(),
        career_text,
        job_description,
    )
    with tracer.start_as_current_span("llm.generate"), capture_run_messages() as messages:
        try:
            result = await cv_agent.run(prompt, model=model, model_settings=ModelSettings(max_tokens=16384))
        except UnexpectedModelBehavior as exc:
            _log_run_diagnostics(messages, exc)
            raise
    cv = CV(personal_info=info, **result.output.model_dump())
    return cv


def _part_payload(part: object) -> str:
    """Normalize a message part to text for length/digest computation; never logged itself."""
    content = getattr(part, "content", None)
    if content is not None:
        if isinstance(content, str):
            return content
        try:
            return json.dumps(content, default=str)
        except (TypeError, ValueError):
            return str(content)
    args = getattr(part, "args", None)
    if args is not None:
        try:
            return json.dumps(args, default=str)
        except (TypeError, ValueError):
            return str(args)
    return ""


def _part_summary(part: object) -> dict[str, object]:
    payload = _part_payload(part)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:_DIGEST_HEX_CHARS]
    return {"type": type(part).__name__, "chars": len(payload), "sha256": digest}


def _message_summary(message: object) -> dict[str, object]:
    summary: dict[str, object] = {
        "role": getattr(message, "kind", type(message).__name__),
        "parts": [_part_summary(part) for part in getattr(message, "parts", [])],
    }
    finish_reason = getattr(message, "finish_reason", None)
    if finish_reason is not None:
        summary["finish_reason"] = finish_reason
    usage = getattr(message, "usage", None)
    if usage is not None:
        summary["input_tokens"] = getattr(usage, "input_tokens", None)
        summary["output_tokens"] = getattr(usage, "output_tokens", None)
    return summary


def _validation_structure(exc: BaseException) -> list[dict[str, object]]:
    """Field paths and error types from the ValidationError cause chain; never input values."""
    cause: BaseException | None = exc.__cause__
    while cause is not None:
        if isinstance(cause, ValidationError):
            return [{"loc": list(error["loc"]), "type": error["type"]} for error in cause.errors()]
        cause = cause.__cause__
    return []


def _log_run_diagnostics(messages: Sequence[object], exc: UnexpectedModelBehavior) -> None:
    """Content-free failure diagnostics: shapes, sizes, digests — never payloads.

    The per-message detail rides the DEBUG gate (cv_shared.logging installs a
    filtering bound logger that drops it unless LOG_LEVEL=DEBUG); the WARNING
    summary stays lean at every level.
    """
    all_parts = [part for message in messages for part in getattr(message, "parts", [])]
    log.warning(
        "model run failed",
        error=str(exc),
        message_count=len(messages),
        part_count=len(all_parts),
        validation_errors=_validation_structure(exc),
    )
    log.debug("model run diagnostics", messages=[_message_summary(message) for message in messages])
