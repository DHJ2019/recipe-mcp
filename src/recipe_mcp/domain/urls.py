"""URL detection, validation and canonicalization (deterministic, no network)."""

from __future__ import annotations

import re
from enum import StrEnum
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

NYT_COOKING_HOST = "cooking.nytimes.com"
NYT_SHORTLINK_HOSTS: frozenset[str] = frozenset({"nyti.ms"})
_NYT_RECIPE_PATH = re.compile(r"^/recipes/(?P<id>\d+)(?:-(?P<slug>[a-z0-9-]+))?/?$", re.IGNORECASE)
_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
_TRACKING_PREFIXES = ("utm_", "smid", "smtyp", "fbclid", "gclid", "mc_", "ref", "campaign")


class UrlKind(StrEnum):
    NYT_RECIPE = "nyt_recipe"
    NYT_SHORTLINK = "nyt_shortlink"
    OTHER = "other"
    INVALID = "invalid"


def extract_urls(text: str) -> list[str]:
    """All http(s) URLs in a block of text, in order, with trailing punctuation removed."""
    found: list[str] = []
    for match in _URL_IN_TEXT.finditer(text):
        url = match.group(0).rstrip(".,;:!?")
        found.append(url)
    return found


def looks_like_url(text: str) -> bool:
    stripped = text.strip()
    return bool(_URL_IN_TEXT.fullmatch(stripped))


def classify_url(url: str) -> UrlKind:
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return UrlKind.INVALID
    host = parts.hostname or ""
    if host in NYT_SHORTLINK_HOSTS:
        return UrlKind.NYT_SHORTLINK
    if host.removeprefix("www.") == NYT_COOKING_HOST and _NYT_RECIPE_PATH.match(parts.path):
        return UrlKind.NYT_RECIPE
    return UrlKind.OTHER


def canonicalize_nyt_url(url: str) -> str | None:
    """Canonical form for an NYT Cooking recipe URL, or ``None`` if it is not one."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").removeprefix("www.")
    if host != NYT_COOKING_HOST:
        return None
    match = _NYT_RECIPE_PATH.match(parts.path)
    if not match:
        return None
    recipe_id = match.group("id")
    slug = (match.group("slug") or "").lower()
    path = f"/recipes/{recipe_id}-{slug}" if slug else f"/recipes/{recipe_id}"
    return f"https://{NYT_COOKING_HOST}{path}"


def canonicalize_url(url: str) -> str:
    """Generic canonical form: https where possible, no tracking params, no fragment."""
    nyt = canonicalize_nyt_url(url)
    if nyt:
        return nyt
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not k.lower().startswith(_TRACKING_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    scheme = "https" if parts.scheme in {"http", "https"} else parts.scheme
    return urlunsplit((scheme, host, path, urlencode(query), ""))


def is_supported_recipe_url(url: str) -> bool:
    return classify_url(url) in {UrlKind.NYT_RECIPE, UrlKind.NYT_SHORTLINK}
