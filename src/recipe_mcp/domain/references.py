"""Resolve ordinal references ("the second one", "#3", "the last one") deterministically."""

from __future__ import annotations

import re

_ORDINALS: dict[str, int] = {
    "first": 1,
    "1st": 1,
    "one": 1,
    "second": 2,
    "2nd": 2,
    "two": 2,
    "third": 3,
    "3rd": 3,
    "three": 3,
    "fourth": 4,
    "4th": 4,
    "four": 4,
    "fifth": 5,
    "5th": 5,
    "five": 5,
}
_WORD_RE = re.compile(
    r"\b(?:the\s+)?(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|last)(?:\s+one)?\b",
    re.IGNORECASE,
)
_HASH_RE = re.compile(r"(?:#|number\s+|no\.?\s*)(\d{1,2})\b", re.IGNORECASE)
_BARE_RE = re.compile(r"^\s*(\d{1,2})\s*$")


def resolve_ordinal(text: str, recent_ids: list[int]) -> int | None:
    """Map a reference in ``text`` to a recipe id from the last shown result list.

    Returns ``None`` when there is no reference or it is out of range.
    """
    if not recent_ids:
        return None
    index: int | None = None
    if (m := _HASH_RE.search(text)) or (m := _BARE_RE.match(text)):
        index = int(m.group(1))
    elif m := _WORD_RE.search(text):
        word = m.group(1).lower()
        index = len(recent_ids) if word == "last" else _ORDINALS.get(word)
    if index is None or not 1 <= index <= len(recent_ids):
        return None
    return recent_ids[index - 1]
