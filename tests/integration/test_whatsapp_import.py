"""Historical export import: extraction, dedup, attribution, stubs, idempotent re-import."""

from __future__ import annotations

from pathlib import Path

from recipe_mcp.domain.models import Member, RecommendationRequest, SourceType
from recipe_mcp.services.container import AppContext
from tests.conftest import FixtureFetcher


def test_plan_deduplicates_and_flags_unsupported(ctx: AppContext, export_path: Path) -> None:
    plan = ctx.whatsapp_import.plan(export_path)
    statuses = [(p.status, p.canonical_url) for p in plan]
    assert statuses == [
        ("planned", "https://cooking.nytimes.com/recipes/1000001-test-lemon-chicken-thighs"),
        ("planned", "https://cooking.nytimes.com/recipes/1000002-test-cabbage-soup"),
        ("planned_unsupported", "https://example.com/blog/knife-skills"),
    ]


def test_run_imports_once_attributes_and_reports(
    ctx: AppContext, export_path: Path, fetcher: FixtureFetcher
) -> None:
    alex = ctx.members.create(
        Member(household_id=ctx.household_id, member_key="alex", display_name="Alex")
    )
    report = ctx.whatsapp_import.run(export_path)
    assert report.counts() == {"imported": 2, "stored_unsupported": 1}
    assert len(fetcher.calls) == 2
    first = ctx.recipes.get(1)
    assert first is not None and first.added_by_member_id == alex.id  # sent by Alex
    second = ctx.recipes.get(2)
    assert second is not None and second.added_by_member_id is None  # Sam is not configured
    stub = ctx.recipes.get(3)
    assert stub is not None and not stub.is_recommendable
    assert stub.title == "Knife Skills 101" and stub.source_type == SourceType.OTHER
    md = report.to_markdown()
    assert "imported: 2" in md and "Test Kitchen Lemon Chicken Thighs" in md
    assert "Other links" in md and "Knife Skills 101" in md
    assert "status,title" in report.to_csv()

    # Idempotent: a re-export with the same links changes nothing and fetches nothing.
    again = ctx.whatsapp_import.run(export_path)
    assert again.counts() == {"duplicate": 2, "unsupported_duplicate": 1}
    assert len(fetcher.calls) == 2
    assert ctx.recipes.count(ctx.household_id) == 3

    review = ctx.categorization.report(ctx.household_id)
    assert "| 1 | Test Kitchen Lemon Chicken Thighs |" in review
    assert "Unsupported links" in review
    recs = ctx.recommendation.recommend(RecommendationRequest())
    assert recs and all(r.recipe_id != 3 for r in recs)
