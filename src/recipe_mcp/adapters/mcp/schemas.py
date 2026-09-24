"""Pydantic output schemas for MCP tool results (the contract clients rely on)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from recipe_mcp.domain import dietary
from recipe_mcp.domain.models import (
    FeedbackSummary,
    Recipe,
    RecommendationRequest,
    RecommendationResult,
)


class RecipeIngredientOut(BaseModel):
    name: str
    raw_text: str
    quantity: str | None = None
    preparation: str | None = None
    is_staple: bool = False
    food_types: list[str] = Field(default_factory=list)
    food_types_corrected: bool = False


class RecipeOut(BaseModel):
    recipe_id: int
    title: str
    status: str
    source_type: str
    source_url: str | None
    servings: str | None
    total_minutes: int | None
    notes: list[str]
    ingredients: list[RecipeIngredientOut]
    classifications: dict[str, list[str]]
    contains: list[str] = Field(default_factory=list)
    """Food types behind the dietary label: meat, fish, shellfish, dairy, egg."""
    can_be_made: dict[str, list[str]] = Field(default_factory=dict)
    """Stricter diets reachable through the recipe's own stated choices, with the swaps."""
    needs_review: list[str] = Field(default_factory=list)
    added_by: str | None = None
    added_at: str
    updated_at: str

    @classmethod
    def from_recipe(cls, recipe: Recipe, added_by: str | None = None) -> RecipeOut:
        from recipe_mcp.domain.taxonomy import Facet

        return cls(
            recipe_id=recipe.id or 0,
            title=recipe.title,
            status=recipe.status.value,
            source_type=recipe.source_type.value,
            source_url=recipe.canonical_source_url,
            servings=recipe.servings,
            total_minutes=recipe.total_minutes,
            notes=recipe.notes,
            ingredients=[
                RecipeIngredientOut(
                    name=i.canonical_name,
                    raw_text=i.raw_text,
                    quantity=i.quantity,
                    preparation=i.preparation,
                    is_staple=i.is_staple,
                    food_types=i.effective_flags.food_types(),
                    food_types_corrected=i.food_types_override is not None,
                )
                for i in recipe.ingredients
            ],
            classifications=recipe.classification_summary(),
            contains=recipe.flags.food_types(),
            can_be_made=dietary.can_be_made(recipe),
            needs_review=[f.value for f in Facet if recipe.facet_needs_review(f)],
            added_by=added_by,
            added_at=recipe.added_at,
            updated_at=recipe.updated_at,
        )


class SaveRecipeOut(BaseModel):
    created: bool
    confirmation: str
    recipe: RecipeOut
    warnings: list[str] = Field(default_factory=list)
    needs_review: bool = False
    needs_classification: bool = False
    """True when no cuisine/dish classification exists yet: the agent should propose one
    with correct_recipe(proposed_by_agent=true)."""


class RecommendRecipesOut(BaseModel):
    request: RecommendationRequest
    results: list[RecommendationResult]
    count: int


class GetRecipeOut(BaseModel):
    recipe: RecipeOut
    feedback: FeedbackSummary


class RateRecipeOut(BaseModel):
    recipe_id: int
    title: str
    recorded: str
    feedback: FeedbackSummary


class CorrectRecipeOut(BaseModel):
    recipe: RecipeOut
    changes: list[str]
