"""Session reporting and URL guards for the authenticated NYT browser.

Playwright itself is never launched here: the offline suite must pass without the
``browser`` extra installed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from recipe_mcp.adapters.nyt.browser import (
    APPROVED_FETCH_HOSTS,
    PlaywrightRecipeFetcher,
    _host,
    _session_from_cookies,
    session_status,
)
from recipe_mcp.adapters.nyt.fetcher import FetchError


def _cookie(name: str, expires: float) -> dict[str, object]:
    return {"name": name, "value": "never-read", "domain": ".nytimes.com", "expires": expires}


def test_no_session_cookie() -> None:
    status = _session_from_cookies([_cookie("nyt-gdpr", 0)])
    assert not status.ok
    assert "no NYT session cookie" in status.detail


def test_valid_session_reports_expiry_without_values() -> None:
    later = (datetime.now(UTC) + timedelta(days=30)).timestamp()
    status = _session_from_cookies([_cookie("NYT-S", later), _cookie("nyt-gdpr", 0)])
    assert status.ok
    assert status.cookie_names == ("NYT-S",)
    assert status.days_remaining is not None and 28 <= status.days_remaining <= 30
    assert "never-read" not in status.summary(), "cookie values must never be surfaced"


def test_expired_session_is_reported_as_stale() -> None:
    past = (datetime.now(UTC) - timedelta(days=1)).timestamp()
    status = _session_from_cookies([_cookie("NYT-S", past)])
    assert not status.ok
    assert "expired" in status.detail


def test_session_only_cookie_has_no_expiry() -> None:
    status = _session_from_cookies([_cookie("SIDNY", -1)])
    assert status.ok and status.expires_at is None
    assert "session cookie" in status.summary()


def test_earliest_expiry_wins() -> None:
    soon = (datetime.now(UTC) + timedelta(days=2)).timestamp()
    later = (datetime.now(UTC) + timedelta(days=90)).timestamp()
    status = _session_from_cookies([_cookie("NYT-S", later), _cookie("SIDNY", soon)])
    assert status.days_remaining is not None and status.days_remaining <= 2


def test_missing_profile_never_raises(tmp_path: Path) -> None:
    status = session_status(tmp_path / "absent")
    assert not status.ok
    assert "nyt-login" in status.detail


def test_host_strips_www() -> None:
    assert _host("https://www.cooking.nytimes.com/recipes/1-x") == "cooking.nytimes.com"
    assert _host("https://evil.example.com/x") == "evil.example.com"
    assert _host("https://cooking.nytimes.com/recipes/1-x") in APPROVED_FETCH_HOSTS


def test_unsupported_url_is_rejected_before_launching_a_browser(tmp_path: Path) -> None:
    fetcher = PlaywrightRecipeFetcher(tmp_path)
    with pytest.raises(FetchError, match="unsupported recipe URL"):
        fetcher.fetch("https://example.com/recipes/nope")


def test_missing_profile_is_rejected_before_launching_a_browser(tmp_path: Path) -> None:
    fetcher = PlaywrightRecipeFetcher(tmp_path / "absent")
    with pytest.raises(FetchError, match="nyt-login"):
        fetcher.fetch("https://cooking.nytimes.com/recipes/1000001-test")
