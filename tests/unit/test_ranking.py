from datetime import UTC, datetime, timedelta

from recipe_mcp.domain import ranking
from recipe_mcp.domain.ingredients import normalize_ingredients
from recipe_mcp.domain.models import (
    Classification,
    FacetSource,
    Feedback,
    Recipe,
    RecipeStatus,
    RecommendationRequest,
    Sentiment,
    SourceType,
)
from recipe_mcp.domain.taxonomy import Facet
from recipe_mcp.services.categorization import rule_classifications


def make(
    rid: int,
    title: str,
    ingredients: list[str],
    minutes: int | None,
    dish: str = "other",
    character: list[str] | None = None,
    primary: str | None = None,
) -> Recipe:
    r = Recipe(
        id=rid,
        household_id=1,
        source_type=SourceType.OTHER,
        title=title,
        total_minutes=minutes,
        ingredients=normalize_ingredients(ingredients),
        status=RecipeStatus.COMPLETE,
    )
    r.classifications = rule_classifications(r)
    r.classifications.append(
        Classification(facet=Facet.DISH_TYPE, value=dish, source=FacetSource.USER)
    )
    for c in character or []:
        r.classifications.append(
            Classification(facet=Facet.CHARACTER, value=c, source=FacetSource.USER)
        )
    if primary:
        r.classifications.append(
            Classification(facet=Facet.PRIMARY_INGREDIENT, value=primary, source=FacetSource.USER)
        )
    return r


NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)

SOUP = make(1, "Veg Soup", ["cabbage", "carrot", "stock", "salt"], 40, "soup", ["cozy"], "cabbage")
SALMON = make(2, "Salmon", ["salmon fillets", "lemon", "dill"], 25, "roast", ["light"], "salmon")
STEW = make(3, "Beef Stew", ["beef", "red wine", "carrot"], 180, "stew", ["rich", "cozy"], "beef")
DRAFT = make(4, "Tuna Draft", ["tuna", "quinoa"], None, "salad", ["light"], "tuna")


def test_dietary_hard_filter() -> None:
    req = RecommendationRequest(dietary=["vegetarian"])
    assert ranking.rejection_reason(SOUP, req, [], NOW) is None
    assert ranking.rejection_reason(SALMON, req, [], NOW) == "dietary"
    assert ranking.rejection_reason(STEW, req, [], NOW) == "dietary"


def test_time_filter_excludes_unknown_time() -> None:
    req = RecommendationRequest(max_minutes=45)
    assert ranking.rejection_reason(SOUP, req, [], NOW) is None
    assert ranking.rejection_reason(STEW, req, [], NOW) == "time"
    assert ranking.rejection_reason(DRAFT, req, [], NOW) == "time"


def test_excluded_ingredient_filter() -> None:
    req = RecommendationRequest(excluded_ingredients=["carrots"])
    assert ranking.rejection_reason(SOUP, req, [], NOW) is not None
    assert ranking.rejection_reason(SALMON, req, [], NOW) is None


def test_coverage_and_missing() -> None:
    have, missing = ranking.coverage(SOUP, ["cabbage"])
    assert have == ["cabbage"]
    assert missing == ["carrot"]  # stock and salt are staples


def test_max_missing_only_applies_with_available_ingredients() -> None:
    assert ranking.rejection_reason(SOUP, RecommendationRequest(max_missing=0), [], NOW) is None
    req = RecommendationRequest(available_ingredients=["cabbage"], max_missing=0)
    assert ranking.rejection_reason(SOUP, req, [], NOW) == "too many missing ingredients"


def test_dislike_by_diner_is_a_hard_filter() -> None:
    fb = [Feedback(id=1, recipe_id=1, member_id=7, sentiment=Sentiment.DISLIKE)]
    req = RecommendationRequest(diners=[7])
    assert ranking.rejection_reason(SOUP, req, fb, NOW) == "disliked by member 7"
    assert ranking.rejection_reason(SOUP, RecommendationRequest(), fb, NOW) is None


def test_recent_repetition_penalised_and_optionally_excluded() -> None:
    recent = (NOW - timedelta(days=3)).isoformat()
    fb = {1: [Feedback(id=1, recipe_id=1, member_id=1, sentiment=Sentiment.LIKE, cooked_at=recent)]}
    plain = ranking.rank([SOUP], RecommendationRequest(), {}, now=NOW)[0].score
    penalised = ranking.rank([SOUP], RecommendationRequest(), fb, now=NOW)[0].score
    assert penalised < plain
    assert ranking.rank([SOUP], RecommendationRequest(exclude_recent_days=14), fb, now=NOW) == []


def test_character_match_raises_score_and_reasons() -> None:
    req = RecommendationRequest(character=["cozy"])
    ranked = ranking.rank([SOUP, SALMON, STEW], req, {}, now=NOW)
    assert ranked[0].recipe.title in {"Veg Soup", "Beef Stew"}
    assert any("cozy" in r for r in ranked[0].reasons)


def test_diversity_prefers_distinct_dish_and_primary() -> None:
    soup2 = make(5, "Cabbage Soup 2", ["cabbage", "stock"], 30, "soup", ["cozy"], "cabbage")
    req = RecommendationRequest(character=["cozy"], limit=2)
    ranked = ranking.rank([SOUP, soup2, STEW], req, {}, now=NOW)
    keys = {
        (
            r.recipe.facet_values(Facet.DISH_TYPE)[0],
            r.recipe.facet_values(Facet.PRIMARY_INGREDIENT)[0],
        )
        for r in ranked
    }
    assert len(keys) == 2


def test_household_fit_when_both_rated() -> None:
    fb = {
        1: [
            Feedback(id=1, recipe_id=1, member_id=1, sentiment=Sentiment.LOVE),
            Feedback(id=2, recipe_id=1, member_id=2, sentiment=Sentiment.LIKE),
        ]
    }
    ranked = ranking.rank([SOUP], RecommendationRequest(diners=[1, 2]), fb, now=NOW)
    assert ranked[0].household_fit == "both rated positively"


def test_to_result_shape() -> None:
    scored = ranking.rank(
        [SOUP], RecommendationRequest(available_ingredients=["cabbage"]), {}, now=NOW
    )[0]
    result = ranking.to_result(scored)
    assert result.recipe_id == 1
    assert result.ingredients_available == ["cabbage"]
    assert result.ingredients_missing == ["carrot"]
    assert "dish_type" in result.classifications


MUSHROOM_PASTA = make(
    10, "Mushroom Pasta", ["oyster mushrooms", "pasta", "parmesan"], 30, "pasta", [], "mushroom"
)
CHICKPEA_STEW = make(11, "Chickpea Stew", ["chickpeas", "tomato"], 40, "stew", [], "chickpeas")
UNLABELLED_STROGANOFF = make(12, "Mushroom Stroganoff", ["mushrooms", "sour cream"], 30, "stew")
CHILI_WITH_BEANS = make(
    13, "Beef Chili", ["beef", "kidney beans", "tomato"], 60, "stew", [], "beef"
)
MAIN_POOL = [SOUP, SALMON, MUSHROOM_PASTA, CHICKPEA_STEW, UNLABELLED_STROGANOFF, CHILI_WITH_BEANS]


def test_main_ingredient_is_a_hard_filter_on_the_label() -> None:
    req = RecommendationRequest(main_ingredient="mushroom")
    ranked = ranking.rank(MAIN_POOL, req, {}, now=NOW)
    assert [s.recipe.id for s in ranked] == [10, 12]
    assert "main ingredient: mushroom" in ranked[0].reasons


def test_main_ingredient_title_fallback_ranks_below_labelled_matches() -> None:
    req = RecommendationRequest(main_ingredient="mushroom")
    labelled, by_title = ranking.rank(MAIN_POOL, req, {}, now=NOW)
    assert by_title.recipe.id == 12
    assert "title mentions mushroom" in by_title.reasons
    assert labelled.score > by_title.score


def test_main_ingredient_group_matches_related_ingredients() -> None:
    # A chili that merely contains beans is not bean-based: its main ingredient is beef.
    req = RecommendationRequest(main_ingredient="bean-based")
    assert [s.recipe.id for s in ranking.rank(MAIN_POOL, req, {}, now=NOW)] == [11]
    req = RecommendationRequest(main_ingredient="seafood")
    assert [s.recipe.id for s in ranking.rank(MAIN_POOL, req, {}, now=NOW)] == [2]


def test_results_show_the_food_types_behind_the_diet() -> None:
    [result] = [
        ranking.to_result(s)
        for s in ranking.rank([MUSHROOM_PASTA], RecommendationRequest(), {}, now=NOW)
    ]
    assert result.contains == ["dairy"]
    assert "vegetarian" in result.classifications["dietary_suitability"]


LENTIL_SOUP_CHOICE = make(
    20, "Red Lentil Soup", ["red lentils", "1 quart chicken or vegetable broth"], 40, "soup"
)
LENTIL_SOUP_VEGAN = make(21, "Lentil Dal", ["red lentils", "coconut milk"], 40, "curry")
CHICKEN_SOUP = make(22, "Chicken Soup", ["chicken", "carrot"], 40, "soup")


def test_excluding_a_food_type_uses_food_types_not_names() -> None:
    noodles = make(30, "Egg Noodle Soup", ["egg noodles", "broth"], 20, "soup")
    pierogies = make(31, "Pierogi Bake", ["potato pierogies", "onion"], 30, "roast")
    garnished = make(32, "Tomato Pasta", ["pasta", "tomato", "Parmesan, for serving"], 25, "pasta")
    creamy = make(33, "Cream Pasta", ["pasta", "heavy cream"], 25, "pasta")
    pool = [noodles, pierogies, garnished, creamy]

    no_egg = ranking.rank(pool, RecommendationRequest(excluded_ingredients=["egg"]), {}, now=NOW)
    # Pierogies may contain egg, but egg is only counted when it is listed.
    assert 30 not in [s.recipe.id for s in no_egg] and 31 in [s.recipe.id for s in no_egg]

    no_dairy = ranking.rank(
        pool, RecommendationRequest(excluded_ingredients=["dairy"], limit=5), {}, now=NOW
    )
    assert [s.recipe.id for s in no_dairy][-1] == 32  # garnish can be left out; ranks last
    assert 33 not in [s.recipe.id for s in no_dairy]
    result = ranking.to_result(no_dairy[-1])
    assert result.adapted_for == "no dairy"
    assert result.diet_swaps == ["leave out parmesan"]


def test_diet_and_food_type_exclusion_combine() -> None:
    omelette_ok = make(34, "Veg Frittata", ["eggs", "spinach"], 20, "other")
    req = RecommendationRequest(dietary=["vegetarian"], excluded_ingredients=["eggs"])
    assert ranking.rank([omelette_ok], req, {}, now=NOW) == []


def test_vegan_request_includes_stated_choices_after_exact_matches() -> None:
    req = RecommendationRequest(dietary=["vegan"])
    ranked = ranking.rank([CHICKEN_SOUP, LENTIL_SOUP_CHOICE, LENTIL_SOUP_VEGAN], req, {}, now=NOW)
    assert [s.recipe.id for s in ranked] == [21, 20]
    exact, adapted = (ranking.to_result(s) for s in ranked)
    assert exact.adapted_for is None and exact.diet_swaps == []
    assert adapted.adapted_for == "vegan"
    assert adapted.diet_swaps == ["use vegetable broth"]
    assert "vegan if you use vegetable broth" in adapted.reasons
    # As written the soup is still omnivore.
    assert adapted.classifications["dietary_suitability"] == ["omnivore"]
