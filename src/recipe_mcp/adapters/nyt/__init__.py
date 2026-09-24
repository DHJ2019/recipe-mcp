"""NYT Cooking import: HTTP JSON-LD first, authenticated browser as the fallback.

``browser`` is imported lazily by the container so Playwright stays optional.
"""

from recipe_mcp.adapters.nyt.fetcher import (
    ChainedRecipeFetcher,
    FetchError,
    FetchResult,
    HttpRecipeFetcher,
    HttpTitleFetcher,
    RecipeFetcher,
    TitleFetcher,
    extract_title,
)
from recipe_mcp.adapters.nyt.jsonld import ParsedRecipe, has_usable_recipe, parse_recipe_jsonld

__all__ = [
    "ChainedRecipeFetcher",
    "FetchError",
    "FetchResult",
    "HttpRecipeFetcher",
    "HttpTitleFetcher",
    "ParsedRecipe",
    "RecipeFetcher",
    "TitleFetcher",
    "extract_title",
    "has_usable_recipe",
    "parse_recipe_jsonld",
]
