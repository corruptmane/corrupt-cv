"""build_model maps catalog entries to pydantic-ai models per provider."""

import pytest
from ai_processor.providers import UnsupportedProviderError, build_model
from cvgen.catalog.v1 import catalog_pb2
from pydantic_ai.models.openrouter import OpenRouterModel


def test_build_model_returns_openrouter_model_for_openrouter_provider() -> None:
    entry = catalog_pb2.ModelCatalogEntry(
        key="openrouter/glm-5.3",
        provider=catalog_pb2.PROVIDER_OPENROUTER,
        model_id="z-ai/glm-5.3",
    )

    result = build_model(entry, "test-api-key")

    assert isinstance(result, OpenRouterModel)


def test_build_model_raises_unsupported_provider_error_for_unspecified_provider() -> None:
    entry = catalog_pb2.ModelCatalogEntry(key="unknown/model", provider=catalog_pb2.PROVIDER_UNSPECIFIED)

    with pytest.raises(UnsupportedProviderError):
        build_model(entry, "test-api-key")
