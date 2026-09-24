import pytest

from recipe_mcp.domain import dietary
from recipe_mcp.domain.ingredients import (
    canonical_name,
    flags_for_name,
    ingredient_matches,
    matches_main_ingredient,
    normalize_ingredient,
    normalize_ingredients,
    normalize_line,
    title_mentions_main_ingredient,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2 scallions, sliced", "green onion"),
        ("8 boneless, skinless chicken thighs", "chicken"),
        ("1 can coconut milk", "coconut milk"),
        ("Kosher salt and black pepper", "salt and pepper"),
        ("mixed seeds", "seeds"),
        ("seeds", "seeds"),
        ("2 carrots, sliced", "carrot"),
        ("1/2 head savoy cabbage, shredded", "cabbage"),
        ("3 tablespoons extra-virgin olive oil", "olive oil"),
        ("2 eggs", "eggs"),
        ("1 cup red lentils", "red lentils"),
        ("fresh coriander", "cilantro"),
    ],
)
def test_canonical_names(raw: str, expected: str) -> None:
    assert canonical_name(raw) == expected


def test_normalize_ingredient_splits_quantity_and_preparation() -> None:
    ing = normalize_ingredient("2 tablespoons red curry paste, plus more to taste")
    assert ing.quantity == "2 tablespoons"
    assert ing.preparation == "plus more to taste"
    assert ing.canonical_name == "red curry paste"
    assert ing.category == "pantry"


def test_staples_detected() -> None:
    assert normalize_ingredient("1 tablespoon olive oil").is_staple
    assert normalize_ingredient("salt").is_staple
    assert not normalize_ingredient("2 salmon fillets").is_staple


@pytest.mark.parametrize(
    ("name", "meat", "fish", "shellfish", "dairy", "egg"),
    [
        ("chicken", True, False, False, False, False),
        ("chicken stock", True, False, False, False, False),
        ("salmon", False, True, False, False, False),
        ("fish sauce", False, True, False, False, False),
        ("shrimp", False, False, True, False, False),
        ("oyster sauce", False, False, True, False, False),
        ("parmesan", False, False, False, True, False),
        ("coconut milk", False, False, False, False, False),
        ("peanut butter", False, False, False, False, False),
        ("eggs", False, False, False, False, True),
        ("eggplant", False, False, False, False, False),
        ("egg noodles", False, False, False, False, True),
        ("vegetable stock", False, False, False, False, False),
        ("tofu", False, False, False, False, False),
    ],
)
def test_flags(name: str, meat: bool, fish: bool, shellfish: bool, dairy: bool, egg: bool) -> None:
    f = flags_for_name(name)
    assert (
        f.contains_meat,
        f.contains_fish,
        f.contains_shellfish,
        f.contains_dairy,
        f.contains_egg,
    ) == (
        meat,
        fish,
        shellfish,
        dairy,
        egg,
    )


def test_normalize_ingredients_deduplicates() -> None:
    result = normalize_ingredients(["1 onion", "2 onions, diced", "", "garlic"])
    assert [i.canonical_name for i in result] == ["onion", "garlic"]


def test_ingredient_matches_is_forgiving_but_not_loose() -> None:
    assert ingredient_matches("salmon", "salmon")
    assert ingredient_matches("carrots", "carrot")
    assert ingredient_matches("cabbage", "cabbage")
    assert ingredient_matches("napa cabbage", "cabbage")
    assert not ingredient_matches("salmon", "chicken")
    # Word-subset matches are allowed in both directions.
    assert ingredient_matches("rice", "rice noodles")
    assert ingredient_matches("tomato paste", "tomato")


# Regression: NYT phrasings that lost the protein word, so meat and fish recipes were
# tagged vegan or vegetarian after the WhatsApp backfill.
@pytest.mark.parametrize(
    ("raw", "name", "preparation"),
    [
        ("2 pounds bone-in, skin-on chicken thighs", "chicken", None),
        (
            "3 pounds bone-in, skin-on chicken thighs and drumsticks, patted dry",
            "chicken thighs drumstick",
            "patted dry",
        ),
        ("4 skin-on salmon fillets", "salmon", None),
        ("3 Cornish hens, skinned and halved", "cornish hen", "skinned and halved"),
        ("2 (5-ounce) filets mignons", "filet mignon", None),
        ("2 (4-ounce) tins sardines packed in olive oil", "sardines", None),
        ("8 ounces labneh", "labneh", None),
        ("1 pound frozen potsticker dumplings (not thawed)", "potsticker dumpling", None),
        ("1 pound frozen, unthawed dumplings, any flavor", "dumpling", "any flavor"),
        ("1 can tuna in olive oil", "tuna", None),
    ],
)
def test_protein_phrasings_keep_the_protein(raw: str, name: str, preparation: str | None) -> None:
    ing = normalize_ingredient(raw)
    assert ing.canonical_name == name
    assert ing.preparation == preparation


@pytest.mark.parametrize(
    ("raw", "diet"),
    [
        ("2 pounds bone-in, skin-on chicken thighs", "omnivore"),
        ("3 Cornish hens, skinned and halved", "omnivore"),
        ("2 (5-ounce) filets mignons", "omnivore"),
        ("2 (4-ounce) tins sardines packed in olive oil", "pescatarian"),
        ("8 ounces labneh", "vegetarian"),
        # A dumpling's food type comes from its stated filling, never a default.
        ("1 pound frozen potsticker dumplings (not thawed)", "vegan"),
        ("1 pound frozen, unthawed dumplings, any flavor", "vegan"),
        ("12 frozen vegetable dumplings", "vegan"),
        ("1 pound frozen pork dumplings", "omnivore"),
        ("16 shrimp dumplings", "pescatarian"),
        # Egg counts only when egg is listed: mayonnaise can be made without it.
        ("½ cup mayonnaise", "vegan"),
        ("¼ cup garlic aioli", "vegan"),
        ("1 package wonton wrappers", "vegan"),
        ("2 tablespoons Worcestershire sauce", "pescatarian"),
    ],
)
def test_protein_phrasings_set_dietary_flags(raw: str, diet: str) -> None:
    ing = normalize_ingredient(raw)
    assert dietary.strictest(dietary.allowed_diets(ing.flags)) == diet


# A line that names several foods carries all of their food types; alternatives count.
@pytest.mark.parametrize(
    ("raw", "names", "contains"),
    [
        (
            "2 boneless, skinless chicken thighs, cut into 1-inch cubes, or 8 large peeled, "
            "deveined shrimp (about ½ pound), optional",
            ["chicken", "shrimp"],
            ["meat", "shellfish"],
        ),
        ("1 pound ground pork, beef, lamb or turkey", ["pork", "beef", "lamb", "turkey"], ["meat"]),
        ("1 quart chicken or vegetable broth", ["stock", "chicken"], ["meat"]),
        (
            "1 ¼ pounds skinless hake, cod or other white fish fillets",
            ["hake", "cod", "fish"],
            ["fish"],
        ),
        ("¼ cup crème fraîche or sour cream", ["creme fraiche sour cream"], ["dairy"]),
        (
            "1 cup/4 ounces coarsely grated Gruyère or Comté cheese",
            ["gruyere comte cheese"],
            ["dairy"],
        ),
        ("1 pound pork or shrimp dumplings", ["pork shrimp dumpling"], ["meat", "shellfish"]),
    ],
)
def test_every_food_on_a_line_counts(raw: str, names: list[str], contains: list[str]) -> None:
    found = normalize_line(raw)
    assert [i.canonical_name for i in found] == names
    assert dietary.flags_for(found).food_types() == contains


@pytest.mark.parametrize(
    ("raw", "category"),
    [
        (
            "1 ½ pounds mixed mushrooms (oyster, shiitake, cremini or button), stemmed",
            "vegetable",
        ),
        ("8 ounces oyster mushrooms, torn", "vegetable"),
        ("1 (15-ounce) can cannellini beans, butter beans or navy beans, drained", "legume"),
        ("2 (15-ounce) cans butter beans, rinsed", "legume"),
        ("¼ teaspoon cream of tartar", "other"),
        ("¼ cup minced bread and butter pickles", "grain"),
        ("Olive oil, for forming the meatballs", "pantry"),
    ],
)
def test_lookalike_words_are_not_animal_foods(raw: str, category: str) -> None:
    found = normalize_line(raw)
    assert dietary.flags_for(found).food_types() == []
    assert found[0].category == category


def test_line_foods_do_not_crowd_out_their_own_lines() -> None:
    result = normalize_ingredients(
        ["2 chicken thighs, or 8 shrimp", "1 pound shrimp, peeled", "2 eggs"]
    )
    assert [(i.canonical_name, i.quantity) for i in result] == [
        ("chicken", "2"),
        ("shrimp", "1 pound"),
        ("eggs", "2"),
    ]


@pytest.mark.parametrize(
    ("wanted", "name", "expected"),
    [
        ("mushroom", "oyster mushroom", True),
        ("mushrooms", "mushroom", True),
        ("mushroom-based", "mushroom", True),
        ("beans", "chickpeas", True),
        ("bean-based", "red lentils", True),
        ("legumes", "white beans", True),
        ("beans", "mushroom", False),
        ("seafood", "shrimp", True),
        ("fish", "shrimp", False),
        ("poultry", "chicken", True),
        ("meat", "tofu", False),
    ],
)
def test_main_ingredient_matching(wanted: str, name: str, expected: bool) -> None:
    assert matches_main_ingredient(wanted, name) is expected


def test_title_fallback_for_main_ingredient() -> None:
    assert title_mentions_main_ingredient("mushroom", "Creamy Mushroom Stroganoff")
    assert title_mentions_main_ingredient("beans", "Braised Chickpeas With Greens")
    assert not title_mentions_main_ingredient("mushroom", "Lemon Chicken")
