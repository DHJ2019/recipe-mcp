"""The single ``ModelClient`` interface and its strict structured-output schemas."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field


class ProposedValue(BaseModel):
    facet: str
    value: str


class FacetConfidence(BaseModel):
    """Per-facet confidence in [0, 1]; fixed keys so strict structured output works."""

    cuisine: float = Field(ge=0.0, le=1.0, default=0.5)
    dish_type: float = Field(ge=0.0, le=1.0, default=0.5)
    meal: float = Field(ge=0.0, le=1.0, default=0.5)
    primary_ingredient: float = Field(ge=0.0, le=1.0, default=0.5)
    effort: float = Field(ge=0.0, le=1.0, default=0.5)
    character: float = Field(ge=0.0, le=1.0, default=0.5)
    cooking_method: float = Field(ge=0.0, le=1.0, default=0.5)
    health_orientation: float = Field(ge=0.0, le=1.0, default=0.5)

    def for_facet(self, facet_name: str) -> float:
        return float(getattr(self, facet_name, 0.5))


class RecipeClassification(BaseModel):
    """Model proposal for a recipe's facets. Deterministic rules validate it afterwards."""

    dietary_suitability: list[str] = Field(default_factory=list)
    cuisine: str = "other"
    dish_type: str = "other"
    meal: list[str] = Field(default_factory=list)
    primary_ingredients: list[str] = Field(default_factory=list)
    effort: str | None = None
    character: list[str] = Field(default_factory=list)
    cooking_method: str | None = None
    health_orientation: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    facet_confidence: FacetConfidence = Field(default_factory=FacetConfidence)
    proposed_values: list[ProposedValue] = Field(default_factory=list)


class PersonalRecipeDraft(BaseModel):
    """Structured draft from informal text. Missing facts stay missing."""

    title: str
    ingredients: list[str] = Field(default_factory=list)
    servings: str | None = None
    total_minutes: int | None = None
    notes: list[str] = Field(default_factory=list)


class QueryConstraints(BaseModel):
    """Typed constraints extracted from a natural-language recommendation request."""

    dietary: list[str] = Field(default_factory=list)
    cuisine: str | None = None
    dish_type: str | None = None
    main_ingredient: str | None = None
    character: list[str] = Field(default_factory=list)
    max_minutes: int | None = None
    available_ingredients: list[str] = Field(default_factory=list)
    excluded_ingredients: list[str] = Field(default_factory=list)
    max_missing: int | None = None
    for_household: bool = False
    exclude_recent: bool = False


class ImageIngredient(BaseModel):
    name: str
    confidence: float = Field(ge=0.0, le=1.0)


class ImageIngredients(BaseModel):
    items: list[ImageIngredient] = Field(default_factory=list)


class RecipeClassificationInput(BaseModel):
    title: str
    ingredients: list[str]
    total_minutes: int | None = None
    source_cuisine: str | None = None
    source_category: str | None = None
    notes: list[str] = Field(default_factory=list)

    def input_hash(self) -> str:
        payload = json.dumps(self.model_dump(), sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def text_hash(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()[:32]


@dataclass
class ModelResponse[T: BaseModel]:
    output: T
    provider: str
    model: str
    prompt_version: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached: bool = False


class ModelClient(Protocol):
    """Every semantic task the application delegates to a model."""

    provider: str
    model: str

    def classify_recipe(
        self, recipe: RecipeClassificationInput
    ) -> ModelResponse[RecipeClassification]: ...

    def parse_personal_recipe(self, text: str) -> ModelResponse[PersonalRecipeDraft]: ...

    def interpret_query(self, text: str) -> ModelResponse[QueryConstraints]: ...

    def extract_image_ingredients(
        self, image_bytes: bytes, mime_type: str
    ) -> ModelResponse[ImageIngredients]: ...
