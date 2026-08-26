"""build_model maps catalog entries to pydantic-ai models per provider."""

import pytest
from ai_processor.providers import UnsupportedProviderError, build_model, provider_label
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


def test_provider_label_maps_every_catalog_provider_to_a_lowercase_label() -> None:
    for provider, want in (
        (catalog_pb2.PROVIDER_ANTHROPIC, "anthropic"),
        (catalog_pb2.PROVIDER_OPENAI, "openai"),
        (catalog_pb2.PROVIDER_GOOGLE, "google"),
        (catalog_pb2.PROVIDER_OPENROUTER, "openrouter"),
        (catalog_pb2.PROVIDER_FAKE, "fake"),
    ):
        entry = catalog_pb2.ModelCatalogEntry(provider=provider)
        assert provider_label(entry) == want

    # Unknown enum values must stay low-cardinality and visible.
    assert provider_label(catalog_pb2.ModelCatalogEntry(provider=catalog_pb2.PROVIDER_UNSPECIFIED)) == "unknown"
