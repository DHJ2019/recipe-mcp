"""Growing the vocabulary: Chinese and Vietnamese cuisines, and moving stored ``other``."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from recipe_mcp.cli import main as cli
from recipe_mcp.domain import taxonomy
from recipe_mcp.domain.models import Classification, FacetSource, RecommendationRequest
from recipe_mcp.domain.taxonomy import Facet
from recipe_mcp.services.container import AppContext, build_context
from recipe_mcp.settings import Settings
from tests.conftest import NYT_FIXTURE_URL, FixtureFetcher, StubTitleFetcher


@pytest.fixture
def agent_ctx(settings: Settings, fetcher: FixtureFetcher) -> Iterator[AppContext]:
    settings.model_provider = "none"
    context = build_context(settings, fetcher=fetcher, title_fetcher=StubTitleFetcher())
    try:
        yield context
    finally:
        context.close()


def save(ctx: AppContext, title: str, **classifications: str) -> int:
    result = ctx.ingestion.save_structured(
        title, ["chicken thigh", "rice"], classifications=dict(classifications) or None
    )
    assert result.recipe.id is not None
    return result.recipe.id


def facet_rows(ctx: AppContext, recipe_id: int, facet: Facet) -> list[Classification]:
    recipe = ctx.recipes.get(recipe_id)
    assert recipe is not None
    return [c for c in recipe.classifications if c.facet == facet]


def add_cuisine(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    grown = (*taxonomy.CUISINE_VALUES[:-1], value, taxonomy.OTHER)
    monkeypatch.setitem(taxonomy.CONTROLLED_VALUES, Facet.CUISINE, grown)


# -- the new cuisines ------------------------------------------------------


@pytest.mark.parametrize("cuisine", ["Chinese", "Vietnamese"])
def test_new_cuisines_are_stored_shown_and_filterable(agent_ctx: AppContext, cuisine: str) -> None:
    recipe_id = save(agent_ctx, f"{cuisine} Chicken Rice")
    result = agent_ctx.corrections.propose(
        recipe_id, {"cuisine": [cuisine], "dish_type": ["rice dish"]}
    )

    assert result.recipe.facet_values(Facet.CUISINE) == [cuisine.lower()]
    assert all(c.proposed_value is None for c in facet_rows(agent_ctx, recipe_id, Facet.CUISINE))
    found = agent_ctx.recommendation.recommend(RecommendationRequest(cuisine=cuisine.lower()))
    assert [r.recipe_id for r in found] == [recipe_id]


def test_nyt_chinese_cuisine_is_kept_as_a_parsed_hint(settings: Settings, nyt_html: str) -> None:
    settings.model_provider = "none"
    html = nyt_html.replace('"recipeCuisine": "Mediterranean"', '"recipeCuisine": "Chinese"')
    ctx = build_context(settings, fetcher=FixtureFetcher(html), title_fetcher=StubTitleFetcher())
    try:
        saved = ctx.ingestion.save_url(NYT_FIXTURE_URL)
        assert saved.recipe.facet_values(Facet.CUISINE) == ["chinese"]
        assert "Omnivore · Chinese · 45 minutes" in saved.confirmation()
    finally:
        ctx.close()


# -- a person's unknown value is kept ---------------------------------------


def test_person_correction_outside_the_vocabulary_keeps_their_word(agent_ctx: AppContext) -> None:
    recipe_id = save(agent_ctx, "Doro Wat")

    agent_ctx.corrections.correct(recipe_id, facet_corrections={"cuisine": ["Ethiopian"]})

    [row] = facet_rows(agent_ctx, recipe_id, Facet.CUISINE)
    assert row.value == "other" and row.proposed_value == "ethiopian"
    assert row.source == FacetSource.USER and row.user_confirmed


# -- refresh-taxonomy --------------------------------------------------------


def test_refresh_moves_other_onto_new_vocabulary(
    agent_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    proposed = save(agent_ctx, "Injera Platter")
    agent_ctx.corrections.propose(proposed, {"cuisine": ["Ethiopian"], "dish_type": ["Dumplings"]})
    corrected = save(agent_ctx, "Doro Wat")
    agent_ctx.corrections.correct(corrected, facet_corrections={"cuisine": ["ethiopian"]})
    untouched = save(agent_ctx, "Lemon Chicken", cuisine="mediterranean")

    before = agent_ctx.categorization.refresh_taxonomy(agent_ctx.household_id)
    assert before.moves == []
    assert before.remaining == {Facet.CUISINE: {"ethiopian": 2}, Facet.DISH_TYPE: {"dumplings": 1}}

    add_cuisine(monkeypatch, "ethiopian")
    preview = agent_ctx.categorization.refresh_taxonomy(agent_ctx.household_id)
    assert sorted((m.recipe_id, m.value) for m in preview.moves) == [
        (proposed, "ethiopian"),
        (corrected, "ethiopian"),
    ]
    assert preview.remaining == {Facet.DISH_TYPE: {"dumplings": 1}}
    assert facet_rows(agent_ctx, proposed, Facet.CUISINE)[0].value == "other"  # dry run

    applied = agent_ctx.categorization.refresh_taxonomy(agent_ctx.household_id, apply=True)
    assert len(applied.moves) == 2

    [model_row] = facet_rows(agent_ctx, proposed, Facet.CUISINE)
    assert model_row.value == "ethiopian" and model_row.proposed_value is None
    assert model_row.source == FacetSource.MODEL and not model_row.user_confirmed
    [user_row] = facet_rows(agent_ctx, corrected, Facet.CUISINE)
    assert user_row.value == "ethiopian" and user_row.user_confirmed
    assert user_row.source == FacetSource.USER
    assert agent_ctx.recipes.get(untouched).facet_values(Facet.CUISINE) == ["mediterranean"]  # type: ignore[union-attr]
    # The unknown dish type stays parked, and a second run changes nothing.
    assert facet_rows(agent_ctx, proposed, Facet.DISH_TYPE)[0].proposed_value == "dumplings"
    again = agent_ctx.categorization.refresh_taxonomy(agent_ctx.household_id, apply=True)
    assert again.moves == [] and again.remaining == {Facet.DISH_TYPE: {"dumplings": 1}}


def test_refresh_drops_other_when_the_value_is_already_stored(
    agent_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    recipe_id = save(agent_ctx, "Shared Plate")
    rows = [
        Classification(facet=Facet.CUISINE, value=v, source=FacetSource.MODEL, proposed_value=p)
        for v, p in (("other", "ethiopian"), ("ethiopian", None))
    ]
    add_cuisine(monkeypatch, "ethiopian")
    agent_ctx.recipes.replace_classifications(recipe_id, rows, keep_user=False)

    agent_ctx.categorization.refresh_taxonomy(agent_ctx.household_id, apply=True)

    assert [c.value for c in facet_rows(agent_ctx, recipe_id, Facet.CUISINE)] == ["ethiopian"]


def test_refresh_taxonomy_command(
    agent_ctx: AppContext, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    recipe_id = save(agent_ctx, "Injera Platter")
    agent_ctx.corrections.propose(recipe_id, {"cuisine": ["Ethiopian"], "dish_type": ["Dumplings"]})
    add_cuisine(monkeypatch, "ethiopian")
    monkeypatch.setattr(cli, "_ctx", lambda _settings: agent_ctx)

    args = cli.build_parser().parse_args(["refresh-taxonomy", "--dry-run"])
    assert args.fn(args, agent_ctx.settings) == 0

    out = capsys.readouterr().out
    assert f"{recipe_id}: Injera Platter — cuisine: other -> ethiopian" in out
    assert "would move 1 value(s)" in out
    assert "dish_type: dumplings (1)" in out
