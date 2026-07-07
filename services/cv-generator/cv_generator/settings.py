from cv_worker.settings import WorkerSettings


class Settings(WorkerSettings):
    s3_endpoint: str = "http://127.0.0.1:4566"
    s3_region: str = "us-east-1"
    s3_bucket: str = "cv-pdfs"
    s3_access_key_id: str = "test"
    s3_secret_access_key: str = "test"
    s3_use_path_style: bool = True
