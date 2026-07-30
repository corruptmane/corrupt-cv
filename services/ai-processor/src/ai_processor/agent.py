"""The CV structuring agent: one shared Agent, per-request model injection."""

import json

import structlog
from cv_shared.models import CV
from cv_shared.proto_convert import personal_info_from_proto
from cvgen.cv.v1 import cv_pb2
from opentelemetry import trace
from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models import Model

from ai_processor.prompts import SYSTEM_PROMPT, user_prompt

log = structlog.get_logger("ai_processor.agent")
cv_agent = Agent[None, CV](output_type=CV, instructions=SYSTEM_PROMPT, retries=3)
tracer = trace.get_tracer("ai_processor.agent")


async def generate_cv(
    model: Model,
    *,
    personal_info: cv_pb2.PersonalInfo,
    career_text: str,
    job_description: str,
) -> CV:
    """Run the agent and force personal_info back to the request's values.

    The model sees the personal info as context but must never control
    contact data, so the request's proto is authoritative.
    """
    info = personal_info_from_proto(personal_info)
    prompt = user_prompt(
        info.model_dump_json(),
        career_text,
        job_description,
    )
    with tracer.start_as_current_span("llm.generate"), capture_run_messages() as messages:
        try:
            result = await cv_agent.run(prompt, model=model)
        except UnexpectedModelBehavior:
            _log_messages(messages)
            raise
    cv = result.output
    cv.personal_info = info
    return cv


def _log_messages(messages: list) -> None:
    """Log captured run messages in a compact structured format."""
    parts = []
    for msg in messages:
        kind = type(msg).__name__
        for part in getattr(msg, "parts", []):
            part_kind = type(part).__name__
            content = ""
            if hasattr(part, "content") and isinstance(part.content, str):
                snippet = part.content[:500]
                content = snippet
            elif hasattr(part, "args"):
                try:
                    content = json.dumps(part.args)[:500]
                except (TypeError, ValueError):
                    content = str(part.args)[:500]
            elif hasattr(part, "tool_name"):
                content = f"tool={part.tool_name}"
            parts.append(f"{kind}.{part_kind}: {content}")
    log.warning("model conversation", messages=parts, count=len(messages))
