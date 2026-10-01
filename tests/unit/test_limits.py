import pytest

from recipe_mcp.domain import limits
from recipe_mcp.domain.limits import InputTooLarge


def test_values_at_the_limit_pass_and_one_over_fails() -> None:
    limits.check_text("title", "x" * limits.MAX_TITLE_CHARS, limits.MAX_TITLE_CHARS)
    with pytest.raises(InputTooLarge, match="title is longer than 300 characters"):
        limits.check_text("title", "x" * (limits.MAX_TITLE_CHARS + 1), limits.MAX_TITLE_CHARS)
    limits.check_text("servings", None, limits.MAX_SERVINGS_CHARS)


def test_lists_are_limited_by_count_and_by_entry_length() -> None:
    limits.check_items("ingredients", ["salt"] * limits.MAX_INGREDIENTS, 100, 1000)
    with pytest.raises(InputTooLarge, match="ingredients has more than 100 entries"):
        limits.check_items("ingredients", ["salt"] * 101, 100, 1000)
    with pytest.raises(InputTooLarge, match="each entry in ingredients"):
        limits.check_items("ingredients", ["x" * 1001], 100, 1000)


def test_errors_name_the_field_never_the_value() -> None:
    secret = "private family recipe " * 100
    with pytest.raises(InputTooLarge) as exc:
        limits.check_recipe_fields(title=secret)
    assert "private family recipe" not in str(exc.value)


def test_facets_limit_names_values_and_lengths() -> None:
    limits.check_facets("classifications", {"cuisine": "italian", "character": ["light"]})
    limits.check_facets("classifications", None)
    with pytest.raises(InputTooLarge, match="more than 20 facets"):
        limits.check_facets("classifications", {f"f{i}": [] for i in range(21)})
    with pytest.raises(InputTooLarge, match=r"classifications\.character has more than 20"):
        limits.check_facets("classifications", {"character": ["light"] * 21})
    with pytest.raises(InputTooLarge, match=r"each entry in classifications\.cuisine"):
        limits.check_facets("classifications", {"cuisine": "x" * 101})


def test_field_updates_cover_every_text_field() -> None:
    limits.check_field_updates(
        {"title": "Soup", "notes": "good", "servings": 4, "add_ingredients": ["salt"]}
    )
    cases: list[dict[str, object]] = [
        {"title": "x" * 301},
        {"notes": "x" * 2001},
        {"notes": ["ok"] * 21},
        {"servings": "x" * 101},
        {"add_ingredients": ["salt"] * 101},
        {"remove_ingredients": ["x" * 1001]},
        {"food_types": {f"item {i}": [] for i in range(101)}},
        {"food_types": {"stock": ["meat"] * 11}},
    ]
    for updates in cases:
        with pytest.raises(InputTooLarge):
            limits.check_field_updates(updates)
