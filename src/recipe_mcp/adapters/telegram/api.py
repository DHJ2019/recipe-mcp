"""Minimal Telegram Bot API client over HTTPS (long polling, replies and editing them)."""

from __future__ import annotations

from typing import Any, Protocol

import httpx

TELEGRAM_API = "https://api.telegram.org"


class TelegramApiError(RuntimeError):
    pass


class TelegramApi(Protocol):
    def get_me(self) -> dict[str, Any]: ...

    def get_updates(self, offset: int | None, timeout: int) -> list[dict[str, Any]]: ...

    def send_message(
        self, chat_id: int | str, text: str, reply_to_message_id: int | None = None
    ) -> dict[str, Any]: ...

    def edit_message_text(self, chat_id: int | str, message_id: int, text: str) -> None: ...


class HttpTelegramApi:
    def __init__(self, token: str, client: httpx.Client | None = None) -> None:
        self._base = f"{TELEGRAM_API}/bot{token}"
        self._client = client or httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0))

    def _call(self, method: str, **params: Any) -> Any:
        try:
            response = self._client.post(f"{self._base}/{method}", json=params)
        except httpx.HTTPError as exc:
            raise TelegramApiError(f"{method}: {exc.__class__.__name__}") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise TelegramApiError(f"{method}: non-JSON response {response.status_code}") from exc
        if not data.get("ok"):
            raise TelegramApiError(f"{method}: {data.get('description', 'unknown error')}")
        return data["result"]

    def get_me(self) -> dict[str, Any]:
        result: dict[str, Any] = self._call("getMe")
        return result

    def get_updates(self, offset: int | None, timeout: int) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message", "message_reaction"],
        }
        if offset is not None:
            params["offset"] = offset
        result: list[dict[str, Any]] = self._call("getUpdates", **params)
        return result

    def send_message(
        self, chat_id: int | str, text: str, reply_to_message_id: int | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text[:4096],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_to_message_id is not None:
            params["reply_parameters"] = {
                "message_id": reply_to_message_id,
                "allow_sending_without_reply": True,
            }
        result: dict[str, Any] = self._call("sendMessage", **params)
        return result

    def edit_message_text(self, chat_id: int | str, message_id: int, text: str) -> None:
        """Replace the text of a message the bot sent (same HTML rules as sendMessage)."""
        self._call(
            "editMessageText",
            chat_id=chat_id,
            message_id=message_id,
            text=text[:4096],
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
