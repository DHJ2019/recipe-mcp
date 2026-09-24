"""Household authorization: phone normalization and allowlist checks."""

from __future__ import annotations

import re

from recipe_mcp.domain.models import Member

_DIGITS = re.compile(r"\D")


def normalize_phone(raw: str) -> str | None:
    """Normalise a phone number to E.164 (``+`` followed by 8-15 digits).

    Accepts ``whatsapp:+1...`` prefixes, spaces, dashes and parentheses. Returns
    ``None`` when the input cannot be a valid number.
    """
    value = raw.strip().lower().removeprefix("whatsapp:")
    digits = _DIGITS.sub("", value)
    if not digits:
        return None
    if value.startswith("00"):
        digits = digits[2:]
    if not (8 <= len(digits) <= 15):
        return None
    return f"+{digits}"


def is_allowed(raw_number: str, allowlist: list[str]) -> bool:
    number = normalize_phone(raw_number)
    if number is None:
        return False
    normalized_allowlist = {normalize_phone(n) for n in allowlist}
    return number in normalized_allowlist


def resolve_member(raw_number: str, members: list[Member]) -> Member | None:
    number = normalize_phone(raw_number)
    if number is None:
        return None
    for member in members:
        if member.active and member.normalized_phone_number == number:
            return member
    return None
