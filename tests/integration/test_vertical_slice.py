"""Save an NYT fixture, categorize it, retrieve it and get it recommended."""

from __future__ import annotations

from recipe_mcp.domain.models import RecipeStatus, RecommendationRequest, SourceType
from recipe_mcp.domain.taxonomy import Facet
from recipe_mcp.services.container import AppContext
from tests.conftest import NYT_FIXTURE_URL, FixtureFetcher


def test_save_nyt_fixture_end_to_end(ctx: AppContext, fetcher: FixtureFetcher) -> None:
    result = ctx.ingestion.save(NYT_FIXTURE_URL + "?utm_source=share")
    recipe = result.recipe
    assert result.created
    assert recipe.source_type == SourceType.NYT
    assert recipe.status == RecipeStatus.COMPLETE
    assert recipe.canonical_source_url == NYT_FIXTURE_URL
    assert recipe.total_minutes == 45
    assert recipe.servings == "4 servings"
    assert recipe.is_recommendable
    names = [i.canonical_name for i in recipe.ingredients]
    assert "chicken" in names and "cabbage" in names and "carrot" in names
    assert recipe.facet_values(Facet.DIETARY) == ["omnivore"]
    assert recipe.facet_values(Facet.EFFORT) == ["weeknight"]
    assert recipe.facet_values(Facet.CUISINE) == ["mediterranean"]
    assert "chicken" in recipe.facet_values(Facet.PRIMARY_INGREDIENT)
    assert fetcher.calls == [NYT_FIXTURE_URL + "?utm_source=share"]
    assert ctx.model_runs.count() == 1

    # Idempotent: the same canonical URL (and a short link to it) never fetches again.
    again = ctx.ingestion.save(
        "https://www.cooking.nytimes.com/recipes/1000001-Test-Lemon-Chicken-Thighs/"
    )
    assert not again.created and again.recipe.id == recipe.id
    assert len(fetcher.calls) == 1
    short = ctx.ingestion.save("https://nyti.ms/abc123")
    assert not short.created and short.recipe.id == recipe.id
    assert len(fetcher.calls) == 2  # short links must be resolved before dedup

    assert recipe.id is not None
    fetched = ctx.recipes.get(recipe.id)
    assert fetched is not None and fetched.title == "Test Kitchen Lemon Chicken Thighs"

    recs = ctx.recommendation.recommend(
        RecommendationRequest(
            max_minutes=60, available_ingredients=["chicken", "cabbage", "carrots"]
        )
    )
    assert recs and recs[0].recipe_id == recipe.id
    assert set(recs[0].ingredients_available) == {"chicken", "cabbage", "carrot"}
    assert recs[0].source_url == NYT_FIXTURE_URL


def test_recategorize_uses_cache(ctx: AppContext) -> None:
    result = ctx.ingestion.save(NYT_FIXTURE_URL)
    ctx.categorization.categorize(result.recipe)
    runs = ctx.db.connection.execute(
        "SELECT validation_status FROM model_runs ORDER BY id"
    ).fetchall()
    assert [r["validation_status"] for r in runs] == ["ok", "cached"]


def test_confirmation_text(ctx: AppContext) -> None:
    result = ctx.ingestion.save(NYT_FIXTURE_URL)
    text = result.confirmation()
    assert text.startswith("Saved: Test Kitchen Lemon Chicken Thighs")
    assert "Omnivore" in text and "45 minutes" in text
