import pytest

from recipe_mcp.domain import dietary
from recipe_mcp.domain.ingredients import normalize_ingredients
from recipe_mcp.domain.models import IngredientFlags, Recipe, SourceType


def test_allowed_diets_ladder() -> None:
    assert dietary.allowed_diets(IngredientFlags()) == [
        "vegan",
        "vegetarian",
        "pescatarian",
        "omnivore",
    ]
    assert dietary.allowed_diets(IngredientFlags(contains_dairy=True)) == [
        "vegetarian",
        "pescatarian",
        "omnivore",
    ]
    assert dietary.allowed_diets(IngredientFlags(contains_fish=True)) == ["pescatarian", "omnivore"]
    assert dietary.allowed_diets(IngredientFlags(contains_shellfish=True)) == [
        "pescatarian",
        "omnivore",
    ]
    assert dietary.allowed_diets(IngredientFlags(contains_meat=True)) == ["omnivore"]


def test_validate_claims_rejects_contradictions() -> None:
    flags = dietary.flags_for(normalize_ingredients(["tuna", "tomato", "quinoa"]))
    accepted, rejected = dietary.validate_claims(["vegetarian", "pescatarian", "vegan"], flags)
    assert accepted == ["pescatarian"]
    assert rejected == ["vegetarian", "vegan"]


def test_satisfies_requires_every_label() -> None:
    assert dietary.satisfies(["vegan", "vegetarian", "pescatarian", "omnivore"], ["vegetarian"])
    assert not dietary.satisfies(["pescatarian", "omnivore"], ["vegetarian"])
    assert dietary.satisfies(["omnivore"], [])


def test_strictest() -> None:
    assert dietary.strictest(["omnivore", "pescatarian"]) == "pescatarian"
    assert dietary.strictest([]) is None


# "Can be made": only choices the recipe's own lines state, never inferred swaps.
def _recipe(lines: list[str]) -> Recipe:
    return Recipe(
        household_id=1,
        source_type=SourceType.OTHER,
        title="t",
        ingredients=normalize_ingredients(lines),
    )


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (
            ["1 cup red lentils", "1 quart chicken or vegetable broth"],
            {"vegan": ["use vegetable broth"]},
        ),
        (["1 cup red lentils", "1 quart chicken broth"], {}),  # no stated choice: no guess
        (["1 pound pasta", "Parmesan, for serving"], {"vegan": ["leave out parmesan"]}),
        (
            ["1 pound pasta", "4 ounces pancetta, diced (optional)"],
            {"vegan": ["leave out pancetta"]},
        ),
        (
            [
                "2 chicken thighs, cut into cubes, or 8 shrimp, optional",
                "2 tablespoons oyster sauce",
            ],
            {"pescatarian": ["use shrimp"]},
        ),
        (
            ["2 cups rice", "1 cup chicken, seafood or vegetable stock"],
            {"vegan": ["use vegetable stock"]},
        ),
        # "or" between describing words is not a choice.
        (["1 ½ pounds Mexican or Guatemalan chorizo or Portuguese chouriço"], {}),
        # A garnish list is left out, not picked from.
        (
            [
                "1 cup farro",
                "Toppings (optional): toasted nuts or seeds, grated or crumbled cheese, "
                "soft-boiled egg",
            ],
            {"vegan": ["leave out cheese, eggs"]},
        ),
        # Food types outside the stated options always stay.
        (
            ["2 cups chicken or vegetable stock with 1 tablespoon fish sauce"],
            {"pescatarian": ["use vegetable stock"]},
        ),
    ],
)
def test_can_be_made_uses_only_stated_choices(
    lines: list[str], expected: dict[str, list[str]]
) -> None:
    got = dietary.can_be_made(_recipe(lines))
    strictest = {k: v for k, v in got.items() if k == next(iter(got), None)}
    assert strictest == expected


def test_can_be_made_is_empty_when_already_satisfied() -> None:
    assert dietary.can_be_made(_recipe(["1 cup red lentils", "1 quart vegetable broth"])) == {}


def test_can_be_made_respects_food_type_corrections() -> None:
    recipe = _recipe(["1 cup red lentils", "1 quart chicken or vegetable broth"])
    for ingredient in recipe.ingredients:
        if ingredient.canonical_name == "stock":
            ingredient.food_types_override = IngredientFlags(contains_meat=True)
    assert "vegan" not in dietary.can_be_made(recipe)
