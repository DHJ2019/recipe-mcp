"""Telegram long-polling host.

Deterministic intents (NYT links, reply-to ratings, ordinal references, time
corrections, photos) are handled here without any model. Everything else goes to
the brain (a headless Claude Code run) which talks to the same store through MCP.
The bot only ever replies to a message; it never initiates.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from html import escape
from typing import Any

from recipe_mcp.adapters.telegram.api import TelegramApi, TelegramApiError
from recipe_mcp.adapters.telegram.auth import authorize
from recipe_mcp.adapters.telegram.composer import TELEGRAM_MAX_CHARS, format_confirmation
from recipe_mcp.adapters.telegram.parsing import IncomingMessage, Intent, parse_message
from recipe_mcp.domain.models import Member, Sentiment
from recipe_mcp.providers.agent_brain import Brain, BrainRequest
from recipe_mcp.services.container import AppContext
from recipe_mcp.services.corrections import CorrectionError
from recipe_mcp.services.ingestion import IngestionError

log = logging.getLogger("recipe_mcp.telegram")

HISTORY_TURNS = 10
HISTORY_MINUTES = 30
RESULTS_TTL_HOURS = 12
POLL_TIMEOUT_SECONDS = 30
STARTUP_RETRY_INITIAL_SECONDS = 2
STARTUP_RETRY_MAX_SECONDS = 30


def _expires(minutes: int = 0, hours: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(minutes=minutes, hours=hours)).isoformat()


class TelegramHost:
    def __init__(
        self,
        ctx: AppContext,
        api: TelegramApi,
        brain: Brain,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.ctx = ctx
        self.api = api
        self.brain = brain
        self._sleep = sleep
        self.offset: int | None = None

    # -- polling loop -----------------------------------------------------

    def wait_for_telegram(self) -> dict[str, Any]:
        """Call ``getMe`` until it succeeds, backing off between attempts.

        At boot the daemon can start before DNS or the network is ready. Retrying here
        keeps the host alive instead of exiting and waiting for launchd to relaunch it.
        """
        delay = STARTUP_RETRY_INITIAL_SECONDS
        attempt = 1
        while True:
            try:
                return self.api.get_me()
            except TelegramApiError as exc:
                log.warning(
                    "telegram not reachable yet (attempt %d): %s; retrying in %ds",
                    attempt,
                    exc,
                    delay,
                )
                self._sleep(delay)
                delay = min(delay * 2, STARTUP_RETRY_MAX_SECONDS)
                attempt += 1

    def run_forever(self) -> None:
        me = self.wait_for_telegram()
        log.info("telegram host started as @%s (brain=%s)", me.get("username"), self.brain.name)
        while True:
            try:
                self.poll_once()
            except TelegramApiError as exc:
                log.warning("telegram api error: %s", exc)
                self._sleep(5)
            except Exception:  # pragma: no cover - keep the daemon alive
                log.exception("unhandled error in poll loop")
                self._sleep(5)

    def poll_once(self) -> int:
        updates = self.api.get_updates(self.offset, POLL_TIMEOUT_SECONDS)
        for update in updates:
            self.offset = int(update["update_id"]) + 1
            self.handle_update(update)
        return len(updates)

    # -- update handling --------------------------------------------------

    def handle_update(self, update: dict[str, Any]) -> str | None:
        """Process one update and return the reply text that was sent (or ``None``)."""
        incoming = self._incoming(update)
        if incoming is None:
            return None
        auth = authorize(incoming.user_id, incoming.chat_id, self.ctx.settings)
        if not auth.allowed:
            log.info("rejected message in chat %s: %s", incoming.chat_id, auth.reason)
            return None
        member = self.ctx.members.by_telegram_id(incoming.user_id)
        reply = self._respond(incoming, member)
        if reply is None:
            return None
        text, recipe_ids = reply
        sent = self._send(incoming.chat_id, text, incoming.message_id)
        if recipe_ids:
            self._remember_results(incoming.chat_id, recipe_ids, sent.get("message_id"))
        self._remember_turn(incoming.chat_id, incoming.text, text)
        return text

    def _incoming(self, update: dict[str, Any]) -> IncomingMessage | None:
        if "message_reaction" in update:
            r = update["message_reaction"]
            emojis = [
                e.get("emoji", "") for e in r.get("new_reaction", []) if e.get("type") == "emoji"
            ]
            if not emojis:
                return None
            return IncomingMessage(
                chat_id=int(r["chat"]["id"]),
                user_id=int(r.get("user", {}).get("id", 0)),
                message_id=int(r["message_id"]),
                reply_to_message_id=int(r["message_id"]),
                reaction=emojis[0],
            )
        message = update.get("message")
        if not message or "from" not in message:
            return None
        return IncomingMessage(
            chat_id=int(message["chat"]["id"]),
            user_id=int(message["from"]["id"]),
            message_id=int(message["message_id"]),
            text=message.get("text") or message.get("caption") or "",
            reply_to_message_id=(message.get("reply_to_message") or {}).get("message_id"),
            has_photo=bool(message.get("photo")),
        )

    def _respond(
        self, incoming: IncomingMessage, member: Member | None
    ) -> tuple[str, list[int]] | None:
        chat = str(incoming.chat_id)
        recent_ids, message_map = self._recent_state(chat)
        parsed = parse_message(incoming, message_map, recent_ids)
        member_id = member.id if member else None
        display = member.display_name if member else "someone"

        if parsed.intent == Intent.SAVE_URL:
            try:
                result = self.ctx.ingestion.save_url(parsed.urls[0], member_id=member_id)
            except IngestionError as exc:
                return f"Couldn't save that link: {escape(str(exc))}", []
            ids = [result.recipe.id] if result.recipe.id else []
            return format_confirmation(result.confirmation()), ids

        if parsed.intent == Intent.RATE and parsed.recipe_id:
            if member_id is None:
                return "I don't know which member you are; ask the household admin.", []
            ratings: list[tuple[int, Sentiment, int | None]] = []
            if parsed.sentiment is not None:
                ratings.append((member_id, parsed.sentiment, None))
            if parsed.on_behalf_of_hint and parsed.on_behalf_sentiment is not None:
                other = self.ctx.members.by_name(self.ctx.household_id, parsed.on_behalf_of_hint)
                if other and other.id and other.id != member_id:
                    ratings.append((other.id, parsed.on_behalf_sentiment, member_id))
            if not ratings:
                return self._ask_brain(chat, incoming, member, display, recent_ids)
            noted: list[str] = []
            verdict = ""
            for subject_id, sentiment, reported_by in ratings:
                try:
                    summary = self.ctx.feedback_service.rate(
                        parsed.recipe_id, subject_id, sentiment, reported_by_member_id=reported_by
                    )
                except LookupError as exc:
                    return escape(str(exc)), []
                who = self.ctx.members.get(subject_id)
                noted.append(f"{who.display_name if who else display} {sentiment.value}s")
                verdict = summary.household_verdict.replace("_", " ")
            recipe = self.ctx.recipes.get(parsed.recipe_id)
            title = recipe.title if recipe else f"recipe {parsed.recipe_id}"
            return f"Noted: {', '.join(noted)} <b>{escape(title)}</b> ({verdict}).", []

        if parsed.intent == Intent.CORRECT and parsed.total_minutes and parsed.recipe_id:
            try:
                corrected = self.ctx.corrections.correct(
                    parsed.recipe_id,
                    field_updates={"total_minutes": parsed.total_minutes},
                    member_id=member_id,
                )
            except CorrectionError as exc:
                return escape(str(exc)), []
            title = escape(corrected.recipe.title)
            return f"Updated <b>{title}</b>: {parsed.total_minutes} minutes.", []

        if parsed.intent == Intent.PHOTO:
            return "Photo input arrives in a later stage; describe what you have for now.", []

        return self._ask_brain(chat, incoming, member, display, recent_ids)

    def _ask_brain(
        self,
        chat: str,
        incoming: IncomingMessage,
        member: Member | None,
        display: str,
        recent_ids: list[int],
    ) -> tuple[str, list[int]]:
        history = self._history(chat)
        request = BrainRequest(
            chat_id=chat,
            member_key=member.member_key if member else None,
            display_name=display,
            text=incoming.text,
            history=history[-HISTORY_TURNS:],
            recent_result_ids=recent_ids,
        )
        reply = self.brain.reply(request)
        if reply.error or not reply.text.strip():
            log.warning("brain failed: %s", reply.error)
            return "Sorry, I couldn't work that out just now. Try again in a moment.", []
        return escape(reply.text)[:TELEGRAM_MAX_CHARS], reply.recipe_ids

    # -- state and sending ------------------------------------------------

    def _send(self, chat_id: int, text: str, reply_to: int) -> dict[str, Any]:
        try:
            return self.api.send_message(chat_id, text[:TELEGRAM_MAX_CHARS], reply_to)
        except TelegramApiError as exc:
            log.warning("send failed: %s", exc)
            return {}

    def _recent_state(self, chat: str) -> tuple[list[int], dict[int, int]]:
        state = self.ctx.pending.get(chat, "recent_results") or {}
        raw_ids = state.get("ids")
        raw_messages = state.get("messages")
        ids = [int(i) for i in raw_ids] if isinstance(raw_ids, list) else []
        messages = (
            {int(k): int(v) for k, v in raw_messages.items()}
            if isinstance(raw_messages, dict)
            else {}
        )
        return ids, messages

    def _history(self, chat: str) -> list[tuple[str, str]]:
        state = self.ctx.pending.get(chat, "turn_history") or {}
        raw = state.get("turns")
        if not isinstance(raw, list):
            return []
        return [(str(t[0]), str(t[1])) for t in raw if isinstance(t, list) and len(t) == 2]

    def _remember_results(self, chat_id: int, ids: list[int], bot_message_id: int | None) -> None:
        chat = str(chat_id)
        _, existing = self._recent_state(chat)
        messages: dict[str, int] = {str(k): v for k, v in existing.items()}
        if bot_message_id is not None and ids:
            messages[str(bot_message_id)] = ids[0]
        self.ctx.pending.put(
            chat,
            "recent_results",
            {"ids": ids, "messages": messages},
            _expires(hours=RESULTS_TTL_HOURS),
        )

    def _remember_turn(self, chat_id: int, user_text: str, bot_text: str) -> None:
        chat = str(chat_id)
        turns: list[list[str]] = [[r, t] for r, t in self._history(chat)]
        if user_text:
            turns.append(["user", user_text[:500]])
        turns.append(["assistant", bot_text[:500]])
        self.ctx.pending.put(
            chat,
            "turn_history",
            {"turns": turns[-HISTORY_TURNS:]},
            _expires(minutes=HISTORY_MINUTES),
        )
