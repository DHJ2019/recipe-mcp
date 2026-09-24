"""Build the configured model client (optional: the agent brain needs none)."""

from __future__ import annotations

from recipe_mcp.providers.base import ModelClient
from recipe_mcp.settings import Settings


def build_model_client(settings: Settings) -> ModelClient:
    if settings.model_provider == "fake":
        from recipe_mcp.providers.fake import FakeModelClient

        return FakeModelClient()
    settings.require("model")
    assert settings.openai_api_key is not None
    from recipe_mcp.providers.openai_client import OpenAIModelClient

    return OpenAIModelClient(
        api_key=settings.openai_api_key.get_secret_value(), model=settings.effective_model_name
    )
