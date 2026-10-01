"""Controlled classification vocabulary.

The taxonomy is intentionally small. The model may only choose from these values;
anything else becomes ``other`` plus a proposed value that is recorded for review.
"""

from __future__ import annotations

from enum import StrEnum

OTHER = "other"


class Facet(StrEnum):
    DIETARY = "dietary_suitability"
    CUISINE = "cuisine"
    DISH_TYPE = "dish_type"
    MEAL = "meal"
    PRIMARY_INGREDIENT = "primary_ingredient"
    EFFORT = "effort"
    CHARACTER = "character"
    COOKING_METHOD = "cooking_method"
    HEALTH = "health_orientation"


DIETARY_VALUES: tuple[str, ...] = ("vegan", "vegetarian", "pescatarian", "omnivore")
CUISINE_VALUES: tuple[str, ...] = (
    "thai",
    "italian",
    "indian",
    "japanese",
    "korean",
    "chinese",
    "vietnamese",
    "mexican",
    "mediterranean",
    "american",
    "french",
    OTHER,
)
DISH_TYPE_VALUES: tuple[str, ...] = (
    "soup",
    "salad",
    "curry",
    "stew",
    "pasta",
    "roast",
    "stir-fry",
    "sandwich",
    "rice dish",
    "noodle dish",
    OTHER,
)
MEAL_VALUES: tuple[str, ...] = ("breakfast", "lunch", "dinner", "starter", "dessert", "snack")
EFFORT_VALUES: tuple[str, ...] = ("quick", "weeknight", "weekend", "project")
CHARACTER_VALUES: tuple[str, ...] = ("bright", "fresh", "light", "cozy", "rich", "spicy")
COOKING_METHOD_VALUES: tuple[str, ...] = (
    "no-cook",
    "roast",
    "bake",
    "grill",
    "braise",
    "pressure cook",
    OTHER,
)
HEALTH_VALUES: tuple[str, ...] = ("light", "balanced", "rich")

# Primary ingredients are an open list of common proteins and bases. Values not
# listed here are kept verbatim (they are grounded in the ingredient list rather
# than invented), which is why the facet is not strictly controlled.
PRIMARY_INGREDIENT_VALUES: tuple[str, ...] = (
    "salmon",
    "tuna",
    "cod",
    "shrimp",
    "chicken",
    "beef",
    "pork",
    "lamb",
    "tofu",
    "tempeh",
    "legumes",
    "egg",
    "mushroom",
    "pumpkin",
    "cabbage",
    "cauliflower",
    "eggplant",
    "potato",
)

CONTROLLED_VALUES: dict[Facet, tuple[str, ...]] = {
    Facet.DIETARY: DIETARY_VALUES,
    Facet.CUISINE: CUISINE_VALUES,
    Facet.DISH_TYPE: DISH_TYPE_VALUES,
    Facet.MEAL: MEAL_VALUES,
    Facet.EFFORT: EFFORT_VALUES,
    Facet.CHARACTER: CHARACTER_VALUES,
    Facet.COOKING_METHOD: COOKING_METHOD_VALUES,
    Facet.HEALTH: HEALTH_VALUES,
}

# Facets that accept several values for a single recipe.
MULTI_VALUE_FACETS: frozenset[Facet] = frozenset(
    {Facet.DIETARY, Facet.MEAL, Facet.PRIMARY_INGREDIENT, Facet.CHARACTER}
)


def normalize_value(facet: Facet, value: str) -> tuple[str, str | None]:
    """Map a proposed value onto the controlled vocabulary.

    Returns ``(accepted_value, proposed_value)``. When the value is not in the
    vocabulary the accepted value is ``other`` (or the verbatim value for the open
    primary-ingredient facet) and ``proposed_value`` carries the original text.
    """
    cleaned = value.strip().lower()
    if facet == Facet.PRIMARY_INGREDIENT:
        return cleaned, None
    allowed = CONTROLLED_VALUES[facet]
    if cleaned in allowed:
        return cleaned, None
    if OTHER in allowed:
        return OTHER, cleaned or None
    # Facets without an ``other`` escape hatch drop unknown values entirely.
    return "", cleaned or None


def effort_for_minutes(total_minutes: int | None) -> str | None:
    """Deterministic effort bucket from total time; ``None`` when time is unknown."""
    if total_minutes is None:
        return None
    if total_minutes <= 25:
        return "quick"
    if total_minutes <= 45:
        return "weeknight"
    if total_minutes <= 120:
        return "weekend"
    return "project"
