"""Drain semantics of run_pull_loop: clean stop_event exit, in-flight completion, bounded cancel of stuck handlers."""

import asyncio
import inspect
from typing import Any, cast

import pytest
from cv_shared.consumer import run_pull_loop
from natsio.jetstream import Consumer

JOB_ID = "7a1e5d70-9c2b-4f4e-8a3d-2b1c0d9e8f7a"


class FakeMsg:
    def __init__(self, subject: str) -> None:
        self.subject = subject
        self.headers: dict[str, str] | None = None
        self.data = b""
        self.acked = False
        self.termed = False
        self.naks: list[float | None] = []

    async def ack(self) -> None:
        self.acked = True

    async def term(self, reason: str | None = None) -> None:
        self.termed = True
        self.term_reason = reason

    async def nak(self, delay: float | None = None) -> None:
        self.naks.append(delay)

    async def in_progress(self) -> None:
        pass


class DrainFakeConsumer:
    """Serves its queue, then parks inside fetch until stop_event fires.

    An empty queue never raises CancelledError (unlike the otel-suite fake):
    a drain must be observable as a plain return, so the loop needs its own
    stop check instead of relying on task cancellation.
    """

    def __init__(self, msgs: list[FakeMsg], stop_event: asyncio.Event) -> None:
        self._msgs = list(msgs)
        self._stop = stop_event
        self.fetch_calls = 0

    async def fetch(self, max_messages: int, timeout: float) -> list[FakeMsg]:  # noqa: ASYNC109 - mirrors natsio fetch()
        self.fetch_calls += 1
        if self._msgs:
            return [self._msgs.pop(0)]
        await self._stop.wait()
        await asyncio.sleep(0.01)  # keep the pre-drain fallback from spinning hot
        return []


def _drain_kwargs(stop_event: asyncio.Event) -> dict[str, Any]:
    """Forward stop_event only when run_pull_loop accepts it.

    Keeps RED-phase failures behavioural (a loop that ignores the drain
    signal misses assertions) instead of a bare TypeError about a keyword
    that does not exist yet.
    """
    if "stop_event" in inspect.signature(run_pull_loop).parameters:
        return {"stop_event": stop_event}
    return {}


async def _wait_bounded(task: asyncio.Task[None], budget_s: float) -> bool:
    done, _ = await asyncio.wait({task}, timeout=budget_s)
    return task in done


async def test_stop_before_fetch_exits_cleanly() -> None:
    stop = asyncio.Event()
    stop.set()
    msg = FakeMsg(f"cv.{JOB_ID}.requested")
    consumer = DrainFakeConsumer([msg], stop)

    async def handler(_msg: Any) -> None:
        raise AssertionError("handler must not run after stop")

    task = asyncio.create_task(
        run_pull_loop(cast(Consumer, consumer), handler, service="test-service", **_drain_kwargs(stop))
    )
    assert await _wait_bounded(task, budget_s=2.0), "loop ignored stop_event set before fetch"
    task.result()  # exited cleanly, no exception
    assert consumer.fetch_calls == 0
    assert not msg.acked


async def test_stop_during_handler_completes_and_acks() -> None:
    stop = asyncio.Event()
    msg = FakeMsg(f"cv.{JOB_ID}.requested")
    consumer = DrainFakeConsumer([msg], stop)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def handler(_msg: Any) -> None:
        entered.set()
        await release.wait()

    task = asyncio.create_task(
        run_pull_loop(cast(Consumer, consumer), handler, service="test-service", **_drain_kwargs(stop))
    )
    await entered.wait()  # fetch dispatched the message into the handler
    stop.set()  # SIGTERM lands mid-handler
    release.set()

    assert await _wait_bounded(task, budget_s=2.0), "loop kept fetching after the drained message finished"
    task.result()
    assert msg.acked
    assert consumer.fetch_calls == 1  # no further fetch attempt after drain


async def test_drain_timeout_cancels_stuck_handler() -> None:
    stop = asyncio.Event()
    msg = FakeMsg(f"cv.{JOB_ID}.requested")
    consumer = DrainFakeConsumer([msg], stop)
    entered = asyncio.Event()

    async def handler(_msg: Any) -> None:
        entered.set()
        await asyncio.sleep(30)  # far beyond any drain budget

    task = asyncio.create_task(
        run_pull_loop(cast(Consumer, consumer), handler, service="test-service", **_drain_kwargs(stop))
    )
    await entered.wait()
    stop.set()  # the loop cannot act on this until the handler returns
    finished = await _wait_bounded(task, budget_s=0.2)  # bounded join; drain_timeout_s stand-in
    assert not finished, "stuck handler should outlive the drain budget"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not msg.acked  # documented residual: redelivery replays this job
