"""Informal text becomes a draft without invented facts."""

from __future__ import annotations

import pytest

from recipe_mcp.domain.models import RecipeStatus, SourceType
from recipe_mcp.domain.taxonomy import Facet
from recipe_mcp.services.container import AppContext
from recipe_mcp.services.ingestion import IngestionError

TUNA = "Tuna salad with tomato, quinoa, cucumber, arugula and seeds. Need to season the tuna."


def test_tuna_salad_draft(ctx: AppContext) -> None:
    result = ctx.ingestion.save("Save this: " + TUNA)
    r = result.recipe
    assert result.created
    assert r.source_type == SourceType.PERSONAL
    assert r.status == RecipeStatus.DRAFT
    assert r.total_minutes is None
    assert sorted(i.canonical_name for i in r.ingredients) == sorted(
        ["tuna", "tomato", "quinoa", "cucumber", "arugula", "seeds"]
    )
    assert r.notes == ["Need to season the tuna"]
    diets = r.facet_values(Facet.DIETARY)
    assert "pescatarian" in diets and "vegetarian" not in diets
    assert r.facet_values(Facet.DISH_TYPE) == ["salad"]
    assert "tuna" in r.facet_values(Facet.PRIMARY_INGREDIENT)
    assert "light" in r.facet_values(Facet.CHARACTER)
    blob = " ".join([r.title, *r.notes, *(i.raw_text for i in r.ingredients)]).lower()
    for invented in ("salt", "olive oil", "lemon", "minutes"):
        assert invented not in blob


def test_duplicate_personal_recipe_detected(ctx: AppContext) -> None:
    first = ctx.ingestion.save(TUNA)
    second = ctx.ingestion.save(TUNA)
    assert first.created and not second.created
    assert second.recipe.id == first.recipe.id
    assert ctx.recipes.count(ctx.household_id) == 1


def test_unsupported_url_becomes_stub_and_empty_text_fails(ctx: AppContext) -> None:
    stub = ctx.ingestion.save("https://example.com/recipe")
    assert stub.created and not stub.recipe.is_recommendable
    assert stub.recipe.source_type == SourceType.OTHER
    assert stub.recipe.title == "Knife Skills 101"
    assert "link" in stub.confirmation()
    assert not ctx.ingestion.save("https://example.com/recipe").created
    with pytest.raises(IngestionError):
        ctx.ingestion.save("Dinner.")
