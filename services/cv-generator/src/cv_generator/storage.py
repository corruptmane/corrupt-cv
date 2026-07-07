"""Object storage for rendered PDFs (S3 API; Swift s3api needs path-style addressing)."""

import opendal

from cv_generator.settings import CvGeneratorSettings


def object_key(job_id: str) -> str:
    return f"cvs/{job_id}.pdf"


class Storage:
    def __init__(self, settings: CvGeneratorSettings) -> None:
        self._op = opendal.AsyncOperator(
            "s3",
            bucket=settings.s3_bucket,
            region=settings.s3_region,
            endpoint=settings.s3_endpoint,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            root="/",
            # opendal operator options are string-typed end to end; booleans
            # panic in the Rust layer.
            # Swift s3api serves buckets on the path, not on a subdomain.
            enable_virtual_host_style="false",
            # Never pick up ambient AWS config/credentials; the settings are authoritative.
            disable_config_load="true",
            disable_ec2_metadata="true",
        )

    async def put_pdf(self, key: str, data: bytes) -> None:
        await self._op.write(key, data, content_type="application/pdf")
