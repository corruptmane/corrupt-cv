"""Multiprovider CV extraction via PydanticAI. PROVIDER_TEST builds a
deterministic, valid CV locally (no provider call) so the whole pipeline runs
keyless in CI and demos."""

from typing import cast

from cv.v1 import generation_pb2 as g
from cv_worker import models
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider

SYSTEM_PROMPT = (
    "You are an expert technical recruiter and CV writer. Given a candidate's raw "
    "experience and a target job description, produce a concise, truthful, "
    "ATS-friendly CV tailored to the role. Emphasize the most relevant experience "
    "and skills; never invent employers, dates, or qualifications. Make highlights "
    "specific and results-oriented. Do NOT produce any contact details (name, "
    "email, phone, location, links) — those are supplied separately."
)


def _prompt(req: g.GenerationRequest) -> str:
    return (
        "Tailor a CV for this candidate to the target role.\n\n"
        f"== CANDIDATE EXPERIENCE ==\n{req.experience_text}\n\n"
        f"== TARGET JOB DESCRIPTION ==\n{req.job_description}\n"
    )


def _live_model(provider: int, model_id: str, api_key: str, ollama_base_url: str) -> Model:
    if provider == g.PROVIDER_OPENAI:
        return OpenAIChatModel(model_id or "gpt-4o-mini", provider=OpenAIProvider(api_key=api_key))
    if provider == g.PROVIDER_ANTHROPIC:
        return AnthropicModel(
            model_id or "claude-haiku-4-5", provider=AnthropicProvider(api_key=api_key)
        )
    if provider == g.PROVIDER_GEMINI:
        return GoogleModel(model_id or "gemini-2.0-flash", provider=GoogleProvider(api_key=api_key))
    if provider == g.PROVIDER_OLLAMA:
        return OpenAIChatModel(
            model_id or "llama3.2",
            provider=OpenAIProvider(base_url=ollama_base_url, api_key="ollama"),
        )
    raise ValueError(f"unsupported provider: {provider}")


def _demo_content(req: g.GenerationRequest) -> models.CVContent:
    return models.CVContent(
        summary=(
            "Deterministic demo CV (no AI provider used). Tailored toward: "
            + (req.job_description[:120] or "the target role")
            + "."
        ),
        experience=[
            models.Experience(
                company="Example Corp",
                position="Senior Engineer",
                start_date="2021-01",
                end_date=None,
                location="Remote",
                description=(req.experience_text[:200] or "Built and operated production systems."),
                highlights=[
                    "Aligned to the target job description",
                    "Generated without calling an AI provider",
                ],
            )
        ],
        education=[
            models.Education(
                institution="Example University",
                degree="BSc",
                field="Computer Science",
                start_date="2014",
                end_date="2018",
                gpa=None,
                highlights=[],
            )
        ],
        skills=[models.Skill(category="Core", items=["Go", "Python", "Kubernetes", "NATS"])],
        projects=[],
        languages=[models.Language(name="English", proficiency=models.LanguageProficiency.FLUENT)],
    )


async def generate_cv(
    req: g.GenerationRequest, api_key: str, ollama_base_url: str
) -> models.CVContent:
    """Produce the AI CV *content* (no contact block — that's assembled from the
    form by the caller via mapping.content_to_proto)."""
    if req.provider in (g.PROVIDER_TEST, g.PROVIDER_UNSPECIFIED):
        # Deterministic content with no provider call — keyless CI / demos.
        return _demo_content(req)

    model: Model = _live_model(req.provider, req.model, api_key, ollama_base_url)
    agent = Agent(model, output_type=models.CVContent, system_prompt=SYSTEM_PROMPT)
    result = await agent.run(_prompt(req))
    return cast(models.CVContent, result.output)
