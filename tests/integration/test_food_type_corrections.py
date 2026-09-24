"""A person corrects an ingredient's food types for one recipe; diets follow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from recipe_mcp.domain.models import IngredientFlags, RecommendationRequest
from recipe_mcp.domain.taxonomy import Facet
from recipe_mcp.services.container import AppContext
from recipe_mcp.services.corrections import CorrectionError


def test_food_type_correction_overrides_one_recipe(ctx: AppContext, tmp_path: Path) -> None:
    ctx.corrections.private_evals_path = tmp_path / "evals"
    # Pretend the lexicon got an ingredient wrong: "stock" alone carries no food type, but
    # in this recipe the household knows it is chicken stock.
    soup = ctx.ingestion.save("Cabbage soup with stock, carrot and onion.").recipe
    other = ctx.ingestion.save("Lentil soup with stock and carrot.").recipe
    assert soup.id is not None and other.id is not None
    assert "vegan" in soup.facet_values(Facet.DIETARY)

    result = ctx.corrections.correct(
        soup.id, field_updates={"food_types": {"stock": ["meat"]}}, member_id=None
    )
    r = result.recipe
    assert r.facet_values(Facet.DIETARY) == ["omnivore"]
    stock = next(i for i in r.ingredients if i.canonical_name == "stock")
    assert stock.food_types_override == IngredientFlags(contains_meat=True)
    assert stock.flags == IngredientFlags()  # the shared lexicon default is untouched
    assert "stock contains -> meat" in result.changes

    # Other recipes using the same ingredient keep the lexicon's answer.
    untouched = ctx.recipes.get(other.id)
    assert untouched is not None and "vegan" in untouched.facet_values(Facet.DIETARY)

    # The correction survives a re-parse and is a regression case.
    ctx.categorization.refresh_dietary(ctx.household_id, apply=True)
    again = ctx.recipes.get(soup.id)
    assert again is not None and again.facet_values(Facet.DIETARY) == ["omnivore"]
    vegan = ctx.recommendation.recommend(RecommendationRequest(dietary=["vegan"]))
    assert soup.id not in [x.recipe_id for x in vegan]
    case = json.loads((tmp_path / "evals" / "corrections.jsonl").read_text().splitlines()[-1])
    assert case["expected"]["food_types"] == {"stock": ["meat"]}
    assert case["expected"]["contains"] == ["meat"]

    # Clearing the food types (e.g. "oyster mushroom is not shellfish") uses [].
    cleared = ctx.corrections.correct(soup.id, field_updates={"food_types": {"stock": []}})
    assert "vegan" in cleared.recipe.facet_values(Facet.DIETARY)


def test_food_type_correction_rejects_bad_input(ctx: AppContext) -> None:
    saved = ctx.ingestion.save("Cabbage soup with stock, carrot and onion.").recipe
    assert saved.id is not None
    with pytest.raises(CorrectionError, match="not in this recipe"):
        ctx.corrections.correct(saved.id, field_updates={"food_types": {"salmon": ["fish"]}})
    with pytest.raises(CorrectionError, match="unknown food type"):
        ctx.corrections.correct(saved.id, field_updates={"food_types": {"stock": ["pork"]}})
    with pytest.raises(CorrectionError):
        ctx.corrections.correct(saved.id, field_updates={"food_types": ["meat"]})
