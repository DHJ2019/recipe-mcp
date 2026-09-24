"""Load synthetic demonstration recipes and members from the evals fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from recipe_mcp.domain.ingredients import normalize_ingredients
from recipe_mcp.domain.models import (
    Classification,
    FacetSource,
    Feedback,
    Member,
    Recipe,
    RecipeStatus,
    Sentiment,
    SourceType,
)
from recipe_mcp.domain.taxonomy import Facet
from recipe_mcp.services.categorization import rule_classifications
from recipe_mcp.services.container import AppContext

REPO_ROOT = Path(__file__).resolve().parents[3]
EVALS_DIR = REPO_ROOT / "evals"
SYNTHETIC_RECIPES = EVALS_DIR / "recipes" / "synthetic_recipes.yaml"
TUNA_FIXTURE = EVALS_DIR / "recipes" / "tuna_quinoa_salad.yaml"
INITIAL_QUERIES = EVALS_DIR / "queries" / "initial_queries.yaml"
DEMO_MEMBERS: tuple[tuple[str, str], ...] = (("alex", "Alex"), ("sam", "Sam"))


def load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def recipe_from_fixture(data: dict[str, Any], household_id: int) -> Recipe:
    recipe = Recipe(
        household_id=household_id,
        source_type=SourceType(data.get("source_type", "other")),
        canonical_source_url=data.get("source_url"),
        title=data["title"],
        servings=str(data["servings"]) if data.get("servings") is not None else None,
        total_minutes=data.get("total_minutes"),
        notes=list(data.get("notes", [])),
        status=RecipeStatus(data.get("status", "complete")),
        ingredients=normalize_ingredients(list(data.get("ingredients", []))),
    )
    recipe.classifications = rule_classifications(recipe)
    approved = data.get("classifications", {})
    for facet_name, values in approved.items():
        facet = Facet(facet_name)
        if facet in {Facet.DIETARY, Facet.EFFORT} and facet_name != "effort":
            continue  # dietary is always derived from rules
        for value in values if isinstance(values, list) else [values]:
            if facet == Facet.EFFORT and recipe.total_minutes is not None:
                continue
            recipe.classifications.append(
                Classification(
                    facet=facet,
                    value=str(value),
                    source=FacetSource.USER,
                    confidence=1.0,
                    user_confirmed=True,
                )
            )
    recipe.content_hash = recipe.compute_content_hash()
    return recipe


def ensure_demo_members(ctx: AppContext) -> list[Member]:
    members = ctx.members.list_for_household(ctx.household_id)
    existing = {m.member_key for m in members}
    for key, name in DEMO_MEMBERS:
        if key not in existing:
            members.append(
                ctx.members.create(
                    Member(household_id=ctx.household_id, member_key=key, display_name=name)
                )
            )
    return members


def load_synthetic_recipes(ctx: AppContext, path: Path = SYNTHETIC_RECIPES) -> list[Recipe]:
    """Idempotently load the synthetic recipe set. Returns the stored recipes."""
    stored: list[Recipe] = []
    for data in load_yaml(path)["recipes"]:
        recipe = recipe_from_fixture(data, ctx.household_id)
        existing = None
        if recipe.canonical_source_url:
            existing = ctx.recipes.find_by_url(ctx.household_id, recipe.canonical_source_url)
        if existing is None:
            existing = ctx.recipes.find_by_content_hash(ctx.household_id, recipe.content_hash)
        stored.append(existing or ctx.recipes.create(recipe))
    return stored


def load_demo_feedback(
    ctx: AppContext, recipes: list[Recipe], path: Path = SYNTHETIC_RECIPES
) -> int:
    """Seed the demo ratings declared in the fixture file (idempotent)."""
    members = {m.member_key: m for m in ensure_demo_members(ctx)}
    by_title = {r.title: r for r in recipes}
    added = 0
    for entry in load_yaml(path).get("feedback", []):
        recipe = by_title.get(entry["recipe"])
        member = members.get(str(entry["member"]).lower())
        if recipe is None or member is None or recipe.id is None or member.id is None:
            continue
        already = [f for f in ctx.feedback.for_recipe(recipe.id) if f.member_id == member.id]
        if already:
            continue
        ctx.feedback.add(
            Feedback(
                recipe_id=recipe.id,
                member_id=member.id,
                sentiment=Sentiment(entry["sentiment"]),
                notes=entry.get("notes"),
                cooked_at=entry.get("cooked_at"),
            )
        )
        added += 1
    return added


def seed_demo(ctx: AppContext) -> tuple[list[Recipe], int]:
    ensure_demo_members(ctx)
    recipes = load_synthetic_recipes(ctx)
    added = load_demo_feedback(ctx, recipes)
    return recipes, added
