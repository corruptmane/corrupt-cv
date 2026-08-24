"""Service entrypoint: bind to JetStream and consume cv.*.structured until signalled."""

import asyncio
import contextlib
import signal

import structlog
from cv_shared.consumer import run_pull_loop
from cv_shared.health import HealthServer
from cv_shared.logging import setup_logging
from cv_shared.natsx import DURABLE_CV_GENERATOR, bind_pull_consumer, connect
from cv_shared.otel import setup_otel, shutdown

from cv_generator.handler import JobHandler
from cv_generator.renderer import Renderer
from cv_generator.settings import CvGeneratorSettings
from cv_generator.storage import Storage

SERVICE = "cv-generator"

log = structlog.get_logger("cv_generator.main")


async def _run() -> None:
    settings = CvGeneratorSettings()
    setup_logging(settings.log_level)
    setup_otel(SERVICE)

    ready = False
    health = HealthServer(settings.ops_port, ready_check=lambda: ready)
    health.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    renderer = Renderer(settings.typst_template_path)
    storage = Storage(settings)

    nc = await connect(settings.nats_url, name=SERVICE)
    try:
        js = nc.jetstream()
        consumer = await bind_pull_consumer(js, DURABLE_CV_GENERATOR)
        ready = True
        log.info("service ready", nats_url=settings.nats_url, ops_port=settings.ops_port)

        handler = JobHandler(js=js, renderer=renderer, storage=storage)
        consume = asyncio.create_task(
            run_pull_loop(consumer, handler, service=SERVICE, stop_event=stop, heartbeat_s=30)
        )
        stop_wait = asyncio.create_task(stop.wait())
        try:
            done, _ = await asyncio.wait({consume, stop_wait}, return_when=asyncio.FIRST_COMPLETED)
            if consume in done:
                consume.result()  # surface an unexpected consumer-loop crash
        finally:
            stop_wait.cancel()
            if stop.is_set():
                # Graceful drain: give the in-flight message time to finish
                # (ack/term/nak) instead of cancelling mid-handler, which
                # abandons GETDEL-consumed work to redelivery.
                done2, _ = await asyncio.wait({consume}, timeout=settings.drain_timeout_s)
                if consume in done2:
                    consume.result()  # surface an unexpected consumer-loop crash
                else:
                    log.warning(
                        "drain timeout exceeded, cancelling mid-handler",
                        drain_timeout_s=settings.drain_timeout_s,
                    )
                    consume.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await consume
            else:
                consume.cancel()
    finally:
        ready = False
        log.info("shutting down")
        health.stop()
        await nc.drain()
        # Flush OTel batch processors last so final spans/logs are exported;
        # telemetry teardown must never mask the exit path above.
        try:
            shutdown()
        except Exception:
            log.exception("otel shutdown failed")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
