"""Repository interface contracts against a temporary SQLite database."""

from __future__ import annotations

import pytest

from recipe_mcp.domain.ingredients import normalize_ingredients
from recipe_mcp.domain.models import (
    Classification,
    FacetSource,
    Feedback,
    Member,
    ModelRun,
    Recipe,
    Sentiment,
    SourceType,
)
from recipe_mcp.domain.taxonomy import Facet
from recipe_mcp.services.container import AppContext


def _recipe(ctx: AppContext, title: str = "Test Soup", url: str | None = None) -> Recipe:
    r = Recipe(
        household_id=ctx.household_id,
        source_type=SourceType.OTHER if url else SourceType.PERSONAL,
        canonical_source_url=url,
        title=title,
        total_minutes=30,
        notes=["a note"],
        ingredients=normalize_ingredients(["2 carrots, diced", "salt", "1 can coconut milk"]),
        classifications=[
            Classification(
                facet=Facet.CUISINE, value="thai", source=FacetSource.MODEL, confidence=0.8
            )
        ],
    )
    return ctx.recipes.create(r)


def test_recipe_roundtrip_preserves_ingredients_and_facets(ctx: AppContext) -> None:
    stored = _recipe(ctx, url="https://example.com/r/1")
    assert stored.id is not None
    loaded = ctx.recipes.get(stored.id)
    assert loaded is not None
    assert [i.canonical_name for i in loaded.ingredients] == ["carrot", "salt", "coconut milk"]
    assert loaded.ingredients[0].quantity == "2"
    assert loaded.ingredients[0].preparation == "diced"
    assert loaded.ingredients[1].is_staple
    assert loaded.notes == ["a note"]
    assert loaded.facet_values(Facet.CUISINE) == ["thai"]
    assert loaded.content_hash == stored.content_hash
    assert ctx.recipes.find_by_url(ctx.household_id, "https://example.com/r/1") is not None
    assert ctx.recipes.find_by_content_hash(ctx.household_id, stored.content_hash) is not None
    assert ctx.recipes.count(ctx.household_id) == 1


def test_replace_classifications_keeps_user_confirmed(ctx: AppContext) -> None:
    stored = _recipe(ctx)
    assert stored.id is not None
    ctx.recipes.confirm_facet(stored.id, Facet.CUISINE, ["japanese"])
    ctx.recipes.replace_classifications(
        stored.id,
        [
            Classification(
                facet=Facet.CUISINE,
                value="thai",
                source=FacetSource.MODEL,
                confidence=0.9,
                needs_review=True,
            )
        ],
    )
    loaded = ctx.recipes.get(stored.id)
    assert loaded is not None
    assert loaded.facet_values(Facet.CUISINE) == ["japanese"]
    assert not loaded.facet_needs_review(Facet.CUISINE)
    assert ctx.recipes.list_uncategorized(ctx.household_id) == []


def test_needs_review_roundtrip(ctx: AppContext) -> None:
    stored = _recipe(ctx)
    assert stored.id is not None
    ctx.recipes.replace_classifications(
        stored.id,
        [
            Classification(
                facet=Facet.DISH_TYPE,
                value="soup",
                source=FacetSource.MODEL,
                confidence=0.4,
                needs_review=True,
            )
        ],
    )
    loaded = ctx.recipes.get(stored.id)
    assert loaded is not None and loaded.facet_needs_review(Facet.DISH_TYPE)


def test_update_recipe_rewrites_ingredients(ctx: AppContext) -> None:
    stored = _recipe(ctx)
    stored.title = "Renamed"
    stored.ingredients = normalize_ingredients(["tofu"])
    ctx.recipes.update(stored)
    loaded = ctx.recipes.get(stored.id or 0)
    assert loaded is not None
    assert loaded.title == "Renamed"
    assert [i.canonical_name for i in loaded.ingredients] == ["tofu"]


def test_link_stubs_are_not_uncategorized(ctx: AppContext) -> None:
    ctx.recipes.create(
        Recipe(
            household_id=ctx.household_id,
            source_type=SourceType.OTHER,
            canonical_source_url="https://example.com/x",
            title="A link",
        )
    )
    assert ctx.recipes.list_uncategorized(ctx.household_id) == []


def test_members_and_feedback(ctx: AppContext) -> None:
    m = ctx.members.create(
        Member(
            household_id=ctx.household_id,
            member_key="alex",
            display_name="Alex",
            telegram_user_id=4242,
            whatsapp_export_name="Alexander",
        )
    )
    assert ctx.members.by_key(ctx.household_id, "ALEX") is not None
    assert ctx.members.by_telegram_id(4242) is not None
    assert ctx.members.by_export_name(ctx.household_id, "alexander") is not None
    assert ctx.members.by_name(ctx.household_id, "alex") is not None
    m.display_name = "Alexa"
    ctx.members.upsert(m)
    assert len(ctx.members.list_for_household(ctx.household_id)) == 1
    r = _recipe(ctx)
    assert r.id is not None and m.id is not None
    ctx.feedback.add(
        Feedback(
            recipe_id=r.id, member_id=m.id, sentiment=Sentiment.LOVE, reported_by_member_id=m.id
        )
    )
    stored = ctx.feedback.for_recipe(r.id)[0]
    assert stored.sentiment == Sentiment.LOVE and stored.reported_by_member_id == m.id
    assert r.id in ctx.feedback.for_household(ctx.household_id)


def test_refresh_staples(ctx: AppContext) -> None:
    _recipe(ctx)
    assert ctx.recipes.refresh_staples(frozenset({"carrot"})) == 2  # carrot on, salt off
    assert ctx.recipes.refresh_staples(frozenset({"carrot"})) == 0


def test_model_runs_and_cache(ctx: AppContext) -> None:
    ctx.model_runs.record(
        ModelRun(
            task="t", input_hash="h", provider="fake", model="m", prompt_version="v1", latency_ms=3
        )
    )
    assert ctx.model_runs.count() == 1
    assert ctx.model_runs.cache_get("t", "h", "v1", "m") is None
    ctx.model_runs.cache_put("t", "h", "v1", "m", '{"x": 1}')
    assert ctx.model_runs.cache_get("t", "h", "v1", "m") == '{"x": 1}'


def test_app_state_roundtrip(ctx: AppContext) -> None:
    assert ctx.state.get("telegram_update_offset") is None
    ctx.state.set("telegram_update_offset", "42")
    ctx.state.set("telegram_update_offset", "43")
    assert ctx.state.get("telegram_update_offset") == "43"


def test_pending_interactions_are_per_chat_and_expire(ctx: AppContext) -> None:
    ctx.pending.put("-100123", "recent_results", {"ids": [3, 1]}, "2999-01-01T00:00:00+00:00")
    assert ctx.pending.get("-100123", "recent_results") == {"ids": [3, 1]}
    ctx.pending.put("-100123", "recent_results", {"ids": [5]}, "2999-01-01T00:00:00+00:00")
    assert ctx.pending.get("-100123", "recent_results") == {"ids": [5]}
    ctx.pending.put("-100123", "draft_confirmation", {"x": 1}, "2000-01-01T00:00:00+00:00")
    assert ctx.pending.get("-100123", "draft_confirmation") is None
    ctx.pending.clear("-100123", "recent_results")
    assert ctx.pending.get("-100123", "recent_results") is None
    with pytest.raises(ValueError):
        ctx.pending.put("1", "bogus", {}, "2999-01-01T00:00:00+00:00")
