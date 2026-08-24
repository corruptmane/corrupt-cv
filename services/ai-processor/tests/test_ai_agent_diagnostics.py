"""W7: failure diagnostics must be content-free (no PII) and prompts must delimit user data.

The failing-run harness mirrors test_ai_agent.py / fake.py: a FunctionModel whose
output-tool calls never validate, driving the agent into UnexpectedModelBehavior.
"""

import json
import re
from typing import cast

import pytest
import structlog
from ai_processor import agent as agent_module
from ai_processor.agent import generate_cv
from ai_processor.prompts import SYSTEM_PROMPT, user_prompt
from cvgen.cv.v1 import cv_pb2
from pydantic_ai import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from structlog.testing import capture_logs

Record = dict[str, object]


@pytest.fixture(autouse=True)
def _fresh_structlog(monkeypatch: pytest.MonkeyPatch):
    """Other suites call setup_logging(), whose cached INFO filter would swallow DEBUG here."""
    structlog.reset_defaults()
    monkeypatch.setattr(agent_module, "log", structlog.get_logger("ai_processor.agent"))
    yield
    structlog.reset_defaults()


FIXTURE_NAME = "Oleksandra Kovalenko"
FIXTURE_EMAIL = "o.kovalenko@privatemx.dev"
FIXTURE_PHONE = "+380 99 555 7788"

CAREER_TEXT = "Built event pipelines.\nRan Kubernetes clusters."
JOB_TEXT = "Platform engineer role.\nGo and NATS."


def _personal_info() -> cv_pb2.PersonalInfo:
    return cv_pb2.PersonalInfo(
        name=FIXTURE_NAME,
        email=FIXTURE_EMAIL,
        phone=FIXTURE_PHONE,
        location_city="Lviv",
        location_country="Ukraine",
    )


def _failing_model() -> FunctionModel:
    """Output-tool args that never validate; the agent exhausts retries and raises."""

    def _respond(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        output_tool = info.output_tools[0]
        return ModelResponse(
            parts=[ToolCallPart(tool_name=output_tool.name, args='{"summary": "invalid-payload-marker"}')],
            finish_reason="tool_call",
        )

    return FunctionModel(_respond, model_name="bad-fake-cv")


async def _run_failing() -> list[Record]:
    with capture_logs() as records, pytest.raises(UnexpectedModelBehavior):
        await generate_cv(
            _failing_model(),
            personal_info=_personal_info(),
            career_text=f"Contact: {FIXTURE_NAME}, {FIXTURE_EMAIL}, {FIXTURE_PHONE}.\n{CAREER_TEXT}",
            job_description=JOB_TEXT,
        )
    return cast(list[Record], list(records))


def _blob(records: list[Record]) -> str:
    return json.dumps(records, default=str)


# --- content-free diagnostics ---------------------------------------------------


async def test_failure_logs_contain_no_pii() -> None:
    records = await _run_failing()

    blob = _blob(records)
    assert FIXTURE_EMAIL not in blob
    assert FIXTURE_NAME not in blob
    assert FIXTURE_PHONE not in blob


async def test_failure_diagnostics_expose_lengths_and_digests_only() -> None:
    records = await _run_failing()

    diagnostics = [record for record in records if record.get("event") == "model run diagnostics"]
    assert diagnostics, "expected per-message DEBUG diagnostics"
    messages = cast(list[Record], diagnostics[0]["messages"])
    assert messages
    parts: list[Record] = []
    roles: set[object] = set()
    responses: list[Record] = []
    for message in messages:
        parts.extend(cast(list[Record], message["parts"]))
        roles.add(message["role"])
        if message["role"] == "response":
            responses.append(message)
    assert parts
    for part in parts:
        assert set(part) == {"type", "chars", "sha256"}  # no content key may exist
        assert isinstance(part["chars"], int)
        assert part["chars"] >= 0
        digest = part["sha256"]
        assert isinstance(digest, str)
        assert re.fullmatch(r"[0-9a-f]{12}", digest)
    assert roles == {"request", "response"}
    for response in responses:
        assert "input_tokens" in response
        assert "output_tokens" in response
    assert any(response.get("finish_reason") == "tool_call" for response in responses)


async def test_validation_errors_logged_as_structure_only() -> None:
    records = await _run_failing()

    failures = [record for record in records if record.get("event") == "model run failed"]
    assert failures, "expected WARNING failure summary"
    validation_errors = cast(list[Record], failures[0]["validation_errors"])
    assert validation_errors
    locs: list[tuple[object, ...]] = []
    types: list[object] = []
    for error in validation_errors:
        loc = error["loc"]
        assert isinstance(loc, list)
        locs.append(tuple(loc))
        types.append(error["type"])
    assert ("experience",) in locs  # GeneratedCV: first required field the payload omits
    assert "missing" in types

    blob = _blob(records)
    assert "invalid-payload-marker" not in blob  # known bad input value never logged
    assert "input_value" not in blob  # raw pydantic error dicts would carry it


class _RecordingLogger:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def debug(self, event: str, **_kw: object) -> None:
        self.calls.append(("debug", event))

    def warning(self, event: str, **_kw: object) -> None:
        self.calls.append(("warning", event))


async def test_verbose_diagnostics_ride_the_debug_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-message detail is emitted at DEBUG only; cv_shared.logging filters it at INFO."""
    recorder = _RecordingLogger()
    monkeypatch.setattr(agent_module, "log", recorder)

    with pytest.raises(UnexpectedModelBehavior):
        await generate_cv(
            _failing_model(),
            personal_info=_personal_info(),
            career_text=CAREER_TEXT,
            job_description=JOB_TEXT,
        )

    events = [event for _, event in recorder.calls]
    assert "model run failed" in events  # lean summary stays at WARNING
    levels = [level for level, event in recorder.calls if event == "model run diagnostics"]
    assert levels == ["debug"]


# --- prompt delimiting ------------------------------------------------------------


def test_user_prompt_wraps_career_and_job_in_sentinels() -> None:
    prompt = user_prompt('{"name":"Jane"}', CAREER_TEXT, JOB_TEXT)

    assert prompt.index("<<<CAREER_HISTORY>>>") < prompt.index(CAREER_TEXT) < prompt.index("<<<END_CAREER_HISTORY>>>")
    assert prompt.index("<<<JOB_DESCRIPTION>>>") < prompt.index(JOB_TEXT) < prompt.index("<<<END_JOB_DESCRIPTION>>>")


def test_sentinels_are_consistent_upper_snake_fences() -> None:
    fences = re.findall(r"<<<([A-Z_]+)>>>", user_prompt("{}", CAREER_TEXT, JOB_TEXT))

    assert fences == ["CAREER_HISTORY", "END_CAREER_HISTORY", "JOB_DESCRIPTION", "END_JOB_DESCRIPTION"]


def test_control_chars_stripped_but_newlines_and_tabs_kept() -> None:
    dirty_career = f"A\x00B\x0bC\x1fD\nE\tF{CAREER_TEXT}"
    dirty_job = f"X\x00Y\x0bZ\nW{JOB_TEXT}"

    prompt = user_prompt("{}", dirty_career, dirty_job)

    for control in ("\x00", "\x0b", "\x1f"):
        assert control not in prompt
    assert f"ABCD\nE\tF{CAREER_TEXT}" in prompt  # \n and \t are legitimate formatting
    assert f"XYZ\nW{JOB_TEXT}" in prompt


def test_system_prompt_declares_fence_content_as_data_not_instructions() -> None:
    assert "untrusted candidate data" in SYSTEM_PROMPT
    assert SYSTEM_PROMPT.count("never instructions") == 1
