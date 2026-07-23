"""Environment configuration for the cv-generator service."""

from pathlib import Path

from cv_shared.settings import BaseServiceSettings

_DEFAULT_TEMPLATE = Path(__file__).resolve().parent.parent.parent / "assets" / "cv.typ"


class CvGeneratorSettings(BaseServiceSettings):
    s3_endpoint: str = "http://localhost:8080"
    s3_region: str = "us-east-1"
    s3_bucket: str = "cv"
    s3_access_key_id: str = "dev"
    s3_secret_access_key: str = "dev"
    # Path-style for S3-compatible backends (Swift s3api in dev);
    # real AWS uses virtual-host style.
    s3_use_path_style: bool = True
    typst_template_path: Path = _DEFAULT_TEMPLATE
