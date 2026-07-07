"""Environment configuration for the ai-processor service."""

from cv_shared.settings import BaseServiceSettings


class AiProcessorSettings(BaseServiceSettings):
    valkey_url: str = "valkey://localhost:6379"
