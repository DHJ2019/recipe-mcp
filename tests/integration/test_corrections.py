"""Save, correct and re-query: corrections persist, override the model and become cases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from recipe_mcp.domain.models import RecipeStatus, RecommendationRequest
from recipe_mcp.domain.taxonomy import Facet
from recipe_mcp.services.container import AppContext
from recipe_mcp.services.corrections import CorrectionError

TUNA = "Tuna salad with tomato, quinoa, cucumber, arugula and seeds. Need to season the tuna."


def test_save_correct_requery(ctx: AppContext, tmp_path: Path) -> None:
    ctx.corrections.private_evals_path = tmp_path / "evals"
    saved = ctx.ingestion.save(TUNA).recipe
    assert saved.id is not None
    assert ctx.recommendation.recommend(RecommendationRequest(max_minutes=45)) == []

    result = ctx.corrections.correct(
        saved.id,
        field_updates={"total_minutes": 30, "notes": ["Season the tuna before assembling"]},
        facet_corrections={"cuisine": ["Mediterranean"], "character": ["light", "fresh"]},
        member_id=None,
    )
    r = result.recipe
    assert r.total_minutes == 30 and r.status == RecipeStatus.COMPLETE
    assert r.facet_values(Facet.EFFORT) == ["weeknight"]
    assert r.facet_values(Facet.CUISINE) == ["mediterranean"]
    assert r.facet_values(Facet.CHARACTER) == ["light", "fresh"]
    assert r.notes == ["Season the tuna before assembling"]

    recs = ctx.recommendation.recommend(
        RecommendationRequest(max_minutes=45, cuisine="mediterranean")
    )
    assert [x.recipe_id for x in recs] == [saved.id]

    # Model re-runs never overwrite the user's answer.
    ctx.categorization.categorize(r)
    latest = ctx.recipes.get(saved.id)
    assert latest is not None and latest.facet_values(Facet.CUISINE) == ["mediterranean"]

    cases = (tmp_path / "evals" / "corrections.jsonl").read_text().splitlines()
    assert len(cases) == 1
    case = json.loads(cases[0])
    assert case["recipe_id"] == saved.id
    assert case["expected"]["facets"]["cuisine"] == ["mediterranean"]
    assert case["expected"]["total_minutes"] == 30


def test_ingredient_corrections_rerun_dietary_rules(ctx: AppContext) -> None:
    saved = ctx.ingestion.save("Quinoa salad with tomato, cucumber and arugula.").recipe
    assert saved.id is not None
    assert "vegan" in saved.facet_values(Facet.DIETARY)
    result = ctx.corrections.correct(saved.id, field_updates={"add_ingredients": ["100 g feta"]})
    diets = result.recipe.facet_values(Facet.DIETARY)
    assert "vegan" not in diets and "vegetarian" in diets
    assert any("added ingredient feta" in c for c in result.changes)
    back = ctx.corrections.correct(saved.id, field_updates={"remove_ingredients": ["feta"]})
    assert "vegan" in back.recipe.facet_values(Facet.DIETARY)


def test_invalid_corrections(ctx: AppContext) -> None:
    saved = ctx.ingestion.save(TUNA).recipe
    assert saved.id is not None
    with pytest.raises(CorrectionError):
        ctx.corrections.correct(saved.id, facet_corrections={"dietary_suitability": ["vegan"]})
    with pytest.raises(CorrectionError):
        ctx.corrections.correct(saved.id, field_updates={"total_minutes": -3})
    with pytest.raises(CorrectionError):
        ctx.corrections.correct(saved.id, field_updates={"colour": "red"})
    with pytest.raises(CorrectionError):
        ctx.corrections.correct(999, field_updates={"title": "x"})
