"""Fetch NYT Cooking pages over HTTP and validate the final URL after redirects.

The authenticated Playwright fallback in :mod:`recipe_mcp.adapters.nyt.browser`
implements the same :class:`RecipeFetcher` protocol, and
:class:`ChainedRecipeFetcher` puts the two in order, so ingestion does not change.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass
from html import unescape
from typing import Protocol

import httpx

from recipe_mcp.adapters.nyt.jsonld import has_usable_recipe
from recipe_mcp.domain.urls import UrlKind, canonicalize_url, classify_url

USER_AGENT = "recipe-mcp/0.1 (+personal household recipe assistant)"

log = logging.getLogger("recipe_mcp.nyt")


class FetchError(RuntimeError):
    pass


@dataclass
class FetchResult:
    requested_url: str
    final_url: str
    canonical_url: str
    html: str


class RecipeFetcher(Protocol):
    def fetch(self, url: str) -> FetchResult: ...


class TitleFetcher(Protocol):
    """Best-effort page title for unsupported links; returns ``None`` on any failure."""

    def fetch_title(self, url: str) -> str | None: ...


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_OG_TITLE_RE = re.compile(
    r"<meta[^>]+property=[\"']og:title[\"'][^>]+content=[\"']([^\"']+)[\"']", re.IGNORECASE
)


def extract_title(html: str) -> str | None:
    match = _OG_TITLE_RE.search(html) or _TITLE_RE.search(html)
    if not match:
        return None
    title = unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    return title[:200] or None


TITLE_MAX_BYTES = 200_000

Resolver = Callable[[str], list[str]]


class BlockedAddressError(httpx.HTTPError):
    """Raised when a link points at a private, loopback or otherwise non-public address."""


def _resolve(host: str) -> list[str]:
    return [str(info[4][0]) for info in socket.getaddrinfo(host, None)]


def is_public_host(host: str, resolve: Resolver = _resolve) -> bool:
    """True only when every address the host resolves to is a public internet address.

    Stops a shared link from making the Mac fetch pages on the home network (the router's
    admin page, other devices) or the Mac itself.
    """
    if not host:
        return False
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(a.split("%")[0]) for a in resolve(host)]
        except (OSError, ValueError):
            return False
    return bool(addresses) and all(a.is_global and not a.is_multicast for a in addresses)


class HttpTitleFetcher:
    """Best-effort page title for links to sites other than NYT Cooking.

    Every request, including each redirect hop, must go to a public address, and at most
    ``TITLE_MAX_BYTES`` of the page is read.
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
        resolve: Resolver = _resolve,
    ) -> None:
        self._resolve = resolve
        self._client = client or httpx.Client(
            follow_redirects=True,
            max_redirects=5,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            event_hooks={"request": [self._check_request]},
        )

    def _check_request(self, request: httpx.Request) -> None:
        if request.url.scheme not in {"http", "https"} or not is_public_host(
            request.url.host, self._resolve
        ):
            raise BlockedAddressError(f"refusing to fetch non-public address {request.url.host}")

    def fetch_title(self, url: str) -> str | None:
        try:
            with self._client.stream("GET", url) as response:
                if response.status_code >= 400:
                    return None
                body = b""
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) >= TITLE_MAX_BYTES:
                        break
                encoding = response.encoding or "utf-8"
        except httpx.HTTPError:
            return None
        return extract_title(body[:TITLE_MAX_BYTES].decode(encoding, errors="replace"))


class HttpRecipeFetcher:
    def __init__(self, client: httpx.Client | None = None, timeout: float = 20.0) -> None:
        self._client = client or httpx.Client(
            follow_redirects=True, timeout=timeout, headers={"User-Agent": USER_AGENT}
        )

    def fetch(self, url: str) -> FetchResult:
        kind = classify_url(url)
        if kind not in {UrlKind.NYT_RECIPE, UrlKind.NYT_SHORTLINK}:
            raise FetchError(f"unsupported recipe URL: {url}")
        try:
            response = self._client.get(url)
        except httpx.HTTPError as exc:
            raise FetchError(f"network error fetching {url}: {exc.__class__.__name__}") from exc
        final_url = str(response.url)
        if classify_url(final_url) != UrlKind.NYT_RECIPE:
            raise FetchError(f"redirected to an unsupported location: {final_url}")
        if response.status_code in (401, 403):
            raise FetchError("NYT Cooking requires authentication for this recipe")
        if response.status_code >= 400:
            raise FetchError(f"NYT Cooking returned HTTP {response.status_code}")
        return FetchResult(
            requested_url=url,
            final_url=final_url,
            canonical_url=canonicalize_url(final_url),
            html=response.text,
        )


class ChainedRecipeFetcher:
    """Cheap HTTP fetch first; authenticated browser only when the page is unusable.

    The fallback runs when HTTP fails outright (paywall, 401/403, network) *or* when it
    returns a page with no usable Recipe data, which is how NYT serves subscriber-only
    recipes to an anonymous client.
    """

    def __init__(
        self,
        primary: RecipeFetcher,
        fallback: RecipeFetcher,
        *,
        on_fallback: Callable[[str, str], None] | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self._on_fallback = on_fallback

    def fetch(self, url: str) -> FetchResult:
        try:
            result = self.primary.fetch(url)
        except FetchError as exc:
            return self._fall_back(url, str(exc))
        if has_usable_recipe(result.html):
            return result
        return self._fall_back(url, "no usable recipe data in the anonymous page")

    def _fall_back(self, url: str, reason: str) -> FetchResult:
        if self._on_fallback is not None:
            self._on_fallback(url, reason)
        log.info("falling back to the authenticated browser: %s", reason)
        try:
            return self.fallback.fetch(url)
        except FetchError as exc:
            raise FetchError(f"{reason}; authenticated fetch also failed: {exc}") from exc
