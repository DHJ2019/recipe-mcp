"""Shared fixtures: isolated settings, fixture-backed NYT fetcher, fake model."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from recipe_mcp.adapters.nyt.fetcher import FetchError, FetchResult
from recipe_mcp.domain.urls import UrlKind, canonicalize_url, classify_url
from recipe_mcp.providers.fake import FakeModelClient
from recipe_mcp.services import fixtures
from recipe_mcp.services.container import AppContext, build_context
from recipe_mcp.settings import Settings, load_settings

FIXTURES = Path(__file__).parent / "fixtures"
NYT_FIXTURE_URL = "https://cooking.nytimes.com/recipes/1000001-test-lemon-chicken-thighs"


class FixtureFetcher:
    """Serves the same synthetic NYT page for any supported URL; records calls."""

    def __init__(self, html: str, redirects: dict[str, str] | None = None) -> None:
        self.html = html
        self.redirects = redirects or {}
        self.calls: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        target = self.redirects.get(url, url)
        if classify_url(target) != UrlKind.NYT_RECIPE:
            raise FetchError(f"unsupported recipe URL: {url}")
        canonical = canonicalize_url(target)
        return FetchResult(
            requested_url=url, final_url=target, canonical_url=canonical, html=self.html
        )


@pytest.fixture
def nyt_html() -> str:
    return (FIXTURES / "nyt_recipe.html").read_text(encoding="utf-8")


@pytest.fixture
def export_path() -> Path:
    return FIXTURES / "whatsapp_export_sample.txt"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(
        env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        model_provider="fake",
        temp_media_dir=tmp_path / "media",
        whatsapp_export_path=tmp_path / "export.txt",
        nyt_browser_profile_path=tmp_path / "profile",
        # Never read the developer's real .private/members.yaml from a test.
        members_path=tmp_path / "members.yaml",
    )


@pytest.fixture
def fetcher(nyt_html: str) -> FixtureFetcher:
    return FixtureFetcher(nyt_html, redirects={"https://nyti.ms/abc123": NYT_FIXTURE_URL})


class StubTitleFetcher:
    """Never touches the network; returns a title only for example.com."""

    def fetch_title(self, url: str) -> str | None:
        return "Knife Skills 101" if "example.com" in url else None


@pytest.fixture
def ctx(settings: Settings, fetcher: FixtureFetcher) -> Iterator[AppContext]:
    context = build_context(
        settings, fetcher=fetcher, title_fetcher=StubTitleFetcher(), model=FakeModelClient()
    )
    try:
        yield context
    finally:
        context.close()


@pytest.fixture
def seeded_ctx(ctx: AppContext) -> AppContext:
    fixtures.seed_demo(ctx)
    return ctx
