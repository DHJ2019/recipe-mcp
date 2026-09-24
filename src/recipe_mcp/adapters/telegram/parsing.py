"""Deterministic classification of an incoming Telegram message.

The bot host uses this before involving the model so that ratings, corrections and
ordinal references resolve without a model call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from recipe_mcp.domain.models import Sentiment
from recipe_mcp.domain.references import resolve_ordinal
from recipe_mcp.domain.urls import extract_urls, is_supported_recipe_url
from recipe_mcp.services.feedback import parse_sentiment


class Intent(StrEnum):
    SAVE_URL = "save_url"
    SAVE_TEXT = "save_text"
    RATE = "rate"
    CORRECT = "correct"
    RECOMMEND = "recommend"
    PHOTO = "photo"
    UNKNOWN = "unknown"


@dataclass
class IncomingMessage:
    chat_id: int
    user_id: int
    message_id: int
    text: str = ""
    reply_to_message_id: int | None = None
    has_photo: bool = False
    reaction: str | None = None


@dataclass
class ParsedMessage:
    intent: Intent
    text: str
    urls: list[str] = field(default_factory=list)
    sentiment: Sentiment | None = None
    recipe_id: int | None = None
    total_minutes: int | None = None
    on_behalf_of_hint: str | None = None
    on_behalf_sentiment: Sentiment | None = None
    confidence: str = "deterministic"


_SAVE_RE = re.compile(r"^\s*(save|add|keep)\b", re.IGNORECASE)
_MINUTES_RE = re.compile(
    r"(?:takes?|is|about|around|roughly)\s+(?:about\s+)?(\d{1,3})\s*(?:min|minutes)", re.I
)
_CORRECT_HINT_RE = re.compile(
    r"\b(actually|not\b|isn'?t|wrong|should be|it'?s (?:a|an)\b|that one)", re.I
)
_BEHALF_RE = re.compile(
    r"\b([A-Z][a-z]+)\s+(didn'?t|did not|hated|wasn'?t (?:a )?fan|loved|liked)\b"
)
_BEHALF_SENTIMENT = {
    "loved": Sentiment.LOVE,
    "liked": Sentiment.LIKE,
}
_RECOMMEND_RE = re.compile(
    r"\b(what can we|what should|something|recommend|ideas?|dinner|lunch|cook"
    r"|make tonight|suggest)\b",
    re.I,
)


def parse_message(
    message: IncomingMessage,
    recipe_for_bot_message: dict[int, int] | None = None,
    recent_result_ids: list[int] | None = None,
) -> ParsedMessage:
    """Classify a message. ``recipe_for_bot_message`` maps the bot's own message ids to
    recipe ids (for reply-to ratings); ``recent_result_ids`` is the last result list."""
    text = (message.text or "").strip()
    reply_map = recipe_for_bot_message or {}
    recent = recent_result_ids or []

    if message.has_photo:
        return ParsedMessage(intent=Intent.PHOTO, text=text)

    replied_recipe = reply_map.get(message.reply_to_message_id or -1)
    behalf = _BEHALF_RE.search(text)
    behalf_name = behalf.group(1) if behalf else None
    behalf_sentiment: Sentiment | None = None
    own_text = text
    if behalf:
        verb = behalf.group(2).lower()
        behalf_sentiment = _BEHALF_SENTIMENT.get(verb, Sentiment.DISLIKE)
        own_text = (text[: behalf.start()] + text[behalf.end() :]).strip(" ,.;")
    sentiment = parse_sentiment(message.reaction or own_text)
    if sentiment is None and behalf_sentiment is not None:
        sentiment = behalf_sentiment
        own_sentiment: Sentiment | None = None
    else:
        own_sentiment = sentiment

    urls = extract_urls(text)
    if urls and is_supported_recipe_url(urls[0]):
        return ParsedMessage(intent=Intent.SAVE_URL, text=text, urls=urls)
    if urls and len(text) <= len(urls[0]) + 5:
        return ParsedMessage(intent=Intent.SAVE_URL, text=text, urls=urls)

    ordinal_recipe = resolve_ordinal(text, recent)
    target = replied_recipe or ordinal_recipe

    minutes = _MINUTES_RE.search(text)
    if target is not None and minutes:
        return ParsedMessage(
            intent=Intent.CORRECT, text=text, recipe_id=target, total_minutes=int(minutes.group(1))
        )
    if sentiment is not None and (target is not None or (recent and len(text) <= 80)):
        return ParsedMessage(
            intent=Intent.RATE,
            text=text,
            sentiment=own_sentiment,
            recipe_id=target or (recent[0] if recent else None),
            on_behalf_of_hint=behalf_name,
            on_behalf_sentiment=behalf_sentiment,
            confidence="deterministic" if target else "assumed_last_result",
        )
    if target is not None and _CORRECT_HINT_RE.search(text):
        return ParsedMessage(intent=Intent.CORRECT, text=text, recipe_id=target, confidence="model")
    if _SAVE_RE.search(text) and not _RECOMMEND_RE.search(text):
        return ParsedMessage(intent=Intent.SAVE_TEXT, text=text)
    if _RECOMMEND_RE.search(text) or text.endswith("?"):
        return ParsedMessage(intent=Intent.RECOMMEND, text=text, confidence="model")
    return ParsedMessage(intent=Intent.UNKNOWN, text=text, confidence="model")
