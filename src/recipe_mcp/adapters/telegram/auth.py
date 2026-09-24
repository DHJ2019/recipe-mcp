"""Allowlist checks for the household group. Everything else is rejected and logged
without content."""

from __future__ import annotations

from dataclasses import dataclass

from recipe_mcp.settings import Settings


@dataclass(frozen=True)
class Authorization:
    allowed: bool
    reason: str


def authorize(user_id: int | None, chat_id: int | None, settings: Settings) -> Authorization:
    """A message is accepted only from an allowlisted user in the household group or in a
    private chat with that same user."""
    if user_id is None or user_id not in settings.allowed_telegram_user_ids:
        return Authorization(False, "user not allowlisted")
    if chat_id is None:
        return Authorization(False, "missing chat id")
    if chat_id == settings.telegram_group_chat_id:
        return Authorization(True, "household group")
    if chat_id == user_id:
        return Authorization(True, "private chat with allowlisted member")
    return Authorization(False, "chat not allowlisted")
