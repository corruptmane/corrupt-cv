"""The real Agent run against the fake FunctionModel: valid CV, no network."""

import ai_processor.agent as agent_module
import pytest
from ai_processor.agent import generate_cv
from ai_processor.fake import build_fake_model
from cv_shared.models import CV
from cvgen.cv.v1 import cv_pb2


class FakeCounter:
    def __init__(self) -> None:
        self.adds: list[tuple[int, dict[str, object]]] = []

    def add(self, amount: int, attributes: dict[str, object] | None = None) -> None:
        self.adds.append((amount, attributes or {}))


class FakeHistogram:
    def __init__(self) -> None:
        self.records: list[tuple[float, dict[str, object]]] = []

    def record(self, amount: float, attributes: dict[str, object] | None = None) -> None:
        self.records.append((amount, attributes or {}))


def _personal_info() -> cv_pb2.PersonalInfo:
    return cv_pb2.PersonalInfo(
        name="Jane Doe",
        email="jane.doe@example.com",
        phone="+380 67 000 1122",
        location_city="Lviv",
        location_country="Ukraine",
        links=[cv_pb2.Link(label="GitHub", url="https://github.com/janedoe")],
    )


async def test_fake_model_produces_valid_cv_with_personal_info_override() -> None:
    cv = await generate_cv(
        build_fake_model(),
        personal_info=_personal_info(),
        career_text="Six years of backend work.",
        job_description="Platform engineer role.",
        provider="fake",
        model_key="fake/canned",
    )

    assert isinstance(cv, CV)
    # The canned CV carries different contact data; the request must win.
    assert cv.personal_info.name == "Jane Doe"
    assert str(cv.personal_info.email) == "jane.doe@example.com"
    assert cv.personal_info.phone == "+380 67 000 1122"
    assert cv.personal_info.links[0].label == "GitHub"
    # The professional content comes from the model.
    assert cv.summary
    assert cv.experience
    assert cv.skills


async def test_generate_cv_records_attempt_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts, durations, tokens = FakeCounter(), FakeHistogram(), FakeCounter()
    monkeypatch.setattr(agent_module, "llm_attempts", attempts)
    monkeypatch.setattr(agent_module, "llm_request_duration", durations)
    monkeypatch.setattr(agent_module, "llm_tokens", tokens)

    cv = await generate_cv(
        build_fake_model(),
        personal_info=_personal_info(),
        career_text="x",
        job_description="y",
        provider="fake",
        model_key="fake/canned",
    )

    assert isinstance(cv, CV)
    assert attempts.adds == [(1, {"provider": "fake", "model_key": "fake/canned", "outcome": "ok"})]
    assert len(durations.records) == 1
    assert durations.records[0][1] == {"provider": "fake"}
    # The fake model reports real usage: one increment per direction.
    assert [attrs for _amount, attrs in tokens.adds] == [
        {"provider": "fake", "type": "input"},
        {"provider": "fake", "type": "output"},
    ]
    assert all(isinstance(amount, int) and amount > 0 for amount, _attrs in tokens.adds)


async def test_output_schema_sent_to_models_excludes_personal_info() -> None:
    """W9-followup: contact data never reaches the model's output contract."""
    import json

    import pytest
    from pydantic_ai import UnexpectedModelBehavior
    from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    captured: dict = {}

    def _spy(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if "schema" not in captured:
            captured["schema"] = info.output_tools[0].parameters_json_schema
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args="{}")])

    with pytest.raises(UnexpectedModelBehavior):
        await generate_cv(
            FunctionModel(_spy, model_name="schema-spy"),
            personal_info=_personal_info(),
            career_text="x",
            job_description="y",
            provider="fake",
            model_key="fake/spy",
        )

    schema = captured["schema"]
    assert "summary" in json.dumps(schema)
    assert "personal_info" not in json.dumps(schema)
