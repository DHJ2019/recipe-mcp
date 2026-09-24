"""A paywalled recipe still saves, because the chain hands over to the browser."""

from __future__ import annotations

from pathlib import Path

import pytest

from recipe_mcp.adapters.nyt.fetcher import ChainedRecipeFetcher, HttpRecipeFetcher
from recipe_mcp.domain.models import SourceType
from recipe_mcp.providers.fake import FakeModelClient
from recipe_mcp.services.container import build_context, build_recipe_fetcher
from recipe_mcp.settings import Settings
from tests.conftest import NYT_FIXTURE_URL, FixtureFetcher, StubTitleFetcher

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def paywalled_html() -> str:
    return (FIXTURES / "nyt_recipe_paywalled.html").read_text(encoding="utf-8")


def test_save_url_succeeds_through_the_fallback(
    settings: Settings, paywalled_html: str, nyt_html: str
) -> None:
    chain = ChainedRecipeFetcher(FixtureFetcher(paywalled_html), FixtureFetcher(nyt_html))
    ctx = build_context(
        settings, fetcher=chain, title_fetcher=StubTitleFetcher(), model=FakeModelClient()
    )
    try:
        result = ctx.ingestion.save_url(NYT_FIXTURE_URL)
        assert result.created
        assert result.recipe.source_type == SourceType.NYT
        assert result.recipe.title == "Test Kitchen Lemon Chicken Thighs"
        assert len(result.recipe.ingredients) == 9
    finally:
        ctx.close()


def test_without_a_browser_profile_the_fetcher_stays_plain_http(settings: Settings) -> None:
    assert isinstance(build_recipe_fetcher(settings), HttpRecipeFetcher)


def test_with_a_browser_profile_the_browser_sits_behind_http(settings: Settings) -> None:
    settings.nyt_browser_profile_path.mkdir(parents=True, exist_ok=True)
    fetcher = build_recipe_fetcher(settings)
    assert isinstance(fetcher, ChainedRecipeFetcher)
    assert isinstance(fetcher.primary, HttpRecipeFetcher)
