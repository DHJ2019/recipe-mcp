"""Hard filtering and deterministic scoring for recommendations.

The model never decides which recipes exist. It converts language into a
:class:`RecommendationRequest`; everything below is plain Python.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from recipe_mcp.domain import dietary
from recipe_mcp.domain import feedback as feedback_rules
from recipe_mcp.domain.ingredients import (
    canonical_name,
    ingredient_matches,
    matches_main_ingredient,
    title_mentions_main_ingredient,
)
from recipe_mcp.domain.models import (
    FOOD_TYPES,
    Feedback,
    Recipe,
    RecipeStatus,
    RecommendationRequest,
    RecommendationResult,
)
from recipe_mcp.domain.taxonomy import OTHER, Facet

RECENT_REPETITION_DAYS = 14

W_COVERAGE = 3.0
W_MISSING = 0.5
W_CHARACTER = 1.5
W_PREFERENCE = 1.0
W_AFFINITY = 0.5
W_TIME_FIT = 0.5
W_RECENT = 1.0
W_DRAFT = 0.25
W_TITLE_ONLY = 1.0
W_ADAPTED = 1.0


@dataclass
class Scored:
    recipe: Recipe
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    available: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    household_fit: str | None = None
    adapted_for: str | None = None
    diet_swaps: list[str] = field(default_factory=list)


def diet_fit(recipe: Recipe, request: RecommendationRequest) -> tuple[str, list[str]] | None:
    """How a recipe meets the request's diets and excluded food types.

    ``("as written", [])`` when it already does, ``(label, swaps)`` when choices its
    own lines state get there ("vegan", ["use vegetable broth"]), ``None`` otherwise.
    """
    diets = [d.lower() for d in request.dietary]
    if any(d not in dietary.DIET_AVOIDS for d in diets):
        return None
    excluded = dietary.excluded_food_types(request.excluded_ingredients)
    avoid: set[str] = set(excluded)
    for diet in diets:
        avoid |= dietary.DIET_AVOIDS[diet]
    if not avoid:
        return ("as written", [])
    swaps = dietary.swaps_to_avoid(recipe, avoid)
    if swaps is None:
        return None
    if not swaps:
        return ("as written", [])
    strictest = next((d for d in dietary.DIET_ORDER if d in diets and d != "omnivore"), None)
    implied = dietary.DIET_AVOIDS[strictest] if strictest else frozenset()
    label = [strictest] if strictest else []
    label += [f"no {t}" for t in FOOD_TYPES if t in excluded and t not in implied]
    return (", ".join(label), swaps)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def coverage(recipe: Recipe, available_ingredients: list[str]) -> tuple[list[str], list[str]]:
    """Split a recipe's non-staple ingredients into (available, missing)."""
    have: list[str] = []
    missing: list[str] = []
    for ingredient in recipe.ingredients:
        if ingredient.is_staple:
            continue
        if any(ingredient_matches(a, ingredient.canonical_name) for a in available_ingredients):
            have.append(ingredient.canonical_name)
        else:
            missing.append(ingredient.canonical_name)
    return have, missing


def main_ingredient_match(recipe: Recipe, wanted: str) -> str | None:
    """Why a recipe counts as built around ``wanted``, or ``None``.

    The main-ingredient label decides. A recipe with no label yet falls back to its
    title, and ranks below labelled matches.
    """
    labels = recipe.facet_values(Facet.PRIMARY_INGREDIENT)
    if labels:
        hit = next((v for v in labels if matches_main_ingredient(wanted, v)), None)
        return f"main ingredient: {hit}" if hit else None
    if title_mentions_main_ingredient(wanted, recipe.title):
        return f"title mentions {wanted}"
    return None


def rejection_reason(
    recipe: Recipe,
    request: RecommendationRequest,
    feedback: list[Feedback],
    now: datetime,
) -> str | None:
    """Return why a recipe fails the hard filters, or ``None`` if it passes."""
    if diet_fit(recipe, request) is None:
        return "dietary" if request.dietary else "excluded food type"
    if request.max_minutes is not None and (
        recipe.total_minutes is None or recipe.total_minutes > request.max_minutes
    ):
        return "time"
    if request.cuisine and request.cuisine.lower() not in recipe.facet_values(Facet.CUISINE):
        return "cuisine"
    if request.dish_type and request.dish_type.lower() not in recipe.facet_values(Facet.DISH_TYPE):
        return "dish_type"
    if request.main_ingredient and main_ingredient_match(recipe, request.main_ingredient) is None:
        return "main_ingredient"
    excluded = [
        canonical_name(e) for e in request.excluded_ingredients if not dietary.is_food_type_term(e)
    ]
    for ingredient in recipe.ingredients:
        if any(ingredient_matches(e, ingredient.canonical_name) for e in excluded):
            return f"excluded ingredient: {ingredient.canonical_name}"
    if request.available_ingredients and request.max_missing is not None:
        _, missing = coverage(recipe, request.available_ingredients)
        if len(missing) > request.max_missing:
            return "too many missing ingredients"
    if request.diners:
        for diner in request.diners:
            if feedback_rules.member_score(feedback, diner) == -2.0:
                return f"disliked by member {diner}"
    if request.exclude_recent_days is not None:
        cutoff = now - timedelta(days=request.exclude_recent_days)
        for entry in feedback:
            cooked = _parse_ts(entry.cooked_at) or _parse_ts(entry.created_at)
            if cooked and cooked >= cutoff:
                return "cooked recently"
    return None


def score(
    recipe: Recipe,
    request: RecommendationRequest,
    feedback: list[Feedback],
    affinity: dict[int, dict[tuple[str, str], float]],
    now: datetime,
) -> Scored:
    result = Scored(recipe=recipe)
    total = 0.0

    if request.dietary or request.excluded_ingredients:
        fit = diet_fit(recipe, request)
        if fit is not None and fit[0] != "as written":
            result.adapted_for, result.diet_swaps = fit
            result.reasons.append(f"{fit[0]} if you {'; '.join(fit[1])}")
            total -= W_ADAPTED

    if request.main_ingredient:
        why = main_ingredient_match(recipe, request.main_ingredient)
        if why:
            result.reasons.append(why)
            if why.startswith("title"):
                total -= W_TITLE_ONLY

    if request.available_ingredients:
        have, missing = coverage(recipe, request.available_ingredients)
        result.available, result.missing = have, missing
        non_staple = len(have) + len(missing)
        ratio = len(have) / non_staple if non_staple else 0.0
        total += W_COVERAGE * ratio - W_MISSING * len(missing)
        if have:
            result.reasons.append(f"uses {', '.join(have[:4])}")
        if missing:
            result.reasons.append(f"missing {len(missing)}: {', '.join(missing[:3])}")
        else:
            result.reasons.append("no missing non-staple ingredients")
    else:
        result.missing = [i.canonical_name for i in recipe.ingredients if not i.is_staple]

    wanted = {c.lower() for c in request.character}
    matched = [c for c in recipe.facet_values(Facet.CHARACTER) if c in wanted]
    if matched:
        total += W_CHARACTER * len(matched)
        result.reasons.append(f"feels {', '.join(matched)}")

    if request.max_minutes and recipe.total_minutes is not None:
        total += W_TIME_FIT * (1 - recipe.total_minutes / request.max_minutes)
        result.reasons.append(f"{recipe.total_minutes} minutes")
    elif recipe.total_minutes is not None:
        result.reasons.append(f"{recipe.total_minutes} minutes")

    diners = request.diners
    if diners:
        pref = feedback_rules.household_score(feedback, diners)
        if pref is not None:
            total += W_PREFERENCE * pref
            rated_all = all(feedback_rules.member_score(feedback, d) is not None for d in diners)
            if pref > 0 and rated_all and len(diners) > 1:
                result.household_fit = "both rated positively"
                result.reasons.append("both of you rated it positively")
            elif pref > 0:
                result.household_fit = "rated positively"
                result.reasons.append("rated positively")
        else:
            estimates: list[float] = []
            keys = [(f, v) for f, vs in recipe.classification_summary().items() for v in vs]
            for diner in diners:
                member_affinity = affinity.get(diner, {})
                values = [member_affinity[k] for k in keys if k in member_affinity]
                if values:
                    estimates.append(sum(values) / len(values))
            if estimates:
                est = min(estimates)
                total += W_AFFINITY * est
                if est > 0:
                    result.household_fit = (
                        "likely to suit both" if len(diners) > 1 else "likely fit"
                    )
                    result.reasons.append("similar to recipes you have liked")

    cutoff = now - timedelta(days=RECENT_REPETITION_DAYS)
    for entry in feedback:
        cooked = _parse_ts(entry.cooked_at)
        if cooked and cooked >= cutoff:
            total -= W_RECENT
            result.reasons.append("cooked recently")
            break

    if recipe.status == RecipeStatus.DRAFT:
        total -= W_DRAFT

    result.score = round(total, 3)
    return result


def _diversity_key(recipe: Recipe) -> tuple[str, str]:
    dish = recipe.facet_values(Facet.DISH_TYPE)
    primary = recipe.facet_values(Facet.PRIMARY_INGREDIENT)
    return (dish[0] if dish else OTHER, primary[0] if primary else OTHER)


def rank(
    recipes: list[Recipe],
    request: RecommendationRequest,
    feedback_by_recipe: dict[int, list[Feedback]],
    affinity: dict[int, dict[tuple[str, str], float]] | None = None,
    now: datetime | None = None,
) -> list[Scored]:
    """Apply hard filters, score, and pick ``limit`` meaningfully different recipes."""
    now = now or datetime.now(UTC)
    affinity = affinity or {}
    scored: list[Scored] = []
    for recipe in recipes:
        fb = feedback_by_recipe.get(recipe.id or -1, [])
        if rejection_reason(recipe, request, fb, now) is not None:
            continue
        scored.append(score(recipe, request, fb, affinity, now))
    scored.sort(key=lambda s: (-s.score, s.recipe.title.lower()))

    chosen: list[Scored] = []
    seen_keys: set[tuple[str, str]] = set()
    for candidate in scored:
        key = _diversity_key(candidate.recipe)
        if key in seen_keys:
            continue
        chosen.append(candidate)
        seen_keys.add(key)
        if len(chosen) >= request.limit:
            return chosen
    # Not enough distinct recipes: fill with the best remaining ones.
    for candidate in scored:
        if candidate in chosen:
            continue
        chosen.append(candidate)
        if len(chosen) >= request.limit:
            break
    return chosen


def to_result(scored: Scored) -> RecommendationResult:
    recipe = scored.recipe
    return RecommendationResult(
        recipe_id=recipe.id or 0,
        title=recipe.title,
        total_minutes=recipe.total_minutes,
        status=recipe.status,
        classifications=recipe.classification_summary(),
        contains=recipe.flags.food_types(),
        adapted_for=scored.adapted_for,
        diet_swaps=scored.diet_swaps,
        ingredients_available=scored.available,
        ingredients_missing=scored.missing,
        reasons=scored.reasons,
        score=scored.score,
        source_url=recipe.canonical_source_url,
        household_fit=scored.household_fit,
    )
