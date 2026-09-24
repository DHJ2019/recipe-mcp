from __future__ import annotations

from recipe_mcp.domain.ingredients import normalize_ingredients
from recipe_mcp.domain.models import Recipe, SourceType
from recipe_mcp.domain.taxonomy import Facet
from recipe_mcp.providers.base import (
    ModelResponse,
    RecipeClassification,
    RecipeClassificationInput,
)
from recipe_mcp.providers.fake import FakeModelClient
from recipe_mcp.services.container import AppContext


def test_categorize_uncategorized_flags_low_confidence_and_keeps_corrections(
    ctx: AppContext,
) -> None:
    stored = ctx.recipes.create(
        Recipe(
            household_id=ctx.household_id,
            source_type=SourceType.OTHER,
            title="Mystery Bowl",
            ingredients=normalize_ingredients(["tofu", "rice", "unknown root"]),
        )
    )
    assert stored.id is not None
    assert len(ctx.recipes.list_uncategorized(ctx.household_id)) == 1
    outcomes = ctx.categorization.categorize_uncategorized(ctx.household_id)
    assert len(outcomes) == 1
    assert outcomes[0].needs_review  # no cuisine or dish hint -> below 0.8 threshold
    assert outcomes[0].recipe.facet_needs_review(Facet.CUISINE)
    assert ctx.recipes.list_uncategorized(ctx.household_id) == []

    corrected = ctx.corrections.correct(stored.id, facet_corrections={"cuisine": ["Korean"]})
    assert corrected.recipe.facet_values(Facet.CUISINE) == ["korean"]
    assert corrected.changes == ["cuisine -> korean"]
    # Re-running categorization keeps the user's answer.
    ctx.categorization.categorize(corrected.recipe)
    latest = ctx.recipes.get(stored.id)
    assert latest is not None and latest.facet_values(Facet.CUISINE) == ["korean"]
    assert not latest.facet_needs_review(Facet.CUISINE)
    assert latest.facet_needs_review(Facet.HEALTH)
    assert "review: " in ctx.categorization.report(ctx.household_id)


def test_threshold_is_configurable(ctx: AppContext) -> None:
    ctx.categorization.threshold = 0.3
    stored = ctx.recipes.create(
        Recipe(
            household_id=ctx.household_id,
            source_type=SourceType.OTHER,
            title="Mystery Bowl",
            ingredients=normalize_ingredients(["tofu", "rice"]),
        )
    )
    outcome = ctx.categorization.categorize(stored)
    assert not outcome.needs_review


def test_dietary_contradictions_are_rejected(ctx: AppContext) -> None:
    class LyingModel(FakeModelClient):
        def classify_recipe(
            self, recipe: RecipeClassificationInput
        ) -> ModelResponse[RecipeClassification]:
            response = super().classify_recipe(recipe)
            response.output = RecipeClassification(
                dietary_suitability=["vegan"],
                cuisine="thai",
                dish_type="soup",
                primary_ingredients=["chicken", "unicorn"],
                confidence=0.9,
            )
            return response

    ctx._model_override = LyingModel()
    recipe = ctx.recipes.create(
        Recipe(
            household_id=ctx.household_id,
            source_type=SourceType.OTHER,
            title="Chicken Soup",
            ingredients=normalize_ingredients(["chicken", "stock"]),
        )
    )
    outcome = ctx.categorization.categorize(recipe)
    assert outcome.recipe.facet_values(Facet.DIETARY) == ["omnivore"]
    assert outcome.recipe.facet_values(Facet.PRIMARY_INGREDIENT) == ["chicken"]
    assert any("rejected dietary" in w for w in outcome.warnings)
    assert any("unicorn" in w for w in outcome.warnings)
