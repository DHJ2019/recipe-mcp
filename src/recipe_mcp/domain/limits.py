"""Size limits on text that reaches storage through the write tools.

The Telegram brain fills tool arguments from household messages and web pages, so a
crafted message could ask it to save arbitrarily large values. Oversized input is
rejected, never truncated, so a recipe is never stored silently incomplete. Messages
name the field and the limit, never the value.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

MAX_INPUT_CHARS = 20_000  # a URL or free-text description passed to save_recipe
MAX_TITLE_CHARS = 300
MAX_INGREDIENTS = 100
MAX_INGREDIENT_CHARS = 1_000
MAX_NOTES = 20
MAX_NOTE_CHARS = 2_000
MAX_SERVINGS_CHARS = 100
MAX_FACETS = 20
MAX_FACET_VALUES = 20
MAX_FACET_VALUE_CHARS = 100


class InputTooLarge(ValueError):
    """A tool argument is over its size limit."""


def check_text(field: str, value: object, limit: int) -> None:
    if value is not None and len(str(value)) > limit:
        raise InputTooLarge(f"{field} is longer than {limit} characters")


def check_items(field: str, values: Iterable[object], max_items: int, max_chars: int) -> None:
    items = list(values)
    if len(items) > max_items:
        raise InputTooLarge(f"{field} has more than {max_items} entries")
    for item in items:
        check_text(f"each entry in {field}", item, max_chars)


def as_list(value: object) -> list[object]:
    """A single value or a list of values, as the tools accept either."""
    if value is None:
        return []
    if isinstance(value, str) or not isinstance(value, Iterable):
        return [value]
    return list(value)


def check_facets(field: str, facets: Mapping[str, object] | None) -> None:
    if not facets:
        return
    if len(facets) > MAX_FACETS:
        raise InputTooLarge(f"{field} has more than {MAX_FACETS} facets")
    for name, values in facets.items():
        check_text(f"a facet name in {field}", name, MAX_FACET_VALUE_CHARS)
        check_items(f"{field}.{name}", as_list(values), MAX_FACET_VALUES, MAX_FACET_VALUE_CHARS)


def check_recipe_fields(
    *,
    title: object = None,
    ingredients: Iterable[object] = (),
    notes: Iterable[object] = (),
    servings: object = None,
) -> None:
    check_text("title", title, MAX_TITLE_CHARS)
    check_items("ingredients", ingredients, MAX_INGREDIENTS, MAX_INGREDIENT_CHARS)
    check_items("notes", notes, MAX_NOTES, MAX_NOTE_CHARS)
    check_text("servings", servings, MAX_SERVINGS_CHARS)


def check_field_updates(updates: Mapping[str, object] | None) -> None:
    """Limits for correct_recipe's field_updates, checked before anything is written."""
    if not updates:
        return
    check_recipe_fields(
        title=updates.get("title"),
        notes=as_list(updates.get("notes")),
        servings=updates.get("servings"),
    )
    for key in ("add_ingredients", "remove_ingredients"):
        check_items(key, as_list(updates.get(key)), MAX_INGREDIENTS, MAX_INGREDIENT_CHARS)
    food_types = updates.get("food_types")
    if isinstance(food_types, Mapping):
        check_items("food_types", food_types.keys(), MAX_INGREDIENTS, MAX_INGREDIENT_CHARS)
        for types in food_types.values():
            check_items("each food_types list", as_list(types), 10, MAX_FACET_VALUE_CHARS)
