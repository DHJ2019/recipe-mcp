"""Authenticated NYT Cooking fetch through a dedicated Playwright profile (Stage 2).

The HTTP fetcher handles anything NYT serves anonymously. Paywalled recipes need a
signed-in browser, so this module drives a *persistent* Chromium profile that lives at
``NYT_BROWSER_PROFILE_PATH`` under ``.private/``. Sign-in happens once, by hand, through
:func:`login`; no password is ever stored or read by this code, and cookie values are
never returned, printed or logged -- only names and expiry timestamps.

Playwright is an optional dependency (``uv sync --extra browser``); every entry point
degrades to a clear message when it is absent, so the offline test suite never needs it.
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from recipe_mcp.adapters.nyt.fetcher import USER_AGENT, FetchError, FetchResult
from recipe_mcp.domain.urls import UrlKind, canonicalize_url, classify_url

# Document navigation is restricted to these hosts (SPEC section 20). Sub-resources
# (fonts, images, scripts on nyt CDNs) are left alone; only page loads are policed.
APPROVED_FETCH_HOSTS: frozenset[str] = frozenset({"cooking.nytimes.com"})
APPROVED_LOGIN_HOSTS: frozenset[str] = frozenset(
    {
        "cooking.nytimes.com",
        "www.nytimes.com",
        "nytimes.com",
        "myaccount.nytimes.com",
        "accounts.nytimes.com",
    }
)

#: Cookie names that indicate a usable NYT session. Values are never read.
SESSION_COOKIE_NAMES: frozenset[str] = frozenset({"NYT-S", "SIDNY", "NYT-MPS"})

LOGIN_START_URL = "https://cooking.nytimes.com/"
DEFAULT_TIMEOUT_SECONDS = 30.0
LOGIN_TIMEOUT_SECONDS = 300.0


class PlaywrightUnavailableError(FetchError):
    """Playwright (or its browser binary) is not installed."""


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.").lower()


def _sync_playwright() -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise PlaywrightUnavailableError(
            "playwright is not installed; run `make nyt-login`, which syncs the "
            "`browser` extra and downloads Chromium"
        ) from exc
    return sync_playwright


@dataclass(frozen=True)
class SessionStatus:
    """What we can say about the stored NYT session without revealing it."""

    ok: bool
    detail: str
    expires_at: datetime | None = None
    cookie_names: tuple[str, ...] = ()

    @property
    def days_remaining(self) -> int | None:
        if self.expires_at is None:
            return None
        return (self.expires_at - datetime.now(UTC)).days

    def summary(self) -> str:
        if not self.ok:
            return self.detail
        if self.expires_at is None:
            return f"{self.detail} (session cookie, expires when the browser profile is cleared)"
        days = self.days_remaining
        when = self.expires_at.date().isoformat()
        return f"{self.detail} (expires {when}, {days} day(s) away)"


def _session_from_cookies(cookies: list[dict[str, Any]]) -> SessionStatus:
    """Summarise cookies by name and expiry only. Values are deliberately ignored."""
    matched = [c for c in cookies if str(c.get("name", "")) in SESSION_COOKIE_NAMES]
    if not matched:
        return SessionStatus(ok=False, detail="no NYT session cookie in the profile")
    expiries = [
        datetime.fromtimestamp(float(c["expires"]), tz=UTC)
        for c in matched
        if isinstance(c.get("expires"), int | float) and float(c["expires"]) > 0
    ]
    names = tuple(sorted(str(c["name"]) for c in matched))
    earliest = min(expiries) if expiries else None
    if earliest is not None and earliest <= datetime.now(UTC):
        return SessionStatus(
            ok=False,
            detail="NYT session has expired; run `make nyt-login` again",
            expires_at=earliest,
            cookie_names=names,
        )
    return SessionStatus(
        ok=True, detail="NYT session present", expires_at=earliest, cookie_names=names
    )


def session_status(profile_path: Path) -> SessionStatus:
    """Report on the stored session. Never raises; doctor calls this on every run."""
    if not profile_path.exists():
        return SessionStatus(
            ok=False, detail=f"no browser profile at {profile_path}; run `make nyt-login`"
        )
    try:
        sync_playwright = _sync_playwright()
    except PlaywrightUnavailableError as exc:
        return SessionStatus(ok=False, detail=str(exc))
    try:
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(str(profile_path), headless=True)
            try:
                return _session_from_cookies(list(context.cookies()))
            finally:
                context.close()
    except Exception as exc:  # pragma: no cover - live path
        return SessionStatus(
            ok=False,
            detail=f"could not read the browser profile ({exc.__class__.__name__}); "
            "is a login window still open?",
        )


def login(profile_path: Path, timeout_seconds: float = LOGIN_TIMEOUT_SECONDS) -> SessionStatus:
    """Open a headed browser for a manual sign-in; close it once the session appears.

    Nothing is typed, captured or stored by this function: the person signs in and the
    cookie lands in the persistent profile directory.
    """
    profile_path.mkdir(parents=True, exist_ok=True)
    sync_playwright = _sync_playwright()
    deadline = time.monotonic() + timeout_seconds
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(profile_path), headless=False, user_agent=USER_AGENT
        )
        try:
            _restrict_navigation(context, APPROVED_LOGIN_HOSTS)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(LOGIN_START_URL, wait_until="domcontentloaded")
            while time.monotonic() < deadline:
                status = _session_from_cookies(list(context.cookies()))
                if status.ok:
                    return status
                time.sleep(2.0)
            return SessionStatus(
                ok=False, detail="timed out waiting for sign-in; no session cookie appeared"
            )
        finally:
            context.close()


def _restrict_navigation(context: Any, approved: frozenset[str]) -> None:
    """Abort document loads outside the approved hosts; leave sub-resources alone."""

    def handler(route: Any, request: Any) -> None:
        if request.resource_type == "document" and _host(request.url) not in approved:
            route.abort()
        else:
            route.continue_()

    context.route("**/*", handler)


@dataclass
class PlaywrightRecipeFetcher:
    """:class:`RecipeFetcher` backed by the signed-in profile. Same contract as HTTP."""

    profile_path: Path
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    headless: bool = True

    def fetch(self, url: str) -> FetchResult:
        if classify_url(url) not in {UrlKind.NYT_RECIPE, UrlKind.NYT_SHORTLINK}:
            raise FetchError(f"unsupported recipe URL: {url}")
        if not self.profile_path.exists():
            raise FetchError(
                f"no NYT browser profile at {self.profile_path}; run `make nyt-login` first"
            )
        sync_playwright = _sync_playwright()
        timeout_ms = int(self.timeout_seconds * 1000)
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                str(self.profile_path), headless=self.headless, user_agent=USER_AGENT
            )
            try:
                _restrict_navigation(context, APPROVED_FETCH_HOSTS)
                page = context.new_page()
                response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                # Mirror HttpRecipeFetcher: a 404 must not look like a paywall.
                status = int(response.status) if response is not None else 0
                if status in (401, 403):
                    raise FetchError("the stored NYT session is not signed in or has expired")
                if status >= 400:
                    raise FetchError(f"NYT Cooking returned HTTP {status}")
                final_url = str(page.url)
                if _host(final_url) not in APPROVED_FETCH_HOSTS:
                    raise FetchError(f"redirected to an unsupported location: {final_url}")
                if classify_url(final_url) != UrlKind.NYT_RECIPE:
                    raise FetchError(f"redirected to an unsupported location: {final_url}")
                # Absence of JSON-LD is reported by the caller's parse, not here.
                with contextlib.suppress(Exception):
                    page.wait_for_selector(
                        'script[type="application/ld+json"]', timeout=timeout_ms, state="attached"
                    )
                html = str(page.content())
            except FetchError:
                raise
            except Exception as exc:
                raise FetchError(
                    f"authenticated fetch failed for {url}: {exc.__class__.__name__}"
                ) from exc
            finally:
                context.close()
        return FetchResult(
            requested_url=url,
            final_url=final_url,
            canonical_url=canonicalize_url(final_url),
            html=html,
        )
