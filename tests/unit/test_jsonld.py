from recipe_mcp.adapters.nyt.jsonld import parse_iso_duration, parse_recipe_jsonld


def test_parse_iso_duration() -> None:
    assert parse_iso_duration("PT45M") == 45
    assert parse_iso_duration("PT1H30M") == 90
    assert parse_iso_duration("P1DT2H") == 1560
    assert parse_iso_duration("PT0M") is None
    assert parse_iso_duration("garbage") is None
    assert parse_iso_duration(None) is None


def test_parse_fixture_page(nyt_html: str) -> None:
    parsed = parse_recipe_jsonld(nyt_html)
    assert parsed is not None
    assert parsed.title == "Test Kitchen Lemon Chicken Thighs"
    assert parsed.total_minutes == 45
    assert parsed.hands_on_minutes == 15
    assert parsed.servings == "4 servings"
    assert parsed.cuisine == "Mediterranean"
    assert parsed.category == "dinner"
    assert len(parsed.ingredients) == 9
    assert (
        parsed.canonical_url
        == "https://cooking.nytimes.com/recipes/1000001-test-lemon-chicken-thighs"
    )


def test_total_time_derived_from_prep_and_cook_when_missing() -> None:
    html = """<script type="application/ld+json">{"@type":"Recipe","name":"X",
    "prepTime":"PT10M","cookTime":"PT20M","recipeIngredient":["a"]}</script>"""
    parsed = parse_recipe_jsonld(html)
    assert parsed is not None and parsed.total_minutes == 30


def test_no_recipe_returns_none() -> None:
    assert parse_recipe_jsonld("<html><body>nothing</body></html>") is None
    assert parse_recipe_jsonld('<script type="application/ld+json">{not json</script>') is None
    assert (
        parse_recipe_jsonld('<script type="application/ld+json">{"@type":"Article"}</script>')
        is None
    )
