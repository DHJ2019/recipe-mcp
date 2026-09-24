"""Security: the link-title fetcher must never reach private or local addresses."""

import httpx
import pytest

from recipe_mcp.adapters.nyt.fetcher import TITLE_MAX_BYTES, HttpTitleFetcher, is_public_host

PUBLIC = {"example.com": ["93.184.215.14"], "evil-rebind.test": ["192.168.1.1"]}


def fake_resolve(host: str) -> list[str]:
    if host not in PUBLIC:
        raise OSError("no such host")
    return PUBLIC[host]


@pytest.mark.parametrize(
    ("host", "public"),
    [
        ("example.com", True),
        ("93.184.215.14", True),
        ("evil-rebind.test", False),  # a public-looking name that resolves to the LAN
        ("127.0.0.1", False),
        ("localhost", False),
        ("192.168.1.1", False),
        ("10.0.0.5", False),
        ("169.254.169.254", False),  # link-local / cloud metadata
        ("::1", False),
        ("fd00::1", False),
        ("", False),
        ("unknown.invalid", False),
    ],
)
def test_is_public_host(host: str, public: bool) -> None:
    assert is_public_host(host, fake_resolve) is public


def _fetcher(handler: httpx.MockTransport) -> HttpTitleFetcher:
    fetcher = HttpTitleFetcher(resolve=fake_resolve)
    fetcher._client = httpx.Client(
        transport=handler,
        follow_redirects=True,
        event_hooks={"request": [fetcher._check_request]},
    )
    return fetcher


def test_refuses_private_targets_and_private_redirects() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"location": "http://192.168.1.1/admin"})
        return httpx.Response(200, text="<title>Router admin</title>")

    fetcher = _fetcher(httpx.MockTransport(handler))
    assert fetcher.fetch_title("http://192.168.1.1/admin") is None
    assert fetcher.fetch_title("http://localhost:8080/") is None
    assert fetcher.fetch_title("https://example.com/redirect") is None
    assert calls == ["https://example.com/redirect"]  # the private hop was never requested


def test_reads_public_title_and_caps_download() -> None:
    big = "<html><head><title>Knife Skills</title></head><body>" + "x" * (TITLE_MAX_BYTES * 3)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=big)

    fetcher = _fetcher(httpx.MockTransport(handler))
    assert fetcher.fetch_title("https://example.com/post") == "Knife Skills"
