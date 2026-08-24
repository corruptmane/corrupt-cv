"""Base settings shared by the Python services; extend per service."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    nats_url: str = "nats://localhost:4222"
    ops_port: int = 9090
    log_level: str = "INFO"
    # Graceful-shutdown budget: how long main() waits for the in-flight
    # message to finish before cancelling mid-handler.
    drain_timeout_s: float = 90.0
