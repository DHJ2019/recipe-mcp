"""Re-running dietary rules over recipes stored by an older ingredient parser."""

from __future__ import annotations

from recipe_mcp.domain.models import (
    Classification,
    FacetSource,
    IngredientFlags,
    Recipe,
    RecipeIngredient,
    SourceType,
)
from recipe_mcp.domain.taxonomy import Facet
from recipe_mcp.services.container import AppContext


def _stale_recipe(ctx: AppContext) -> Recipe:
    """What the old parser stored for a chicken recipe: protein lost, tagged vegan."""
    recipe = Recipe(
        household_id=ctx.household_id,
        source_type=SourceType.NYT,
        title="Sheet-Pan Chicken With Labneh",
        ingredients=[
            RecipeIngredient(
                canonical_name="bone-in",
                raw_text="2 pounds bone-in, skin-on chicken thighs",
                preparation="skin-on chicken thighs",
            ),
            # Stored before labneh was in the dairy lexicon: the row has no dairy flag.
            RecipeIngredient(canonical_name="labneh", raw_text="8 ounces labneh"),
            RecipeIngredient(
                canonical_name="zucchini", raw_text="2 zucchini", category="vegetable"
            ),
        ],
        classifications=[
            *(
                Classification(facet=Facet.DIETARY, value=d, source=FacetSource.RULE)
                for d in ("vegan", "vegetarian", "pescatarian", "omnivore")
            ),
            Classification(
                facet=Facet.CUISINE,
                value="middle_eastern",
                source=FacetSource.MODEL,
                confidence=0.9,
            ),
            Classification(
                facet=Facet.PRIMARY_INGREDIENT,
                value="bone-in",
                source=FacetSource.MODEL,
                confidence=0.9,
            ),
            Classification(
                facet=Facet.CHARACTER,
                value="comforting",
                source=FacetSource.USER,
                user_confirmed=True,
            ),
        ],
    )
    return ctx.recipes.create(recipe)


def test_dry_run_reports_without_writing(ctx: AppContext) -> None:
    stored = _stale_recipe(ctx)
    assert stored.id is not None
    changes = ctx.categorization.refresh_dietary(ctx.household_id, apply=False)
    [change] = [c for c in changes if c.recipe_id == stored.id]
    assert change.before == ["vegan", "vegetarian", "pescatarian", "omnivore"]
    assert change.after == ["omnivore"]
    assert "bone-in" in change.removed and "chicken" in change.added

    unchanged = ctx.recipes.get(stored.id)
    assert unchanged is not None
    assert "vegan" in unchanged.facet_values(Facet.DIETARY)
    assert unchanged.ingredients[0].canonical_name == "bone-in"


def test_apply_rewrites_only_ingredients_and_dietary(ctx: AppContext) -> None:
    stored = _stale_recipe(ctx)
    assert stored.id is not None
    ctx.categorization.refresh_dietary(ctx.household_id, apply=True)

    refreshed = ctx.recipes.get(stored.id)
    assert refreshed is not None
    assert refreshed.facet_values(Facet.DIETARY) == ["omnivore"]
    assert [i.canonical_name for i in refreshed.ingredients] == ["chicken", "labneh", "zucchini"]
    # The shared ingredient row picked up the new lexicon, not only this recipe.
    assert refreshed.ingredients[1].flags == IngredientFlags(contains_dairy=True)
    # Model, agent and user classifications for other facets are untouched.
    assert refreshed.facet_values(Facet.CUISINE) == ["middle_eastern"]
    assert refreshed.facet_values(Facet.PRIMARY_INGREDIENT) == ["bone-in"]
    assert refreshed.facet_values(Facet.CHARACTER) == ["comforting"]

    # A second run finds nothing left to change.
    again = ctx.categorization.refresh_dietary(ctx.household_id, apply=True)
    assert [c for c in again if c.recipe_id == stored.id] == []
