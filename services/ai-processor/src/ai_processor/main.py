"""Service entrypoint: bind to JetStream and consume cv.*.requested until signalled."""

import asyncio
import signal

import structlog
from cv_shared.consumer import run_pull_loop
from cv_shared.health import HealthServer
from cv_shared.logging import setup_logging
from cv_shared.natsx import DURABLE_AI_PROCESSOR, KV_MODEL_CATALOG, bind_kv, bind_pull_consumer, connect
from cv_shared.otel import setup_otel
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from valkey.asyncio import Valkey

from ai_processor.handler import JobHandler
from ai_processor.settings import AiProcessorSettings

SERVICE = "ai-processor"

log = structlog.get_logger("ai_processor.main")


async def _run() -> None:
    settings = AiProcessorSettings()
    setup_logging(settings.log_level)
    setup_otel(SERVICE)
    HTTPXClientInstrumentor().instrument()

    ready = False
    health = HealthServer(settings.ops_port, ready_check=lambda: ready)
    health.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    nc = await connect(settings.nats_url, name=SERVICE)
    valkey = Valkey.from_url(settings.valkey_url)
    try:
        js = nc.jetstream()
        psub = await bind_pull_consumer(js, DURABLE_AI_PROCESSOR)
        kv = await bind_kv(js, KV_MODEL_CATALOG)
        ready = True
        log.info("service ready", nats_url=settings.nats_url, ops_port=settings.ops_port)

        handler = JobHandler(js=js, kv=kv, valkey=valkey)
        consume = asyncio.create_task(run_pull_loop(psub, handler, service=SERVICE, heartbeat_s=30))
        stop_wait = asyncio.create_task(stop.wait())
        try:
            done, _ = await asyncio.wait({consume, stop_wait}, return_when=asyncio.FIRST_COMPLETED)
            if consume in done:
                consume.result()  # surface an unexpected consumer-loop crash
        finally:
            stop_wait.cancel()
            consume.cancel()
    finally:
        ready = False
        log.info("shutting down")
        health.stop()
        await valkey.aclose()
        await nc.drain()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
