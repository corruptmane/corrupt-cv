"""Handler unit tests with fake js/renderer/storage objects (no network)."""

from dataclasses import dataclass
from typing import cast

import pytest
import typst
from cv_generator.handler import RENDER_ERROR, JobHandler
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
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes, dict[str, str] | None, str | None]] = []

    async def publish(
        self,
        subject: str,
        payload: bytes,
        *,
        headers: dict[str, str] | None = None,
        msg_id: str | None = None,
    ) -> None:
        self.published.append((subject, payload, headers, msg_id))


class FakeRenderer:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.rendered: list[str] = []

    def render(self, cv_json: str) -> bytes:
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


def _structured_msg() -> JsMsg:
    structured = events_pb2.JobStructured(
        job_id=JOB_ID,
        cv=cv_pb2.CV(
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
        ),
    )
    structured.occurred_at.GetCurrentTime()
    return cast(JsMsg, FakeMsg(subject=f"cv.{JOB_ID}.structured", data=structured.SerializeToString()))


def _handler(js: FakeJetStream, renderer: FakeRenderer, storage: FakeStorage) -> JobHandler:
    return JobHandler(js=cast(JetStreamContext, js), renderer=renderer, storage=storage)


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
