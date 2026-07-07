"""S3-compatible object storage via OpenDAL (LocalStack now, AWS S3 later).
OpenDAL defaults to path-style addressing, which LocalStack requires. The write
is wrapped in a manual OTel CLIENT span (OpenDAL has no OTel instrumentation)."""

import opendal
from opentelemetry import trace
from opentelemetry.trace import SpanKind

_tracer = trace.get_tracer("cv_generator.storage")


class Storage:
    def __init__(
        self, *, endpoint: str, region: str, bucket: str, access_key: str, secret_key: str
    ) -> None:
        self._op = opendal.AsyncOperator(
            "s3",
            bucket=bucket,
            region=region,
            endpoint=endpoint,
            access_key_id=access_key,
            secret_access_key=secret_key,
            # Use the supplied static creds; don't probe AWS config / EC2 IMDS.
            disable_config_load="true",
            disable_ec2_metadata="true",
        )

    async def put(self, key: str, data: bytes) -> None:
        with _tracer.start_as_current_span(
            "s3 write",
            kind=SpanKind.CLIENT,
            attributes={"opendal.scheme": "s3", "opendal.path": key, "opendal.size": len(data)},
        ):
            await self._op.write(key, data)
