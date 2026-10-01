from recipe_mcp.domain.taxonomy import Facet, effort_for_minutes, normalize_value


def test_normalize_value_controlled_and_other() -> None:
    assert normalize_value(Facet.CUISINE, " Thai ") == ("thai", None)
    assert normalize_value(Facet.CUISINE, "Ethiopian") == ("other", "ethiopian")
    assert normalize_value(Facet.CUISINE, "Chinese") == ("chinese", None)
    assert normalize_value(Facet.CUISINE, "Vietnamese") == ("vietnamese", None)
    assert normalize_value(Facet.CHARACTER, "umami") == ("", "umami")
    assert normalize_value(Facet.PRIMARY_INGREDIENT, "Salmon") == ("salmon", None)


def test_effort_buckets() -> None:
    assert effort_for_minutes(None) is None
    assert effort_for_minutes(20) == "quick"
    assert effort_for_minutes(45) == "weeknight"
    assert effort_for_minutes(90) == "weekend"
    assert effort_for_minutes(200) == "project"
