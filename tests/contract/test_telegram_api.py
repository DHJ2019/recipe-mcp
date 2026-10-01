"""Call shapes the Telegram host sends to the Bot API."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from recipe_mcp.adapters.telegram.api import HttpTelegramApi, TelegramApiError


def api_recording(calls: list[tuple[str, dict[str, Any]]], ok: bool = True) -> HttpTelegramApi:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path.rsplit("/", 1)[-1], json.loads(request.content)))
        if not ok:
            return httpx.Response(
                400, json={"ok": False, "description": "Bad Request: message is not modified"}
            )
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 501}})

    return HttpTelegramApi("123:abc", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_edit_message_text_call_shape() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    api_recording(calls).edit_message_text(-100777, 501, "<b>Saved: Soup</b>\n" + "x" * 5000)

    assert len(calls) == 1
    method, payload = calls[0]
    assert method == "editMessageText"
    assert payload["chat_id"] == -100777 and payload["message_id"] == 501
    assert payload["parse_mode"] == "HTML" and payload["disable_web_page_preview"] is True
    assert payload["text"].startswith("<b>Saved: Soup</b>") and len(payload["text"]) == 4096
    assert set(payload) == {
        "chat_id",
        "message_id",
        "text",
        "parse_mode",
        "disable_web_page_preview",
    }


def test_edit_message_text_error_raises() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    with pytest.raises(TelegramApiError, match="not modified"):
        api_recording(calls, ok=False).edit_message_text(1, 2, "same")


def test_send_message_returns_the_message_id_used_for_edits() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    sent = api_recording(calls).send_message(-100777, "hello", 10)
    assert sent["message_id"] == 501
    assert calls[0][0] == "sendMessage" and calls[0][1]["reply_parameters"]["message_id"] == 10
