"""Deterministic dietary suitability rules.

The model may *propose* dietary labels, but these rules decide. A recipe's
stored dietary values are the full set of diets it satisfies, so filtering for
"vegetarian" also returns vegan recipes.
"""

from __future__ import annotations

from recipe_mcp.domain.ingredients import line_choices
from recipe_mcp.domain.models import FOOD_TYPES, IngredientFlags, Recipe, RecipeIngredient

DIET_ORDER: tuple[str, ...] = ("vegan", "vegetarian", "pescatarian", "omnivore")


def flags_for(ingredients: list[RecipeIngredient]) -> IngredientFlags:
    flags = IngredientFlags()
    for ingredient in ingredients:
        flags = flags.merge(ingredient.effective_flags)
    return flags


def allowed_diets(flags: IngredientFlags) -> list[str]:
    """Every diet the ingredient flags permit, most restrictive first."""
    diets: list[str] = []
    animal_free = not (
        flags.contains_meat
        or flags.contains_fish
        or flags.contains_shellfish
        or flags.contains_dairy
        or flags.contains_egg
    )
    if animal_free:
        diets.append("vegan")
    if not (flags.contains_meat or flags.contains_fish or flags.contains_shellfish):
        diets.append("vegetarian")
    if not flags.contains_meat:
        diets.append("pescatarian")
    diets.append("omnivore")
    return diets


def validate_claims(claimed: list[str], flags: IngredientFlags) -> tuple[list[str], list[str]]:
    """Split proposed dietary labels into (accepted, rejected) using the rules."""
    permitted = set(allowed_diets(flags))
    accepted = [c for c in claimed if c in permitted]
    rejected = [c for c in claimed if c not in permitted]
    return accepted, rejected


def satisfies(recipe_diets: list[str], required: list[str]) -> bool:
    """A recipe satisfies a request when it carries every required diet label."""
    have = set(recipe_diets)
    return all(diet in have for diet in required)


def strictest(diets: list[str]) -> str | None:
    for diet in DIET_ORDER:
        if diet in diets:
            return diet
    return None


def _types(flags: IngredientFlags) -> set[str]:
    return set(flags.food_types())


def _flags(types: set[str]) -> IngredientFlags:
    return IngredientFlags.from_food_types([t for t in FOOD_TYPES if t in types])


# The food types each diet rules out.
DIET_AVOIDS: dict[str, frozenset[str]] = {
    "vegan": frozenset(FOOD_TYPES),
    "vegetarian": frozenset({"meat", "fish", "shellfish"}),
    "pescatarian": frozenset({"meat"}),
    "omnivore": frozenset(),
}
# Words a person uses to exclude a whole food type: "nothing with egg", "no dairy".
_EXCLUDABLE: dict[str, frozenset[str]] = {
    "dairy": frozenset({"dairy"}),
    "egg": frozenset({"egg"}),
    "eggs": frozenset({"egg"}),
    "meat": frozenset({"meat"}),
    "fish": frozenset({"fish"}),
    "shellfish": frozenset({"shellfish"}),
    "seafood": frozenset({"fish", "shellfish"}),
}


def excluded_food_types(terms: list[str]) -> set[str]:
    """Food types named in an exclusion list ("dairy", "eggs", "seafood")."""
    found: set[str] = set()
    for term in terms:
        found |= _EXCLUDABLE.get(term.strip().lower(), frozenset())
    return found


def is_food_type_term(term: str) -> bool:
    return term.strip().lower() in _EXCLUDABLE


def _line_candidates(
    recipe: Recipe,
) -> list[tuple[set[str], list[tuple[str, set[str]]]]]:
    """Per ingredient line: its food types as written, and the stated choices as
    (swap text, food types if chosen)."""
    overrides = {
        i.canonical_name: i.food_types_override
        for i in recipe.ingredients
        if i.food_types_override is not None
    }
    by_line: dict[str, list[RecipeIngredient]] = {}
    for ingredient in recipe.ingredients:
        by_line.setdefault(ingredient.raw_text, []).append(ingredient)

    lines: list[tuple[set[str], list[tuple[str, set[str]]]]] = []
    for raw_text, ingredients in by_line.items():
        baseline: set[str] = set()
        for ingredient in ingredients:
            baseline |= _types(ingredient.effective_flags)
        stated = line_choices(raw_text)
        candidates: list[tuple[str, set[str]]] = []
        if stated.options:
            option_types = {o.name: _types(overrides.get(o.name, o.flags)) for o in stated.options}
            offered = set().union(*option_types.values())
            unconditional = baseline - offered
            candidates.extend(
                (f"use {o.label}", option_types[o.name] | unconditional) for o in stated.options
            )
        if stated.can_leave_out:
            flagged = [o.label for o in stated.options if _types(o.flags)] or [
                i.canonical_name for i in ingredients if _types(i.effective_flags)
            ]
            candidates.append((f"leave out {', '.join(flagged)}", set()))
        lines.append((baseline, candidates))
    return lines


def swaps_to_avoid(recipe: Recipe, avoid: set[str] | frozenset[str]) -> list[str] | None:
    """How to cook the recipe without the ``avoid`` food types using only choices its
    own lines state: ``[]`` when it already has none of them, the swaps when stated
    choices get there, ``None`` when they cannot.

    A line counts only when the author offers the choice: an "or" between foods, or a
    line marked optional or used as a garnish. Nothing is substituted by inference, and
    food types a line has outside its stated options always stay.
    """
    swaps: list[str] = []
    for baseline, candidates in _line_candidates(recipe):
        if not baseline & avoid:
            continue
        permitted = [(t, types) for t, types in candidates if not types & avoid]
        if not permitted:
            return None
        # A stated option before leaving the line out, then the least animal-based
        # one: "use shrimp" over "leave out", "vegetable stock" over "seafood stock".
        swaps.append(min(permitted, key=lambda c: (c[0].startswith("leave out"), len(c[1])))[0])
    return swaps


def can_be_made(recipe: Recipe) -> dict[str, list[str]]:
    """Stricter diets the recipe reaches through choices its own lines state.

    Returns ``{diet: [swap, ...]}`` for each diet not already satisfied as written,
    e.g. ``{"vegan": ["use vegetable broth", "leave out parmesan"]}``.
    """
    as_written = set(allowed_diets(recipe.flags))
    result: dict[str, list[str]] = {}
    for diet in DIET_ORDER:
        if diet in as_written:
            break  # every less strict diet is satisfied too
        swaps = swaps_to_avoid(recipe, DIET_AVOIDS[diet])
        if swaps is not None:
            result[diet] = swaps
    return result
