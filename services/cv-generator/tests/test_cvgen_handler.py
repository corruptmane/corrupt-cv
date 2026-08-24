"""Handler unit tests with fake js/renderer/storage objects (no network)."""

import asyncio
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

import pytest
import typst
from cv_generator.handler import INVALID_INPUT_ERROR, RENDER_ERROR, JobHandler
from cv_shared.consumer import TerminalError
from cvgen.cv.v1 import cv_pb2
from cvgen.events.v1 import events_pb2
from natsio.jetstream import JsMsg
from natsio.jetstream.context import JetStreamContext

JOB_ID = "7a1e5d70-9c2b-4f4e-8a3d-2b1c0d9e8f7a"


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


class FakeRenderer:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.rendered: list[str] = []
        self.render_threads: list[int] = []

    def render(self, cv_json: str) -> bytes:
        self.render_threads.append(threading.get_ident())
        if self.error is not None:
            raise self.error
        self.rendered.append(cv_json)
        return b"%PDF-fake" + b"x" * 64


class FakeStorage:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.written: list[tuple[str, bytes]] = []

    async def put_pdf(self, key: str, data: bytes) -> None:
        if self.error is not None:
            raise self.error
        self.written.append((key, data))


def _valid_cv() -> cv_pb2.CV:
    return cv_pb2.CV(
        personal_info=cv_pb2.PersonalInfo(
            name="Jane Doe",
            email="jane.doe@example.com",
            location_city="Lviv",
            location_country="Ukraine",
        ),
        summary="Backend engineer.",
        experience=[
            cv_pb2.Experience(
                company="Acme Corp",
                position="Engineer",
                start_date="2021-01",
                location="Lviv, Ukraine",
                description="Platform team.",
                highlights=["Did things."],
            )
        ],
        skills=[cv_pb2.Skill(category="Languages", items=["Python"])],
    )


def _structured_msg(cv: cv_pb2.CV | None = None) -> JsMsg:
    structured = events_pb2.JobStructured(job_id=JOB_ID, cv=cv if cv is not None else _valid_cv())
    structured.occurred_at.GetCurrentTime()
    return cast(JsMsg, FakeMsg(subject=f"cv.{JOB_ID}.structured", data=structured.SerializeToString()))


def _handler(js: FakeJetStream, renderer: FakeRenderer, storage: FakeStorage) -> JobHandler:
    return JobHandler(js=cast(JetStreamContext, js), renderer=renderer, storage=storage)


@pytest.fixture
def sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record asyncio.sleep delays instead of waiting; only the publish-retry path sleeps here."""
    calls: list[float] = []

    async def fake_sleep(delay: float, result: object = None) -> object:
        calls.append(delay)
        return result

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return calls


async def test_success_uploads_pdf_and_publishes_job_rendered() -> None:
    js = FakeJetStream()
    renderer = FakeRenderer()
    storage = FakeStorage()

    await _handler(js, renderer, storage)(_structured_msg())

    # end_date=None must reach the template as "Present", never null.
    assert '"Present"' in renderer.rendered[0]
    assert storage.written == [(f"cvs/{JOB_ID}.pdf", b"%PDF-fake" + b"x" * 64)]

    assert len(js.published) == 1
    subject, payload, _headers, msg_id = js.published[0]
    assert subject == f"cv.{JOB_ID}.rendered"
    assert msg_id == f"{JOB_ID}:rendered"
    rendered = events_pb2.JobRendered()
    rendered.ParseFromString(payload)
    assert rendered.job_id == JOB_ID
    assert rendered.pdf_object_key == f"cvs/{JOB_ID}.pdf"
    assert rendered.HasField("occurred_at")


async def test_render_runs_off_the_event_loop_thread() -> None:
    # F13/W8: the sync typst compile must not occupy the event-loop thread.
    js = FakeJetStream()
    renderer = FakeRenderer()
    storage = FakeStorage()
    loop_thread = threading.get_ident()

    await _handler(js, renderer, storage)(_structured_msg())

    assert len(renderer.render_threads) == 1
    assert renderer.render_threads[0] != loop_thread


async def test_typst_error_is_terminal_and_publishes_job_failed() -> None:
    js = FakeJetStream()
    storage = FakeStorage()

    renderer = FakeRenderer(error=typst.TypstError("bad template input", "error: bad template input"))
    with pytest.raises(TerminalError):
        await _handler(js, renderer, storage)(_structured_msg())

    assert storage.written == []
    assert len(js.published) == 1
    subject, payload, _headers, _msg_id = js.published[0]
    assert subject == f"cv.{JOB_ID}.failed"
    failed = events_pb2.JobFailed()
    failed.ParseFromString(payload)
    assert failed.stage == events_pb2.JOB_STAGE_RENDERING
    assert failed.error == RENDER_ERROR


async def test_storage_error_propagates_for_redelivery() -> None:
    js = FakeJetStream()

    with pytest.raises(ConnectionError):
        await _handler(js, FakeRenderer(), FakeStorage(error=ConnectionError("s3 down")))(_structured_msg())

    assert js.published == []  # no rendered/failed event; nak + redelivery instead


async def test_transient_publish_failure_is_retried_then_rendered_event_published(sleep_calls: list[float]) -> None:
    js = FakeJetStream(errors=[TimeoutError("nats blip")])

    await _handler(js, FakeRenderer(), FakeStorage())(_structured_msg())  # must not raise; the delivery must ack

    assert len(js.published) == 1  # exactly ONE rendered event published
    subject, payload, _headers, msg_id = js.published[0]
    assert subject == f"cv.{JOB_ID}.rendered"
    assert msg_id == f"{JOB_ID}:rendered"
    rendered = events_pb2.JobRendered()
    rendered.ParseFromString(payload)
    assert rendered.job_id == JOB_ID
    assert js.attempts == 2  # one blip, one success
    assert sleep_calls == [1.0]  # slept once before the successful retry


async def test_persistent_publish_failure_propagates_for_nak(sleep_calls: list[float]) -> None:
    js = FakeJetStream(errors=[ConnectionError("nats down")] * 8)

    with pytest.raises(ConnectionError):  # nak-path contract: never swallowed into _fail
        await _handler(js, FakeRenderer(), FakeStorage())(_structured_msg())

    assert js.published == []  # no rendered/failed event; nak + redelivery instead
    assert js.attempts == 3  # retried through the full delay budget before giving up
    assert sleep_calls == [1.0, 3.0]


async def test_non_transient_publish_failure_propagates_without_retry(sleep_calls: list[float]) -> None:
    js = FakeJetStream(errors=[ValueError("bad payload")])

    with pytest.raises(ValueError):
        await _handler(js, FakeRenderer(), FakeStorage())(_structured_msg())

    assert js.attempts == 1  # non-transport errors must not be retried
    assert sleep_calls == []  # zero retry sleeps


def _published_failure(js: FakeJetStream) -> events_pb2.JobFailed:
    assert len(js.published) == 1
    subject, payload, _headers, _msg_id = js.published[0]
    assert subject == f"cv.{JOB_ID}.failed"
    failed = events_pb2.JobFailed()
    failed.ParseFromString(payload)
    return failed


async def test_malformed_payload_is_terminal_and_publishes_invalid_input() -> None:
    js = FakeJetStream()

    # A poison payload must terminate the job (term, no redelivery), never let a
    # raw DecodeError escape into the nak loop.
    with pytest.raises(TerminalError):
        await _handler(js, FakeRenderer(), FakeStorage())(
            cast(JsMsg, FakeMsg(subject=f"cv.{JOB_ID}.structured", data=b"\x00\xffnot-a-proto-message"))
        )

    failed = _published_failure(js)
    assert failed.job_id == JOB_ID  # identity recovered from the subject, not the payload
    assert failed.stage == events_pb2.JOB_STAGE_RENDERING
    assert failed.error.startswith(INVALID_INPUT_ERROR)
    assert "DecodeError" in failed.error
    # PII discipline: the detail names the failure class, never the payload bytes.
    assert "\x00\xff" not in failed.error
    assert "not-a-proto" not in failed.error


async def test_invalid_link_url_is_terminal_invalid_input_with_field_detail() -> None:
    js = FakeJetStream()
    cv = _valid_cv()
    cv.personal_info.links.add(label="GitHub", url="notaurl")

    with pytest.raises(TerminalError):
        await _handler(js, FakeRenderer(), FakeStorage())(_structured_msg(cv))

    failed = _published_failure(js)
    assert failed.stage == events_pb2.JOB_STAGE_RENDERING
    assert failed.error.startswith(INVALID_INPUT_ERROR)
    assert "url" in failed.error  # field context surfaces; values never do
    assert "notaurl" not in failed.error


async def test_unspecified_proficiency_is_terminal_invalid_input() -> None:
    js = FakeJetStream()
    cv = _valid_cv()
    cv.languages.add(name="Ukrainian", proficiency=cv_pb2.LANGUAGE_PROFICIENCY_UNSPECIFIED)

    with pytest.raises(TerminalError):
        await _handler(js, FakeRenderer(), FakeStorage())(_structured_msg(cv))

    failed = _published_failure(js)
    assert failed.stage == events_pb2.JOB_STAGE_RENDERING
    assert failed.error.startswith(INVALID_INPUT_ERROR)
    assert "proficiency" in failed.error
