"""Caching and run-recording wrapper around any :class:`ModelClient`.

Outputs are cached by (task, input hash, prompt version, model). Every call,
cached or not, is recorded in ``model_runs`` with latency, tokens and validation
status so Phase 2 model comparisons have data to work from.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ValidationError

from recipe_mcp.db.repositories import ModelRunRepository
from recipe_mcp.domain.models import ModelRun
from recipe_mcp.providers import prompts
from recipe_mcp.providers.base import (
    ImageIngredients,
    ModelClient,
    ModelResponse,
    PersonalRecipeDraft,
    QueryConstraints,
    RecipeClassification,
    RecipeClassificationInput,
    text_hash,
)


class CachingModelClient:
    def __init__(self, inner: ModelClient, runs: ModelRunRepository) -> None:
        self.inner = inner
        self.runs = runs
        self.provider = inner.provider
        self.model = inner.model

    def _cached[T: BaseModel](
        self,
        prompt: prompts.Prompt,
        input_hash: str,
        schema: type[T],
        call: Callable[[], ModelResponse[T]],
    ) -> ModelResponse[T]:
        cached_json = self.runs.cache_get(prompt.name, input_hash, prompt.version, self.model)
        if cached_json is not None:
            try:
                output = schema.model_validate_json(cached_json)
            except ValidationError:
                output = None
            if output is not None:
                self._record(prompt, input_hash, 0, None, None, "cached")
                return ModelResponse(
                    output=output,
                    provider=self.provider,
                    model=self.model,
                    prompt_version=prompt.version,
                    latency_ms=0,
                    cached=True,
                )
        try:
            response = call()
        except ValidationError:
            self._record(prompt, input_hash, 0, None, None, "validation_failed")
            raise
        self.runs.cache_put(
            prompt.name, input_hash, prompt.version, self.model, response.output.model_dump_json()
        )
        self._record(
            prompt,
            input_hash,
            response.latency_ms,
            response.input_tokens,
            response.output_tokens,
            "ok",
        )
        return response

    def _record(
        self,
        prompt: prompts.Prompt,
        input_hash: str,
        latency_ms: int,
        input_tokens: int | None,
        output_tokens: int | None,
        status: str,
    ) -> None:
        self.runs.record(
            ModelRun(
                task=prompt.name,
                input_hash=input_hash,
                provider=self.provider,
                model=self.model,
                prompt_version=prompt.version,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                validation_status=status,
            )
        )

    def classify_recipe(
        self, recipe: RecipeClassificationInput
    ) -> ModelResponse[RecipeClassification]:
        return self._cached(
            prompts.CLASSIFY_RECIPE,
            recipe.input_hash(),
            RecipeClassification,
            lambda: self.inner.classify_recipe(recipe),
        )

    def parse_personal_recipe(self, text: str) -> ModelResponse[PersonalRecipeDraft]:
        return self._cached(
            prompts.PARSE_PERSONAL_RECIPE,
            text_hash(text),
            PersonalRecipeDraft,
            lambda: self.inner.parse_personal_recipe(text),
        )

    def interpret_query(self, text: str) -> ModelResponse[QueryConstraints]:
        return self._cached(
            prompts.INTERPRET_QUERY,
            text_hash(text),
            QueryConstraints,
            lambda: self.inner.interpret_query(text),
        )

    def extract_image_ingredients(
        self, image_bytes: bytes, mime_type: str
    ) -> ModelResponse[ImageIngredients]:
        # Images are deleted after processing; never cache them.
        response = self.inner.extract_image_ingredients(image_bytes, mime_type)
        self._record(
            prompts.EXTRACT_IMAGE_INGREDIENTS,
            text_hash(str(len(image_bytes))),
            response.latency_ms,
            response.input_tokens,
            response.output_tokens,
            "ok",
        )
        return response
