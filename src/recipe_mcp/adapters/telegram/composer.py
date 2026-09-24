"""Compose Telegram replies: HTML parse mode, bold titles and links only, 4,096 max."""

from __future__ import annotations

from html import escape

from recipe_mcp.domain.models import RecommendationResult

TELEGRAM_MAX_CHARS = 4096


def _one(result: RecommendationResult, index: int, reason_limit: int) -> str:
    title = escape(result.title)
    head = f"{index}. <b>{title}</b>"
    if result.source_url:
        head = f'{index}. <a href="{escape(result.source_url, quote=True)}">{title}</a>'
    time = f"{result.total_minutes} min" if result.total_minutes else "time unknown"
    facets = result.classifications
    parts = [
        vs[0]
        for key in ("dietary_suitability", "cuisine", "dish_type", "character")
        if (vs := facets.get(key))
    ]
    if parts and facets.get("dietary_suitability") and result.contains:
        parts[0] += f" ({', '.join(result.contains)})"  # "omnivore (meat, shellfish)"
    tags = " · ".join(parts)
    lines = [head, escape(f"{time} · {tags}" if tags else time)]
    if result.adapted_for:
        lines.append(escape(f"{result.adapted_for} if you {'; '.join(result.diet_swaps)}"))
    if result.ingredients_missing and result.ingredients_available:
        lines.append(escape("missing: " + ", ".join(result.ingredients_missing[:4])))
    reasons = "; ".join(r for r in result.reasons if not r.startswith(f"{result.adapted_for} if"))
    if reason_limit and reasons:
        lines.append(escape(reasons[:reason_limit]))
    return "\n".join(lines)


def format_recommendations(results: list[RecommendationResult]) -> str:
    """One message with up to three recommendations. Reasons are truncated before any
    recommendation is dropped."""
    if not results:
        return (
            "Nothing in the collection matches that yet. "
            "Try fewer constraints or save more recipes."
        )
    for reason_limit in (160, 80, 40, 0):
        body = "\n\n".join(_one(r, i, reason_limit) for i, r in enumerate(results, start=1))
        if len(body) <= TELEGRAM_MAX_CHARS:
            return body
    return "\n\n".join(_one(r, i, 0) for i, r in enumerate(results[:3], start=1))[
        :TELEGRAM_MAX_CHARS
    ]


def format_confirmation(confirmation: str) -> str:
    """Bold the first line of a save confirmation, escape the rest."""
    first, _, rest = confirmation.partition("\n")
    text = f"<b>{escape(first)}</b>"
    if rest:
        text += "\n" + escape(rest)
    text += "\nReply to this message with a correction if anything is wrong."
    return text[:TELEGRAM_MAX_CHARS]
