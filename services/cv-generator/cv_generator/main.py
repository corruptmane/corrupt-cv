"""CV Generator entrypoint: consume cv.*.structured -> Typst PDF -> S3 ->
cv.*.completed."""

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

from .render import render_pdf
from .settings import Settings
from .storage import Storage

log = structlog.get_logger("cv_generator")


async def main() -> None:
    settings = Settings()
    configure_logging(settings.otel_service_name, settings.log_level)
    setup_telemetry()

    storage = Storage(
        endpoint=settings.s3_endpoint,
        region=settings.s3_region,
        bucket=settings.s3_bucket,
        access_key=settings.s3_access_key_id,
        secret_key=settings.s3_secret_access_key,
    )
    bus = await Bus.connect(settings.nats_url, settings.nats_stream)
    start_ops_server(settings.health_addr, readiness=bus.is_ready)

    async def handle(msg: Msg) -> None:
        event = g.CVStructured()
        event.ParseFromString(msg.data)
        job_id = event.job_id
        try:
            cv_dict = mapping.proto_to_dict(event.cv)
            pdf = await asyncio.to_thread(render_pdf, cv_dict)  # typst is CPU-bound
            key = f"pdfs/{job_id}.pdf"
            await storage.put(key, pdf)
            done = g.CVCompleted(job_id=job_id, object_key=key, size_bytes=len(pdf))
            await bus.publish(f"cv.{job_id}.completed", done.SerializeToString(), inject_headers())
            log.info("rendered", job_id=job_id, bytes=len(pdf))
        except Exception as exc:  # noqa: BLE001 - report as a failure event, ack the msg
            log.exception("render stage failed", job_id=job_id)
            failed = g.CVFailed(job_id=job_id, stage=g.STAGE_RENDER, message=str(exc)[:500])
            await bus.publish(f"cv.{job_id}.failed", failed.SerializeToString(), inject_headers())

    consumer = asyncio.create_task(bus.run_consumer("cv-generator", "cv.*.structured", handle))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    log.info("cv-generator ready")
    await stop.wait()

    consumer.cancel()
    try:
        await consumer
    except asyncio.CancelledError:
        pass
    await bus.close()


if __name__ == "__main__":
    asyncio.run(main())
