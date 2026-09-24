from recipe_mcp.domain.urls import (
    UrlKind,
    canonicalize_nyt_url,
    canonicalize_url,
    classify_url,
    extract_urls,
    is_supported_recipe_url,
    looks_like_url,
)


def test_canonicalize_strips_tracking_and_www() -> None:
    url = "https://www.cooking.nytimes.com/recipes/1000001-test-slug?utm_source=x&smid=share#top"
    assert canonicalize_url(url) == "https://cooking.nytimes.com/recipes/1000001-test-slug"


def test_canonicalize_upgrades_http_and_lowercases_slug() -> None:
    assert (
        canonicalize_nyt_url("http://cooking.nytimes.com/recipes/42-Some-Slug/")
        == "https://cooking.nytimes.com/recipes/42-some-slug"
    )


def test_non_nyt_url_returns_none_for_nyt_canonicalizer() -> None:
    assert canonicalize_nyt_url("https://example.com/recipes/1-x") is None


def test_generic_canonicalization_keeps_meaningful_query() -> None:
    assert (
        canonicalize_url("http://Example.com/a/?id=3&utm_medium=mail")
        == "https://example.com/a?id=3"
    )


def test_classify_url_kinds() -> None:
    assert classify_url("https://cooking.nytimes.com/recipes/1-x") == UrlKind.NYT_RECIPE
    assert classify_url("https://nyti.ms/abc") == UrlKind.NYT_SHORTLINK
    assert classify_url("https://cooking.nytimes.com/collections/1") == UrlKind.OTHER
    assert classify_url("https://example.com") == UrlKind.OTHER
    assert classify_url("not a url") == UrlKind.INVALID
    assert classify_url("ftp://cooking.nytimes.com/recipes/1-x") == UrlKind.INVALID


def test_extract_urls_trims_trailing_punctuation() -> None:
    text = "try https://cooking.nytimes.com/recipes/1-a. and https://example.com/x, ok?"
    assert extract_urls(text) == [
        "https://cooking.nytimes.com/recipes/1-a",
        "https://example.com/x",
    ]


def test_looks_like_url_and_supported() -> None:
    assert looks_like_url("  https://nyti.ms/abc ")
    assert not looks_like_url("tuna salad with tomato")
    assert is_supported_recipe_url("https://nyti.ms/abc")
    assert not is_supported_recipe_url("https://example.com/recipe")
