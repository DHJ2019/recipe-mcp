from recipe_mcp.adapters.nyt.fetcher import extract_title


def test_prefers_og_title_then_title_tag() -> None:
    html = (
        '<html><head><meta property="og:title" content="Knife &amp; Fork"/>'
        "<title>Other</title></head></html>"
    )
    assert extract_title(html) == "Knife & Fork"
    assert extract_title("<title>\n  Plain   Title </title>") == "Plain Title"
    assert extract_title("<p>no title</p>") is None
