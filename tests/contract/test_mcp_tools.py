"""Contract tests: every MCP tool's schema and round-trip behaviour via a real client."""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp.client.client import Client
from mcp.types import CallToolResult

from recipe_mcp.adapters.mcp import TOOL_NAMES, build_server
from recipe_mcp.services.container import AppContext


def _payload(result: CallToolResult) -> dict[str, Any]:
    if result.structured_content is not None:
        return dict(result.structured_content)
    text = next(c for c in result.content if getattr(c, "type", "") == "text").text  # type: ignore[union-attr]
    return dict(json.loads(text))


async def test_tool_list_and_schemas(seeded_ctx: AppContext) -> None:
    async with Client(build_server(seeded_ctx)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == set(TOOL_NAMES)

    save = tools["save_recipe"].input_schema
    assert save["required"] == ["input"]
    assert {"input", "notes", "member"} <= set(save["properties"])

    rec = tools["recommend_recipes"].input_schema
    assert "required" not in rec or rec["required"] == []
    assert {
        "dietary",
        "cuisine",
        "dish_type",
        "main_ingredient",
        "character",
        "max_minutes",
        "available_ingredients",
        "excluded_ingredients",
        "max_missing",
        "exclude_recent_days",
        "member",
        "limit",
    } <= set(rec["properties"])
    assert "diners" not in rec["properties"]
    assert tools["recommend_recipes"].annotations is not None
    assert tools["recommend_recipes"].annotations.read_only_hint is True

    assert tools["get_recipe"].input_schema["required"] == ["recipe_id"]
    rate = tools["rate_recipe"].input_schema
    assert set(rate["required"]) == {"recipe_id", "sentiment"}
    assert {"member", "on_behalf_of", "notes"} <= set(rate["properties"])
    correct = tools["correct_recipe"].input_schema
    assert correct["required"] == ["recipe_id"]
    assert {"facet_corrections", "field_updates", "member"} <= set(correct["properties"])


async def test_recommend_recipes_returns_three_results(seeded_ctx: AppContext) -> None:
    async with Client(build_server(seeded_ctx)) as client:
        result = await client.call_tool(
            "recommend_recipes", {"character": ["cozy"], "max_minutes": 45}
        )
    assert not result.is_error
    data = _payload(result)
    assert data["count"] == 3
    for item in data["results"]:
        assert {
            "recipe_id",
            "title",
            "total_minutes",
            "classifications",
            "reasons",
            "source_url",
        } <= set(item)
        assert item["total_minutes"] <= 45
        assert "cozy" in item["classifications"]["character"]


async def test_recommend_household_view_and_member_view(seeded_ctx: AppContext) -> None:
    async with Client(build_server(seeded_ctx)) as client:
        household = await client.call_tool("recommend_recipes", {"cuisine": "korean"})
        alex = await client.call_tool("recommend_recipes", {"cuisine": "korean", "member": "alex"})
        veg = await client.call_tool(
            "recommend_recipes", {"dietary": ["vegetarian"], "cuisine": "thai"}
        )
        bad = await client.call_tool("recommend_recipes", {"member": "nobody"})
    # Sam disliked the Korean beef bowls: hidden from the household view, shown to Alex.
    assert _payload(household)["count"] == 0
    assert _payload(alex)["count"] == 1
    assert len(_payload(household)["request"]["diners"]) == 2
    data = _payload(veg)
    assert data["count"] >= 1
    assert all("vegetarian" in r["classifications"]["dietary_suitability"] for r in data["results"])
    assert bad.is_error


async def test_recommend_by_main_ingredient(seeded_ctx: AppContext) -> None:
    async with Client(build_server(seeded_ctx)) as client:
        beans = await client.call_tool(
            "recommend_recipes", {"main_ingredient": "bean-based", "limit": 10}
        )
        mushroom = await client.call_tool("recommend_recipes", {"main_ingredient": "mushroom"})
    titles = {r["title"] for r in _payload(beans)["results"]}
    assert titles == {
        "Cabbage and White Bean Soup",
        "Lemony Chickpea Salad with Cucumber and Feta",
        "Cauliflower Dal",
    }
    assert [r["title"] for r in _payload(mushroom)["results"]] == ["Mushroom Risotto"]
    assert _payload(beans)["request"]["main_ingredient"] == "bean-based"


async def test_get_recipe_and_not_found(seeded_ctx: AppContext) -> None:
    async with Client(build_server(seeded_ctx)) as client:
        ok = await client.call_tool("get_recipe", {"recipe_id": 1})
        missing = await client.call_tool("get_recipe", {"recipe_id": 999})
    data = _payload(ok)
    assert data["recipe"]["title"]
    assert data["recipe"]["ingredients"]
    assert data["recipe"]["needs_review"] == []
    assert isinstance(data["recipe"]["contains"], list)
    assert isinstance(data["recipe"]["can_be_made"], dict)
    assert {"food_types", "food_types_corrected"} <= set(data["recipe"]["ingredients"][0])
    assert data["feedback"]["recipe_id"] == 1
    assert missing.is_error


async def test_rate_recipe_records_on_behalf_and_default_member(seeded_ctx: AppContext) -> None:
    async with Client(build_server(seeded_ctx)) as client:
        result = await client.call_tool(
            "rate_recipe", {"recipe_id": 2, "member": "alex", "sentiment": "👍", "notes": "nice"}
        )
        behalf = await client.call_tool(
            "rate_recipe",
            {"recipe_id": 2, "member": "alex", "on_behalf_of": "sam", "sentiment": "dislike"},
        )
        nobody = await client.call_tool("rate_recipe", {"recipe_id": 2, "sentiment": "like"})
        bad = await client.call_tool(
            "rate_recipe", {"recipe_id": 2, "member": "Nobody", "sentiment": "like"}
        )
    data = _payload(result)
    assert data["recorded"] == "like"
    assert data["feedback"]["members"][0]["member_key"] == "alex"
    b = _payload(behalf)
    sam = next(m for m in b["feedback"]["members"] if m["member_key"] == "sam")
    assert sam["sentiment"] == "dislike" and sam["reported_by"] == "alex"
    assert b["feedback"]["household_verdict"] == "one_dislikes"
    assert nobody.is_error  # no DEFAULT_MEMBER configured in tests
    assert bad.is_error

    seeded_ctx.settings.default_member = "sam"
    async with Client(build_server(seeded_ctx)) as client:
        default = await client.call_tool("rate_recipe", {"recipe_id": 3, "sentiment": "love"})
    assert _payload(default)["feedback"]["members"][0]["member_key"] == "sam"


async def test_save_recipe_personal_url_and_link_stub(seeded_ctx: AppContext) -> None:
    async with Client(build_server(seeded_ctx)) as client:
        personal = await client.call_tool(
            "save_recipe",
            {
                "input": "Save this: lentil soup with red lentils, carrot, cumin and lemon. "
                "Serves 4.",
                "member": "sam",
            },
        )
        url = await client.call_tool(
            "save_recipe",
            {"input": "https://cooking.nytimes.com/recipes/1000001-test-lemon-chicken-thighs"},
        )
        again = await client.call_tool(
            "save_recipe",
            {
                "input": "https://cooking.nytimes.com/recipes/1000001-test-lemon-chicken-thighs"
                "?utm_source=x"
            },
        )
        other = await client.call_tool("save_recipe", {"input": "https://example.com/some-recipe"})
        invalid = await client.call_tool("save_recipe", {"input": "https://nyti.ms/not-a-recipe"})
    p = _payload(personal)
    assert p["created"] is True
    assert p["recipe"]["status"] == "draft"
    assert p["recipe"]["total_minutes"] is None
    assert p["recipe"]["added_by"] == "sam"
    assert p["confirmation"].startswith("Saved: ")
    u = _payload(url)
    assert u["created"] is True and u["recipe"]["source_type"] == "nyt"
    assert _payload(again)["created"] is False
    o = _payload(other)
    assert o["created"] is True and o["recipe"]["source_type"] == "other"
    assert o["recipe"]["title"] == "Knife Skills 101"
    assert "link" in o["confirmation"]
    assert invalid.is_error


async def test_correct_recipe_overrides_and_fills_time(seeded_ctx: AppContext) -> None:
    tuna = next(
        r
        for r in seeded_ctx.recipes.list_for_household(seeded_ctx.household_id)
        if r.title == "Tuna Quinoa Salad"
    )
    assert tuna.id is not None and tuna.total_minutes is None
    async with Client(build_server(seeded_ctx)) as client:
        result = await client.call_tool(
            "correct_recipe",
            {
                "recipe_id": tuna.id,
                "field_updates": {"total_minutes": 30},
                "facet_corrections": {"character": ["light", "bright"]},
                "member": "alex",
            },
        )
        bad_facet = await client.call_tool(
            "correct_recipe", {"recipe_id": tuna.id, "facet_corrections": {"colour": ["red"]}}
        )
        empty = await client.call_tool("correct_recipe", {"recipe_id": tuna.id})
        missing = await client.call_tool(
            "correct_recipe", {"recipe_id": 999, "field_updates": {"title": "x"}}
        )
    data = _payload(result)
    assert data["recipe"]["total_minutes"] == 30
    assert data["recipe"]["status"] == "complete"
    assert data["recipe"]["classifications"]["character"] == ["light", "bright"]
    assert data["recipe"]["classifications"]["effort"] == ["weeknight"]
    assert "total_minutes -> 30" in data["changes"]
    assert bad_facet.is_error and empty.is_error and missing.is_error


def _error_text(result: CallToolResult) -> str:
    assert result.is_error
    return " ".join(getattr(c, "text", "") for c in result.content)


async def test_write_tools_reject_oversized_input_without_storing_it(
    seeded_ctx: AppContext,
) -> None:
    household = seeded_ctx.household_id
    before = len(seeded_ctx.recipes.list_for_household(household))
    recipe = seeded_ctx.recipes.get(2)
    assert recipe is not None
    huge = "pasta night " * 400  # 4,800 characters
    async with Client(build_server(seeded_ctx)) as client:
        long_title = await client.call_tool(
            "save_recipe", {"input": "x", "title": huge, "ingredients": ["salt"]}
        )
        many_ingredients = await client.call_tool(
            "save_recipe", {"input": "x", "title": "Soup", "ingredients": ["salt"] * 101}
        )
        long_input = await client.call_tool("save_recipe", {"input": "x" * 20_001})
        long_note = await client.call_tool(
            "rate_recipe", {"recipe_id": 2, "member": "alex", "sentiment": "like", "notes": huge}
        )
        partial = await client.call_tool(
            "correct_recipe",
            {
                "recipe_id": 2,
                "field_updates": {"title": "Renamed", "notes": [huge]},
                "member": "alex",
            },
        )
        proposal = await client.call_tool(
            "correct_recipe",
            {
                "recipe_id": 2,
                "facet_corrections": {"character": ["light"] * 21},
                "proposed_by_agent": True,
            },
        )
    assert "title is longer than 300 characters" in _error_text(long_title)
    assert "ingredients has more than 100 entries" in _error_text(many_ingredients)
    assert "input is longer than" in _error_text(long_input)
    assert "notes is longer than" in _error_text(long_note)
    assert "notes is longer than" in _error_text(partial)
    assert "facet_corrections.character" in _error_text(proposal)
    for result in (long_title, long_note, partial):
        assert "pasta night" not in _error_text(result)
    # Nothing was stored: no new recipe, no rating, and no half-applied correction.
    assert len(seeded_ctx.recipes.list_for_household(household)) == before
    assert seeded_ctx.feedback_service.summary(2).members == []
    after = seeded_ctx.recipes.get(2)
    assert after is not None and after.title == recipe.title


@pytest.mark.parametrize("name", TOOL_NAMES)
async def test_every_tool_has_description(seeded_ctx: AppContext, name: str) -> None:
    async with Client(build_server(seeded_ctx)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert tools[name].description
