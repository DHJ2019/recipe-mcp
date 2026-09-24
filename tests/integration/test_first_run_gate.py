"""The Stage 1 gate: fresh database + synthetic fixtures -> save, correct, retrieve,
recommend through a real MCP client, with the offline eval set passing."""

from __future__ import annotations

from pathlib import Path

from mcp.client.client import Client

from recipe_mcp.adapters.mcp import build_server
from recipe_mcp.domain.taxonomy import Facet
from recipe_mcp.providers.fake import FakeModelClient
from recipe_mcp.services import fixtures
from recipe_mcp.services.container import build_context
from recipe_mcp.services.evals import run_evals
from recipe_mcp.settings import load_settings


async def test_fresh_clone_gate() -> None:
    settings = load_settings(
        env_file=None, app_env="test", database_url="sqlite:///:memory:", model_provider="fake"
    )
    ctx = build_context(settings, model=FakeModelClient())
    try:
        recipes, ratings = fixtures.seed_demo(ctx)
        assert len(recipes) == 15 and ratings == 7
        recipes2, ratings2 = fixtures.seed_demo(ctx)
        assert len(recipes2) == 15 and ratings2 == 0  # idempotent
        async with Client(build_server(ctx)) as client:
            rec = await client.call_tool(
                "recommend_recipes", {"character": ["cozy"], "max_minutes": 45}
            )
            assert rec.structured_content is not None and rec.structured_content["count"] == 3
            tuna = next(r for r in recipes if r.title == "Tuna Quinoa Salad")
            corrected = await client.call_tool(
                "correct_recipe", {"recipe_id": tuna.id, "field_updates": {"total_minutes": 20}}
            )
            assert corrected.structured_content is not None
            assert corrected.structured_content["recipe"]["total_minutes"] == 20
            got = await client.call_tool("get_recipe", {"recipe_id": tuna.id})
            assert got.structured_content is not None
            assert got.structured_content["recipe"]["classifications"]["effort"] == ["quick"]
            quick = await client.call_tool(
                "recommend_recipes", {"max_minutes": 25, "dish_type": "salad"}
            )
            assert quick.structured_content is not None
            assert tuna.id in [r["recipe_id"] for r in quick.structured_content["results"]]
    finally:
        ctx.close()


def test_offline_eval_set_passes() -> None:
    report = run_evals()
    assert report.passed, report.render()
    assert report.private is None


def test_private_evals_replay(tmp_path: Path) -> None:
    settings = load_settings(
        env_file=None, app_env="test", database_url="sqlite:///:memory:", model_provider="fake"
    )
    ctx = build_context(settings, model=FakeModelClient())
    try:
        fixtures.seed_demo(ctx)
        private = tmp_path / "evals"
        ctx.corrections.private_evals_path = private
        ctx.corrections.correct(1, facet_corrections={"cuisine": ["thai"]})
        (private / "queries.yaml").write_text(
            "queries:\n  - id: p1\n    text: cozy soup\n"
            "    constraints: {character: [cozy], dish_type: soup}\n"
            "    expected_any: [Thai Pumpkin Soup]\n"
        )
        report = run_evals(live_ctx=ctx, private_path=private)
        assert report.private is not None
        assert report.private.corrections_checked == 1 and report.private.passed
        assert "Private evaluation set" in report.render()
        # A regression: the correction no longer holds.
        ctx.recipes.confirm_facet(1, Facet.CUISINE, ["korean"])
        report = run_evals(live_ctx=ctx, private_path=private)
        assert report.private is not None and not report.private.passed
    finally:
        ctx.close()
