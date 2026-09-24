"""ChainedRecipeFetcher: when the authenticated browser is asked to take over."""

from __future__ import annotations

from pathlib import Path

import pytest

from recipe_mcp.adapters.nyt.fetcher import ChainedRecipeFetcher, FetchError, FetchResult
from recipe_mcp.adapters.nyt.jsonld import has_usable_recipe
from tests.conftest import NYT_FIXTURE_URL, FixtureFetcher

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def paywalled_html() -> str:
    return (FIXTURES / "nyt_recipe_paywalled.html").read_text(encoding="utf-8")


class FailingFetcher:
    """Stands in for HTTP hitting the paywall."""

    def __init__(self, message: str = "NYT Cooking requires authentication") -> None:
        self.message = message
        self.calls: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        raise FetchError(self.message)


def test_paywalled_page_has_no_usable_recipe(paywalled_html: str, nyt_html: str) -> None:
    assert has_usable_recipe(nyt_html)
    assert not has_usable_recipe(paywalled_html)


def test_primary_result_is_used_when_the_page_is_complete(nyt_html: str) -> None:
    primary = FixtureFetcher(nyt_html)
    fallback = FixtureFetcher(nyt_html)
    result = ChainedRecipeFetcher(primary, fallback).fetch(NYT_FIXTURE_URL)
    assert result.html == nyt_html
    assert fallback.calls == [], "the browser must not run when HTTP already worked"


def test_falls_back_when_http_raises(nyt_html: str) -> None:
    primary = FailingFetcher()
    fallback = FixtureFetcher(nyt_html)
    seen: list[tuple[str, str]] = []
    chain = ChainedRecipeFetcher(primary, fallback, on_fallback=lambda u, r: seen.append((u, r)))
    result = chain.fetch(NYT_FIXTURE_URL)
    assert result.html == nyt_html
    assert fallback.calls == [NYT_FIXTURE_URL]
    assert seen and "authentication" in seen[0][1]


def test_falls_back_when_the_page_is_paywalled(paywalled_html: str, nyt_html: str) -> None:
    primary = FixtureFetcher(paywalled_html)
    fallback = FixtureFetcher(nyt_html)
    result = ChainedRecipeFetcher(primary, fallback).fetch(NYT_FIXTURE_URL)
    assert result.html == nyt_html
    assert fallback.calls == [NYT_FIXTURE_URL]


def test_both_failing_reports_both_reasons() -> None:
    chain = ChainedRecipeFetcher(FailingFetcher(), FailingFetcher("no browser profile"))
    with pytest.raises(FetchError) as exc:
        chain.fetch(NYT_FIXTURE_URL)
    message = str(exc.value)
    assert "requires authentication" in message
    assert "no browser profile" in message
