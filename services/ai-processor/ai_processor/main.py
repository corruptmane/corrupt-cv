"""AI Processor entrypoint: consume cv.*.requested -> AI -> cv.*.structured."""

import asyncio
import signal

import structlog
from cv.v1 import generation_pb2 as g
from cv_worker import mapping
from cv_worker.bus import Bus
from cv_worker.log import configure_logging
from cv_worker.ops import start_ops_server
from cv_worker.telemetry import inject_headers, setup_telemetry
from nats.aio.msg import Msg

from .agent import generate_cv
from .secrets import SecretStore
from .settings import Settings

log = structlog.get_logger("ai_processor")


async def main() -> None:
    settings = Settings()
    configure_logging(settings.otel_service_name, settings.log_level)
    setup_telemetry()

    secrets = SecretStore(settings.valkey_url)
    bus = await Bus.connect(settings.nats_url, settings.nats_stream)
    start_ops_server(settings.health_addr, readiness=bus.is_ready)

    async def handle(msg: Msg) -> None:
        req = g.GenerationRequest()
        req.ParseFromString(msg.data)
        job_id = req.job_id
        api_key = await secrets.take(job_id)
        try:
            content = await generate_cv(req, api_key or "", settings.ollama_base_url)
            # Assemble the wire CV: AI content + authoritative form contacts.
            event = g.CVStructured(
                job_id=job_id,
                cv=mapping.content_to_proto(content, req.contacts),
                provider=req.provider,
                model=req.model,
            )
            await bus.publish(
                f"cv.{job_id}.structured", event.SerializeToString(), inject_headers()
            )
            log.info("structured", job_id=job_id)
        except Exception as exc:  # noqa: BLE001 - report as a failure event, ack the msg
            log.exception("ai stage failed", job_id=job_id)
            failed = g.CVFailed(job_id=job_id, stage=g.STAGE_AI, message=str(exc)[:500])
            await bus.publish(f"cv.{job_id}.failed", failed.SerializeToString(), inject_headers())

    consumer = asyncio.create_task(bus.run_consumer("ai-processor", "cv.*.requested", handle))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    log.info("ai-processor ready")
    await stop.wait()

    consumer.cancel()
    try:
        await consumer
    except asyncio.CancelledError:
        pass
    await bus.close()
    await secrets.close()


if __name__ == "__main__":
    asyncio.run(main())
