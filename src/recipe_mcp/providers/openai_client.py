"""OpenAI implementation of :class:`ModelClient` using strict structured outputs."""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from pydantic import BaseModel

from recipe_mcp.providers import prompts
from recipe_mcp.providers.base import (
    ImageIngredients,
    ModelResponse,
    PersonalRecipeDraft,
    QueryConstraints,
    RecipeClassification,
    RecipeClassificationInput,
)


class OpenAIModelClient:
    provider = "openai"

    def __init__(self, api_key: str, model: str, timeout: float = 60.0) -> None:
        from openai import OpenAI  # imported lazily so offline paths never need it

        self.model = model
        self._client = OpenAI(api_key=api_key, timeout=timeout)

    def _parse[T: BaseModel](
        self, prompt: prompts.Prompt, user_content: Any, schema: type[T]
    ) -> ModelResponse[T]:
        start = time.perf_counter()
        completion = self._client.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": user_content},
            ],
            response_format=schema,
            temperature=0,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise RuntimeError(f"{prompt.name}: model returned no parsable output")
        usage = completion.usage
        return ModelResponse(
            output=parsed,
            provider=self.provider,
            model=self.model,
            prompt_version=prompt.version,
            latency_ms=int((time.perf_counter() - start) * 1000),
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
        )

    def classify_recipe(
        self, recipe: RecipeClassificationInput
    ) -> ModelResponse[RecipeClassification]:
        payload = json.dumps(recipe.model_dump(), indent=2)
        return self._parse(prompts.CLASSIFY_RECIPE, payload, RecipeClassification)

    def parse_personal_recipe(self, text: str) -> ModelResponse[PersonalRecipeDraft]:
        return self._parse(prompts.PARSE_PERSONAL_RECIPE, text, PersonalRecipeDraft)

    def interpret_query(self, text: str) -> ModelResponse[QueryConstraints]:
        return self._parse(prompts.INTERPRET_QUERY, text, QueryConstraints)

    def extract_image_ingredients(
        self, image_bytes: bytes, mime_type: str
    ) -> ModelResponse[ImageIngredients]:
        data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        content = [
            {"type": "text", "text": "Which ingredients are visible?"},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
        return self._parse(prompts.EXTRACT_IMAGE_INGREDIENTS, content, ImageIngredients)
