"""Map a ModelCatalogEntry to a pydantic-ai model carrying a per-request API key.

Keys are handed off out-of-band via Valkey and live only for the duration of
one processing attempt, so every request builds a fresh model + provider pair
instead of reusing a process-wide client.
"""

from cvgen.catalog.v1 import catalog_pb2
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider

from ai_processor.fake import build_fake_model


class UnsupportedProviderError(Exception):
    """Catalog entry names a provider this service cannot build a model for."""


def build_model(entry: catalog_pb2.ModelCatalogEntry, api_key: str | None) -> Model:
    if entry.provider == catalog_pb2.PROVIDER_FAKE:
        return build_fake_model()
    if api_key is None:
        raise ValueError(f"api_key is required for catalog entry {entry.key!r}")
    match entry.provider:
        case catalog_pb2.PROVIDER_ANTHROPIC:
            return AnthropicModel(entry.model_id, provider=AnthropicProvider(api_key=api_key))
        case catalog_pb2.PROVIDER_OPENAI:
            return OpenAIChatModel(entry.model_id, provider=OpenAIProvider(api_key=api_key))
        case catalog_pb2.PROVIDER_GOOGLE:
            return GoogleModel(entry.model_id, provider=GoogleProvider(api_key=api_key))
        case _:
            raise UnsupportedProviderError(f"unsupported provider {entry.provider} for key {entry.key!r}")
