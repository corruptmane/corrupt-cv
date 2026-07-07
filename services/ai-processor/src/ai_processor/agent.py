"""The CV structuring agent: one shared Agent, per-request model injection."""

from cv_shared.models import CV
from cv_shared.proto_convert import personal_info_from_proto
from cvgen.cv.v1 import cv_pb2
from opentelemetry import trace
from pydantic_ai import Agent
from pydantic_ai.models import Model

from ai_processor.prompts import SYSTEM_PROMPT, user_prompt

cv_agent = Agent[None, CV](output_type=CV, instructions=SYSTEM_PROMPT)
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
    with tracer.start_as_current_span("llm.generate"):
        result = await cv_agent.run(prompt, model=model)
    cv = result.output
    cv.personal_info = info
    return cv
