"""Handler unit tests with fake js/kv/valkey objects (no network)."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast

import ai_processor.handler as handler_module
import pytest
from ai_processor.handler import (
    API_KEY_MISSING_ERROR,
    CREDITS_EXHAUSTED_ERROR,
    INVALID_INPUT_ERROR,
    UNKNOWN_MODEL_ERROR,
    JobHandler,
    apikey_key,
)
from cv_shared.consumer import TerminalError
from cv_shared.proto_convert import cv_from_proto
from cvgen.catalog.v1 import catalog_pb2
from cvgen.cv.v1 import cv_pb2
from cvgen.events.v1 import events_pb2
from natsio.jetstream import JsMsg
from natsio.jetstream.context import JetStreamContext
from natsio.kv import KeyNotFoundError, KeyValue
from pydantic_ai.exceptions import ModelHTTPError
from valkey.asyncio import Valkey

JOB_ID = "0f9b2f6e-6f0f-4a63-9a1c-1c2d3e4f5a6b"


@dataclass
class FakeMsg:
    subject: str
    data: bytes
    headers: dict[str, str] | None = None


class FakeJetStream:
    def __init__(self, *, errors: Sequence[Exception] | None = None) -> None:
        self.published: list[tuple[str, bytes, dict[str, str] | None, str | None]] = []
        self.attempts = 0
        self._errors = list(errors or [])

    async def publish(
        self,
        subject: str,
        payload: bytes,
        *,
        headers: dict[str, str] | None = None,
        msg_id: str | None = None,
    ) -> None:
        self.attempts += 1
        if self._errors:
            raise self._errors.pop(0)
        self.published.append((subject, payload, headers, msg_id))


class FakeKV:
    def __init__(self, entries: dict[str, bytes]) -> None:
        self._entries = entries

    async def get(self, key: str) -> SimpleNamespace:
        if key not in self._entries:
            raise KeyNotFoundError
        return SimpleNamespace(value=self._entries[key])


class FakeValkey:
    def __init__(self, values: dict[str, bytes]) -> None:
        self._values = values
        self.getdel_calls: list[str] = []

    async def getdel(self, key: str) -> bytes | None:
        self.getdel_calls.append(key)
        return self._values.pop(key, None)


def _catalog_entry(provider: catalog_pb2.Provider.ValueType, key: str, model_id: str) -> bytes:
    return catalog_pb2.ModelCatalogEntry(
        key=key, provider=provider, model_id=model_id, display_name=key
    ).SerializeToString()


def _requested_msg(model_key: str) -> JsMsg:
    request = events_pb2.JobRequested(
        job_id=JOB_ID,
        career_text="Six years of backend work with Python, Go, NATS and Kubernetes.",
        job_description="Platform engineer building internal developer tooling.",
        personal_info=cv_pb2.PersonalInfo(
            name="Jane Doe",
            email="jane.doe@example.com",
            location_city="Lviv",
            location_country="Ukraine",
        ),
        model_key=model_key,
    )
    request.occurred_at.GetCurrentTime()
    return cast(JsMsg, FakeMsg(subject=f"cv.{JOB_ID}.requested", data=request.SerializeToString()))


def _handler(
    js: FakeJetStream, kv: FakeKV, valkey: FakeValkey, *, retry_delays_s: tuple[float, ...] = ()
) -> JobHandler:
    return JobHandler(
        js=cast(JetStreamContext, js),
        kv=cast(KeyValue, kv),
        valkey=cast(Valkey, valkey),
        retry_delays_s=retry_delays_s,
    )


@pytest.fixture
def sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record asyncio.sleep delays instead of waiting; only the retry paths sleep here."""
    calls: list[float] = []

    async def fake_sleep(delay: float, result: object = None) -> object:
        calls.append(delay)
        return result

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return calls


def _single_failure(js: FakeJetStream) -> events_pb2.JobFailed:
    assert len(js.published) == 1
    subject, payload, _headers, msg_id = js.published[0]
    assert subject == f"cv.{JOB_ID}.failed"
    assert msg_id == f"{JOB_ID}:failed"
    failed = events_pb2.JobFailed()
    failed.ParseFromString(payload)
    return failed


async def test_unknown_model_key_is_terminal_and_publishes_job_failed() -> None:
    js = FakeJetStream()
    handler = _handler(js, FakeKV({}), FakeValkey({}))

    with pytest.raises(TerminalError):
        await handler(_requested_msg("nope:not-a-model"))

    failed = _single_failure(js)
    assert failed.job_id == JOB_ID
    assert failed.stage == events_pb2.JOB_STAGE_PROCESSING
    assert failed.error == UNKNOWN_MODEL_ERROR


async def test_missing_api_key_is_terminal_and_publishes_job_failed() -> None:
    js = FakeJetStream()
    model_key = "anthropic/claude-sonnet-4-5"
    kv = FakeKV({model_key: _catalog_entry(catalog_pb2.PROVIDER_ANTHROPIC, model_key, "claude-sonnet-4-5")})
    valkey = FakeValkey({})  # key never stored (or already claimed/expired)
    handler = _handler(js, kv, valkey)

    with pytest.raises(TerminalError):
        await handler(_requested_msg(model_key))

    assert valkey.getdel_calls == [apikey_key(JOB_ID)]
    failed = _single_failure(js)
    assert failed.stage == events_pb2.JOB_STAGE_PROCESSING
    assert failed.error == API_KEY_MISSING_ERROR


async def test_fake_provider_runs_agent_and_publishes_job_structured() -> None:
    js = FakeJetStream()
    kv = FakeKV({"fake/canned": _catalog_entry(catalog_pb2.PROVIDER_FAKE, "fake/canned", "fake")})
    valkey = FakeValkey({})
    handler = _handler(js, kv, valkey)

    await handler(_requested_msg("fake/canned"))

    assert valkey.getdel_calls == []  # FAKE provider must skip the key handoff
    assert len(js.published) == 1
    subject, payload, _headers, msg_id = js.published[0]
    assert subject == f"cv.{JOB_ID}.structured"
    assert msg_id == f"{JOB_ID}:structured"

    structured = events_pb2.JobStructured()
    structured.ParseFromString(payload)
    assert structured.job_id == JOB_ID
    assert structured.HasField("occurred_at")

    cv = cv_from_proto(structured.cv)  # round-trips through pydantic validation
    assert cv.personal_info.name == "Jane Doe"
    assert str(cv.personal_info.email) == "jane.doe@example.com"
    assert cv.experience
    assert cv.skills


async def test_transient_publish_failure_is_retried_then_structured_event_published(sleep_calls: list[float]) -> None:
    js = FakeJetStream(errors=[TimeoutError("nats blip")])
    kv = FakeKV({"fake/canned": _catalog_entry(catalog_pb2.PROVIDER_FAKE, "fake/canned", "fake")})
    handler = _handler(js, kv, FakeValkey({}), retry_delays_s=(0.0,))

    await handler(_requested_msg("fake/canned"))  # must not raise; the delivery must ack

    assert len(js.published) == 1  # exactly ONE structured event published
    subject, _payload, _headers, msg_id = js.published[0]
    assert subject == f"cv.{JOB_ID}.structured"
    assert msg_id == f"{JOB_ID}:structured"
    assert js.attempts == 2  # one blip, one success
    assert sleep_calls == [0.0]


async def test_persistent_publish_failure_propagates_for_nak(sleep_calls: list[float]) -> None:
    js = FakeJetStream(errors=[ConnectionError("nats down")] * 8)
    kv = FakeKV({"fake/canned": _catalog_entry(catalog_pb2.PROVIDER_FAKE, "fake/canned", "fake")})
    handler = _handler(js, kv, FakeValkey({}), retry_delays_s=(0.0,))

    with pytest.raises(ConnectionError):  # nak-path contract: never swallowed into _fail
        await handler(_requested_msg("fake/canned"))

    assert js.published == []  # nothing published; nak + redelivery instead
    assert js.attempts == 2  # retried through the full delay budget before giving up
    assert sleep_calls == [0.0]


async def test_non_transient_publish_failure_propagates_without_retry(sleep_calls: list[float]) -> None:
    js = FakeJetStream(errors=[ValueError("bad payload")])
    kv = FakeKV({"fake/canned": _catalog_entry(catalog_pb2.PROVIDER_FAKE, "fake/canned", "fake")})
    handler = _handler(js, kv, FakeValkey({}), retry_delays_s=(0.0,))

    with pytest.raises(ValueError):
        await handler(_requested_msg("fake/canned"))

    assert js.attempts == 1  # non-transport errors must not be retried
    assert sleep_calls == []  # zero retry sleeps


async def test_malformed_request_is_terminal_and_publishes_invalid_input() -> None:
    js = FakeJetStream()
    handler = _handler(js, FakeKV({}), FakeValkey({}))

    # A poison payload must terminate the job (term, no redelivery), never let a
    # raw DecodeError escape into the nak loop.
    with pytest.raises(TerminalError):
        await handler(cast(JsMsg, FakeMsg(subject=f"cv.{JOB_ID}.requested", data=b"\x00\xffnot-a-proto-message")))

    failed = _single_failure(js)
    assert failed.job_id == JOB_ID  # identity recovered from the subject, not the payload
    assert failed.stage == events_pb2.JOB_STAGE_PROCESSING
    assert failed.error.startswith(INVALID_INPUT_ERROR)
    assert "DecodeError" in failed.error
    # PII discipline: the detail names the failure class, never the payload bytes.
    assert "\x00\xff" not in failed.error
    assert "not-a-proto" not in failed.error


async def test_invalid_personal_info_url_is_terminal_before_key_claim() -> None:
    js = FakeJetStream()
    model_key = "anthropic/claude-sonnet-4-5"
    kv = FakeKV({model_key: _catalog_entry(catalog_pb2.PROVIDER_ANTHROPIC, model_key, "claude-sonnet-4-5")})
    valkey = FakeValkey({apikey_key(JOB_ID): b"sk-test-one-shot"})
    request = events_pb2.JobRequested(
        job_id=JOB_ID,
        career_text="Six years of backend work.",
        job_description="Platform engineer.",
        personal_info=cv_pb2.PersonalInfo(
            name="Jane Doe",
            email="jane.doe@example.com",
            location_city="Lviv",
            location_country="Ukraine",
            links=[cv_pb2.Link(label="GitHub", url="notaurl")],
        ),
        model_key=model_key,
    )
    request.occurred_at.GetCurrentTime()
    msg = cast(JsMsg, FakeMsg(subject=f"cv.{JOB_ID}.requested", data=request.SerializeToString()))

    with pytest.raises(TerminalError):
        await _handler(js, kv, valkey)(msg)

    # The contract check fires before the GETDEL: a poisoned request must not
    # burn the one-shot API key on a job that can never succeed.
    assert valkey.getdel_calls == []
    failed = _single_failure(js)
    assert failed.stage == events_pb2.JOB_STAGE_PROCESSING
    assert failed.error.startswith(INVALID_INPUT_ERROR)
    assert "url" in failed.error  # field context surfaces; values never do
    assert "notaurl" not in failed.error


async def test_provider_402_is_terminal_with_credits_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    async def out_of_credits(*args: object, **kwargs: object) -> object:
        raise ModelHTTPError(status_code=402, model_name="claude-sonnet-4-5", body="insufficient credits")

    monkeypatch.setattr(handler_module, "generate_cv", out_of_credits)
    js = FakeJetStream()
    model_key = "anthropic/claude-sonnet-4-5"
    kv = FakeKV({model_key: _catalog_entry(catalog_pb2.PROVIDER_ANTHROPIC, model_key, "claude-sonnet-4-5")})
    handler = _handler(js, kv, FakeValkey({apikey_key(JOB_ID): b"sk-test"}))

    with pytest.raises(TerminalError):
        await handler(_requested_msg(model_key))

    failed = _single_failure(js)
    assert failed.error == CREDITS_EXHAUSTED_ERROR
    assert "try a different model" not in failed.error  # the old generic copy must be gone
