"""Telegram household group adapter: Bot API client, long-polling host, deterministic
parsing, allowlists and the 4,096-character composer. The brain is a headless Claude
Code run (see ``providers/agent_brain.py``)."""

from recipe_mcp.adapters.telegram.api import HttpTelegramApi, TelegramApi, TelegramApiError
from recipe_mcp.adapters.telegram.auth import Authorization, authorize
from recipe_mcp.adapters.telegram.composer import format_confirmation, format_recommendations
from recipe_mcp.adapters.telegram.host import TelegramHost
from recipe_mcp.adapters.telegram.parsing import (
    IncomingMessage,
    Intent,
    ParsedMessage,
    parse_message,
)

__all__ = [
    "Authorization",
    "HttpTelegramApi",
    "IncomingMessage",
    "Intent",
    "ParsedMessage",
    "TelegramApi",
    "TelegramApiError",
    "TelegramHost",
    "authorize",
    "format_confirmation",
    "format_recommendations",
    "parse_message",
]
