"""With MODEL_PROVIDER=none the server stays deterministic and the agent supplies parsing."""

from __future__ import annotations

from pathlib import Path

from mcp.client.client import Client

from recipe_mcp.adapters.mcp import build_server
from recipe_mcp.domain.taxonomy import Facet
from recipe_mcp.services import fixtures
from recipe_mcp.services.container import build_context
from recipe_mcp.settings import load_settings
from tests.conftest import NYT_FIXTURE_URL, FixtureFetcher, StubTitleFetcher


async def test_structured_save_and_agent_proposal(tmp_path: Path, nyt_html: str) -> None:
    settings = load_settings(
        env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'agent.db'}",
        model_provider="none",
        default_member="alex",
    )
    ctx = build_context(
        settings, fetcher=FixtureFetcher(nyt_html), title_fetcher=StubTitleFetcher()
    )
    try:
        fixtures.ensure_demo_members(ctx)
        async with Client(build_server(ctx)) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            assert {"title", "ingredients", "classifications", "total_minutes"} <= set(
                tools["save_recipe"].input_schema["properties"]
            )
            assert "proposed_by_agent" in tools["correct_recipe"].input_schema["properties"]

            # Free text without a model: the server asks the agent to parse it.
            free = await client.call_tool("save_recipe", {"input": "tuna salad with tomato"})
            assert free.is_error and "pass title and ingredients" in free.content[0].text  # type: ignore[union-attr]

            structured = await client.call_tool(
                "save_recipe",
                {
                    "input": "Tuna salad with tomato, quinoa, cucumber, arugula and seeds. "
                    "Need to season the tuna.",
                    "title": "Tuna Quinoa Salad",
                    "ingredients": ["tuna", "tomato", "quinoa", "cucumber", "arugula", "seeds"],
                    "notes": "Season the tuna before assembling",
                    "classifications": {
                        "dish_type": ["salad"],
                        "character": ["light", "fresh"],
                        "primary_ingredient": ["tuna"],
                    },
                },
            )
            assert not structured.is_error
            data = structured.structured_content
            assert data is not None
            r = data["recipe"]
            assert r["status"] == "draft" and r["total_minutes"] is None and r["added_by"] == "alex"
            assert r["classifications"]["dish_type"] == ["salad"]
            assert r["classifications"]["dietary_suitability"] == ["pescatarian", "omnivore"]
            assert data["needs_classification"] is False

            # A URL save extracts deterministically and asks the agent to classify.
            url = await client.call_tool("save_recipe", {"input": NYT_FIXTURE_URL})
            u = url.structured_content
            assert u is not None and u["needs_classification"] is True and u["needs_review"] is True
            rid = u["recipe"]["recipe_id"]
            assert u["recipe"]["classifications"]["dietary_suitability"] == ["omnivore"]
            assert u["recipe"]["classifications"]["cuisine"] == ["mediterranean"]  # parsed hint
            proposal = await client.call_tool(
                "correct_recipe",
                {
                    "recipe_id": rid,
                    "proposed_by_agent": True,
                    "facet_corrections": {
                        "dish_type": ["roast"],
                        "character": ["bright"],
                        "primary_ingredient": ["chicken", "dragonfruit"],
                    },
                },
            )
            p = proposal.structured_content
            assert p is not None
            assert p["recipe"]["classifications"]["dish_type"] == ["roast"]
            assert p["recipe"]["classifications"]["primary_ingredient"] == ["chicken"]
            assert any("dragonfruit" in c for c in p["changes"])
            assert p["recipe"]["needs_review"] == []

            # A person's correction still wins over the agent's proposal, and is recorded.
            ctx.corrections.private_evals_path = tmp_path / "evals"
            fixed = await client.call_tool(
                "correct_recipe", {"recipe_id": rid, "facet_corrections": {"dish_type": ["stew"]}}
            )
            assert fixed.structured_content is not None
            again = await client.call_tool(
                "correct_recipe",
                {
                    "recipe_id": rid,
                    "proposed_by_agent": True,
                    "facet_corrections": {"dish_type": ["roast"]},
                },
            )
            assert again.structured_content is not None
            assert again.structured_content["recipe"]["classifications"]["dish_type"] == ["stew"]
            assert (tmp_path / "evals" / "corrections.jsonl").exists()

            recs = await client.call_tool("recommend_recipes", {"dish_type": "stew"})
            assert recs.structured_content is not None
            assert rid in [x["recipe_id"] for x in recs.structured_content["results"]]
        stored = ctx.recipes.get(rid)
        assert stored is not None and stored.facet_values(Facet.DISH_TYPE) == ["stew"]
        assert ctx.model_runs.count() == 0  # no model was ever called
    finally:
        ctx.close()
