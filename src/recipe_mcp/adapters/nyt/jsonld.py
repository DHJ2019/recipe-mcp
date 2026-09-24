"""Extract a schema.org Recipe from a page's JSON-LD blocks (deterministic)."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

_SCRIPT_RE = re.compile(
    r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


class ParsedRecipe(BaseModel):
    title: str
    ingredients: list[str] = Field(default_factory=list)
    servings: str | None = None
    total_minutes: int | None = None
    hands_on_minutes: int | None = None
    cuisine: str | None = None
    category: str | None = None
    canonical_url: str | None = None


def parse_iso_duration(value: str | None) -> int | None:
    """``PT1H30M`` -> 90. Returns ``None`` for missing or unparsable values."""
    if not value or not isinstance(value, str):
        return None
    match = _DURATION_RE.match(value.strip().upper())
    if not match:
        return None
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    total = days * 1440 + hours * 60 + minutes + (1 if seconds >= 30 else 0)
    return total or None


def _is_recipe(node: Any) -> bool:
    if not isinstance(node, dict):
        return False
    node_type = node.get("@type")
    if isinstance(node_type, list):
        return "Recipe" in node_type
    return node_type == "Recipe"


def _find_recipe_nodes(data: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(data, list):
        for item in data:
            found.extend(_find_recipe_nodes(item))
    elif isinstance(data, dict):
        if _is_recipe(data):
            found.append(data)
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in data:
                found.extend(_find_recipe_nodes(data[key]))
    return found


def _first_str(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        for item in value:
            text = _first_str(item)
            if text:
                return text
    if isinstance(value, dict):
        return _first_str(value.get("name") or value.get("@id"))
    return None


def _str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            text = _first_str(item)
            if text:
                out.append(text)
        return out
    return []


def parse_recipe_jsonld(html: str) -> ParsedRecipe | None:
    """Return the first schema.org Recipe found in the page, or ``None``."""
    for block in _SCRIPT_RE.findall(html):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for node in _find_recipe_nodes(data):
            title = _first_str(node.get("name"))
            if not title:
                continue
            total = parse_iso_duration(node.get("totalTime"))
            prep = parse_iso_duration(node.get("prepTime"))
            cook = parse_iso_duration(node.get("cookTime"))
            if total is None and (prep or cook):
                total = (prep or 0) + (cook or 0)
            url = _first_str(node.get("url") or node.get("@id") or node.get("mainEntityOfPage"))
            return ParsedRecipe(
                title=title,
                ingredients=_str_list(node.get("recipeIngredient")),
                servings=_first_str(node.get("recipeYield")),
                total_minutes=total,
                hands_on_minutes=prep,
                cuisine=_first_str(node.get("recipeCuisine")),
                category=_first_str(node.get("recipeCategory")),
                canonical_url=url,
            )
    return None


def has_usable_recipe(html: str) -> bool:
    """True when the page carries a Recipe with at least one ingredient.

    Paywalled NYT pages still render a Recipe node with an empty ingredient list, so
    both conditions matter before deciding a fetch succeeded.
    """
    parsed = parse_recipe_jsonld(html)
    return parsed is not None and bool(parsed.ingredients)
