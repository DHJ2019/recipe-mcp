from recipe_mcp.domain.references import resolve_ordinal

IDS = [11, 22, 33]


def test_ordinal_words_and_numbers() -> None:
    assert resolve_ordinal("the second one", IDS) == 22
    assert resolve_ordinal("First please", IDS) == 11
    assert resolve_ordinal("let's do the last one", IDS) == 33
    assert resolve_ordinal("#3", IDS) == 33
    assert resolve_ordinal("number 2 looks good", IDS) == 22
    assert resolve_ordinal("2", IDS) == 22


def test_out_of_range_or_absent() -> None:
    assert resolve_ordinal("the fourth one", IDS) is None
    assert resolve_ordinal("#9", IDS) is None
    assert resolve_ordinal("something cozy", IDS) is None
    assert resolve_ordinal("the second one", []) is None
