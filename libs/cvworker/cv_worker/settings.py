"""Common worker settings. Services subclass to add their own fields."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    nats_url: str = "nats://127.0.0.1:4222"
    nats_stream: str = "CV"
    otel_service_name: str = "worker"
    log_level: str = "info"
    # host:port the liveness server binds to (":8081").
    health_addr: str = ":8080"
