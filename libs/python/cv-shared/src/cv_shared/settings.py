"""Base settings shared by the Python services; extend per service."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    nats_url: str = "nats://localhost:4222"
    ops_port: int = 9090
    log_level: str = "INFO"
