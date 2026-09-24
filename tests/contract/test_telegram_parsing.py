"""Telegram message and reply parsing contract (deterministic, no model)."""

from __future__ import annotations

from recipe_mcp.adapters.telegram.composer import (
    TELEGRAM_MAX_CHARS,
    format_confirmation,
    format_recommendations,
)
from recipe_mcp.adapters.telegram.parsing import IncomingMessage, Intent, parse_message
from recipe_mcp.domain.models import RecipeStatus, RecommendationResult, Sentiment

BOT_MESSAGES = {900: 7, 901: 8}
RECENT = [7, 8, 9]


def msg(text: str = "", reply_to: int | None = None, **kw: object) -> IncomingMessage:
    return IncomingMessage(
        chat_id=-1, user_id=1, message_id=1, text=text, reply_to_message_id=reply_to, **kw
    )  # type: ignore[arg-type]


def test_nyt_link_is_a_save() -> None:
    p = parse_message(
        msg("https://cooking.nytimes.com/recipes/1-x?smid=share"), BOT_MESSAGES, RECENT
    )
    assert p.intent == Intent.SAVE_URL and p.urls


def test_reply_rating_uses_reply_to_message() -> None:
    p = parse_message(msg("👍", reply_to=901), BOT_MESSAGES, RECENT)
    assert p.intent == Intent.RATE and p.recipe_id == 8 and p.sentiment == Sentiment.LIKE
    r = parse_message(msg("", reply_to=900, reaction="❤️"), BOT_MESSAGES, RECENT)
    assert r.intent == Intent.RATE and r.recipe_id == 7 and r.sentiment == Sentiment.LOVE


def test_ordinal_rating_and_on_behalf_hint() -> None:
    p = parse_message(msg("we loved the second one"), BOT_MESSAGES, RECENT)
    assert p.intent == Intent.RATE and p.recipe_id == 8 and p.sentiment == Sentiment.LOVE
    q = parse_message(msg("I liked it but Sam didn't"), BOT_MESSAGES, RECENT)
    assert q.intent == Intent.RATE and q.recipe_id == 7 and q.on_behalf_of_hint == "Sam"
    assert q.sentiment == Sentiment.LIKE and q.on_behalf_sentiment == Sentiment.DISLIKE
    assert q.confidence == "assumed_last_result"
    r = parse_message(msg("Sam loved it"), BOT_MESSAGES, RECENT)
    assert r.sentiment is None and r.on_behalf_sentiment == Sentiment.LOVE


def test_time_correction_by_reply_and_by_ordinal() -> None:
    p = parse_message(
        msg("That one takes about 30 minutes, not unknown.", reply_to=900), BOT_MESSAGES, RECENT
    )
    assert p.intent == Intent.CORRECT and p.recipe_id == 7 and p.total_minutes == 30
    q = parse_message(msg("the first one is actually Thai"), BOT_MESSAGES, RECENT)
    assert q.intent == Intent.CORRECT and q.recipe_id == 7 and q.confidence == "model"


def test_save_text_recommend_photo_unknown() -> None:
    assert (
        parse_message(msg("Save this: tuna salad with tomato"), {}, []).intent == Intent.SAVE_TEXT
    )
    assert parse_message(msg("Something cozy under 45 minutes?"), {}, []).intent == Intent.RECOMMEND
    assert parse_message(msg("We have salmon, what can we make"), {}, []).intent == Intent.RECOMMEND
    assert parse_message(msg("", has_photo=True), {}, []).intent == Intent.PHOTO
    assert parse_message(msg("lol"), {}, []).intent == Intent.UNKNOWN


def _result(i: int, reason_len: int = 20) -> RecommendationResult:
    return RecommendationResult(
        recipe_id=i,
        title=f"Recipe <{i}>",
        total_minutes=30,
        status=RecipeStatus.COMPLETE,
        classifications={"dietary_suitability": ["vegan"], "cuisine": ["thai"]},
        ingredients_available=["a"],
        ingredients_missing=["b"],
        reasons=["x" * reason_len],
        score=1.0,
        source_url=f"https://cooking.nytimes.com/recipes/{i}-r",
    )


def test_composer_escapes_links_and_fits_limit() -> None:
    text = format_recommendations([_result(1), _result(2), _result(3)])
    assert '<a href="https://cooking.nytimes.com/recipes/1-r">Recipe &lt;1&gt;</a>' in text
    assert "vegan · thai" in text and "missing: b" in text
    huge = format_recommendations([_result(i, 3000) for i in range(1, 4)])
    assert (
        len(huge) <= TELEGRAM_MAX_CHARS and "Recipe &lt;3&gt;" in huge
    )  # reasons truncated, not recipes
    assert "Nothing in the collection" in format_recommendations([])
    mixed = _result(4).model_copy(
        update={
            "classifications": {"dietary_suitability": ["omnivore"], "cuisine": ["indonesian"]},
            "contains": ["meat", "shellfish", "egg"],
        }
    )
    assert "omnivore (meat, shellfish, egg) · indonesian" in format_recommendations([mixed])
    adapted = _result(5).model_copy(
        update={
            "classifications": {"dietary_suitability": ["omnivore"]},
            "contains": ["meat"],
            "adapted_for": "vegan",
            "diet_swaps": ["use vegetable broth"],
            "reasons": ["vegan if you use vegetable broth", "40 minutes"],
        }
    )
    text = format_recommendations([adapted])
    assert "vegan if you use vegetable broth" in text
    assert text.count("vegan if you") == 1  # not repeated in the reasons line
    conf = format_confirmation("Saved: Thai Pumpkin Soup\nVegan · Thai · soup? · 40 minutes")
    assert conf.startswith("<b>Saved: Thai Pumpkin Soup</b>") and "Reply to this message" in conf
