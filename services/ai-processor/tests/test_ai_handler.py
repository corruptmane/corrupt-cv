"""Handler unit tests with fake js/kv/valkey objects (no network)."""

from types import SimpleNamespace
from typing import Any, cast

import pytest
from ai_processor.handler import API_KEY_MISSING_ERROR, UNKNOWN_MODEL_ERROR, JobHandler, apikey_key
from cv_shared.consumer import TerminalError
from cv_shared.proto_convert import cv_from_proto
from cvgen.catalog.v1 import catalog_pb2
from cvgen.cv.v1 import cv_pb2
from cvgen.events.v1 import events_pb2
from nats.aio.msg import Msg
from nats.js import JetStreamContext
from nats.js.errors import KeyNotFoundError
from nats.js.kv import KeyValue
from valkey.asyncio import Valkey

JOB_ID = "0f9b2f6e-6f0f-4a63-9a1c-1c2d3e4f5a6b"


class FakeJetStream:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes, dict[str, str] | None]] = []

    async def publish(self, subject: str, payload: bytes, headers: dict[str, str] | None = None) -> None:
        self.published.append((subject, payload, headers))


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


def _requested_msg(model_key: str) -> Msg:
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
    return Msg(_client=cast(Any, None), subject=f"cv.{JOB_ID}.requested", data=request.SerializeToString())


def _handler(js: FakeJetStream, kv: FakeKV, valkey: FakeValkey) -> JobHandler:
    return JobHandler(
        js=cast(JetStreamContext, js),
        kv=cast(KeyValue, kv),
        valkey=cast(Valkey, valkey),
        retry_delays_s=(),
    )


def _single_failure(js: FakeJetStream) -> events_pb2.JobFailed:
    assert len(js.published) == 1
    subject, payload, headers = js.published[0]
    assert subject == f"cv.{JOB_ID}.failed"
    assert headers is not None
    assert headers["Nats-Msg-Id"] == f"{JOB_ID}:failed"
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
    subject, payload, headers = js.published[0]
    assert subject == f"cv.{JOB_ID}.structured"
    assert headers is not None
    assert headers["Nats-Msg-Id"] == f"{JOB_ID}:structured"

    structured = events_pb2.JobStructured()
    structured.ParseFromString(payload)
    assert structured.job_id == JOB_ID
    assert structured.HasField("occurred_at")

    cv = cv_from_proto(structured.cv)  # round-trips through pydantic validation
    assert cv.personal_info.name == "Jane Doe"
    assert str(cv.personal_info.email) == "jane.doe@example.com"
    assert cv.experience
    assert cv.skills
