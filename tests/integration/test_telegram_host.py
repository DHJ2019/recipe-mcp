"""The Telegram host end to end with a fake Bot API and a fake brain."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from recipe_mcp.adapters.telegram.api import HttpTelegramApi, TelegramApiError
from recipe_mcp.adapters.telegram.host import TelegramHost
from recipe_mcp.cli.main import QUIET_LOGGERS, configure_logging
from recipe_mcp.domain.models import Member, Sentiment
from recipe_mcp.domain.taxonomy import Facet
from recipe_mcp.providers.agent_brain import BrainRequest, FakeBrain
from recipe_mcp.services import fixtures
from recipe_mcp.services.container import AppContext
from tests.conftest import NYT_FIXTURE_URL

GROUP = -100777
ALEX_ID, SAM_ID, STRANGER = 1001, 1002, 4004


class FakeTelegramApi:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.edited: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self._next_id = 500

    def get_me(self) -> dict[str, Any]:
        return {"username": "recipe_test_bot"}

    def get_updates(self, offset: int | None, timeout: int) -> list[dict[str, Any]]:
        pending = [u for u in self.updates if offset is None or u["update_id"] >= offset]
        return pending

    def send_message(
        self, chat_id: int | str, text: str, reply_to_message_id: int | None = None
    ) -> dict[str, Any]:
        self._next_id += 1
        self.sent.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_to": reply_to_message_id,
                "message_id": self._next_id,
            }
        )
        return {"message_id": self._next_id}

    def edit_message_text(self, chat_id: int | str, message_id: int, text: str) -> None:
        self.edited.append({"chat_id": chat_id, "message_id": message_id, "text": text})


def msg(
    user: int, text: str, mid: int, reply_to: int | None = None, chat: int = GROUP
) -> dict[str, Any]:
    m: dict[str, Any] = {
        "message_id": mid,
        "chat": {"id": chat},
        "from": {"id": user},
        "text": text,
    }
    if reply_to:
        m["reply_to_message"] = {"message_id": reply_to}
    return {"update_id": mid, "message": m}


@pytest.fixture
def host(seeded_ctx: AppContext) -> tuple[TelegramHost, FakeTelegramApi, FakeBrain]:
    seeded_ctx.settings.telegram_allowed_user_ids = f"{ALEX_ID},{SAM_ID}"
    seeded_ctx.settings.telegram_group_chat_id = GROUP
    members = {m.member_key: m for m in fixtures.ensure_demo_members(seeded_ctx)}
    alex, sam = members["alex"], members["sam"]
    alex.telegram_user_id, sam.telegram_user_id = ALEX_ID, SAM_ID
    seeded_ctx.members.upsert(alex)
    seeded_ctx.members.upsert(sam)
    api = FakeTelegramApi()

    def respond(request: BrainRequest) -> str:
        if "cozy" in request.text:
            recs = seeded_ctx.recommendation.recommend(
                __import__(
                    "recipe_mcp.domain.models", fromlist=["RecommendationRequest"]
                ).RecommendationRequest(character=["cozy"])
            )
            ids = ",".join(str(r.recipe_id) for r in recs)
            return "Try: " + "; ".join(r.title for r in recs) + f"\nRECIPES: {ids}"
        return f"I heard: {request.text} (member {request.member_key})\nRECIPES: none"

    brain = FakeBrain(respond)
    return TelegramHost(seeded_ctx, api, brain), api, brain


def test_strangers_and_other_chats_are_ignored(
    host: tuple[TelegramHost, FakeTelegramApi, FakeBrain],
) -> None:
    h, api, brain = host
    assert h.handle_update(msg(STRANGER, "hi", 1)) is None
    assert h.handle_update(msg(ALEX_ID, "hi", 2, chat=-100999)) is None
    assert api.sent == [] and brain.requests == []


def test_nyt_link_saved_deterministically(
    host: tuple[TelegramHost, FakeTelegramApi, FakeBrain], seeded_ctx: AppContext
) -> None:
    h, api, brain = host
    reply = h.handle_update(msg(ALEX_ID, NYT_FIXTURE_URL + "?smid=share", 10))
    assert reply is not None and reply.startswith("<b>Saved: Test Kitchen Lemon Chicken Thighs")
    assert brain.requests == []
    saved = seeded_ctx.recipes.find_by_url(seeded_ctx.household_id, NYT_FIXTURE_URL)
    assert (
        saved is not None
        and saved.added_by_member_id
        == seeded_ctx.members.by_key(seeded_ctx.household_id, "alex").id
    )  # type: ignore[union-attr]
    # Replying 👍 to the confirmation rates that recipe for the replier (Sam).
    bot_msg = api.sent[-1]["message_id"]
    reply2 = h.handle_update(msg(SAM_ID, "👍", 11, reply_to=bot_msg))
    assert reply2 is not None and "Sam likes" in reply2
    fb = seeded_ctx.feedback.for_recipe(saved.id or 0)
    assert (
        fb[-1].sentiment == Sentiment.LIKE
        and fb[-1].member_id == seeded_ctx.members.by_telegram_id(SAM_ID).id
    )  # type: ignore[union-attr]


def test_brain_recommendation_then_ordinal_rating_and_time_fix(
    host: tuple[TelegramHost, FakeTelegramApi, FakeBrain], seeded_ctx: AppContext
) -> None:
    h, _api, brain = host
    reply = h.handle_update(msg(ALEX_ID, "Something cozy tonight?", 20))
    assert reply is not None and reply.startswith("Try: ")
    assert brain.requests[0].member_key == "alex"
    state = seeded_ctx.pending.get(str(GROUP), "recent_results")
    assert state is not None and len(state["ids"]) == 3
    second = int(state["ids"][1])

    reply2 = h.handle_update(msg(SAM_ID, "we loved the second one", 21))
    assert reply2 is not None and "loves" in reply2
    assert seeded_ctx.feedback.for_recipe(second)[-1].sentiment == Sentiment.LOVE

    reply3 = h.handle_update(msg(ALEX_ID, "the first one takes about 35 minutes", 22))
    first = int(state["ids"][0])
    assert reply3 is not None and "35 minutes" in reply3
    assert seeded_ctx.recipes.get(first).total_minutes == 35  # type: ignore[union-attr]

    # Free text goes to the brain with history and the last result list.
    h.handle_update(msg(ALEX_ID, "what about something lighter", 23))
    last = brain.requests[-1]
    assert last.recent_result_ids == [int(i) for i in state["ids"]]
    assert any(role == "assistant" for role, _ in last.history)


def test_on_behalf_rating_and_photo(
    host: tuple[TelegramHost, FakeTelegramApi, FakeBrain], seeded_ctx: AppContext
) -> None:
    h, _api, _brain = host
    h.handle_update(msg(ALEX_ID, "Something cozy", 30))
    state = seeded_ctx.pending.get(str(GROUP), "recent_results")
    assert state is not None
    reply = h.handle_update(msg(ALEX_ID, "I liked it but Sam didn't", 31))
    assert reply is not None and "Alex likes" in reply and "Sam dislikes" in reply
    fb = seeded_ctx.feedback.for_recipe(int(state["ids"][0]))
    assert fb[-2].sentiment == Sentiment.LIKE and fb[-2].reported_by_member_id is None
    assert fb[-1].sentiment == Sentiment.DISLIKE and fb[-1].reported_by_member_id is not None
    photo = {
        "update_id": 32,
        "message": {
            "message_id": 32,
            "chat": {"id": GROUP},
            "from": {"id": ALEX_ID},
            "photo": [{}],
        },
    }
    assert "later stage" in (h.handle_update(photo) or "")


def test_brain_failure_is_graceful(seeded_ctx: AppContext) -> None:
    seeded_ctx.settings.telegram_allowed_user_ids = f"{ALEX_ID}"
    seeded_ctx.settings.telegram_group_chat_id = GROUP
    api = FakeTelegramApi()

    class BrokenBrain:
        name = "broken"

        def reply(self, request: BrainRequest):  # type: ignore[no-untyped-def]
            from recipe_mcp.providers.agent_brain import BrainReply

            return BrainReply(text="", error="exit 1")

    h = TelegramHost(seeded_ctx, api, BrokenBrain())
    reply = h.handle_update(msg(ALEX_ID, "anything", 40))
    assert reply is not None and reply.startswith("Sorry")


def test_brain_failure_details_never_reach_the_log(
    seeded_ctx: AppContext, caplog: pytest.LogCaptureFixture
) -> None:
    seeded_ctx.settings.telegram_allowed_user_ids = f"{ALEX_ID}"
    seeded_ctx.settings.telegram_group_chat_id = GROUP

    class LeakyBrain:
        name = "leaky"

        def reply(self, request: BrainRequest):  # type: ignore[no-untyped-def]
            from recipe_mcp.providers.agent_brain import BrainReply

            return BrainReply(text="", error="exit 1", diagnostic=f"stderr: {request.text}")

    caplog.set_level(logging.DEBUG)
    h = TelegramHost(seeded_ctx, FakeTelegramApi(), LeakyBrain())
    h.handle_update(msg(ALEX_ID, "private lasagne plans", 41))
    assert "exit 1" in caplog.text
    assert "lasagne" not in caplog.text


def test_startup_retries_get_me_until_telegram_is_reachable(seeded_ctx: AppContext) -> None:
    """Regression: at boot DNS is not ready and getMe raised, crashing the daemon."""

    class FlakyApi(FakeTelegramApi):
        def __init__(self, failures: int) -> None:
            super().__init__()
            self.failures = failures
            self.calls = 0

        def get_me(self) -> dict[str, Any]:
            self.calls += 1
            if self.calls <= self.failures:
                raise TelegramApiError("getMe: ConnectError")
            return super().get_me()

    sleeps: list[float] = []
    api = FlakyApi(failures=6)
    h = TelegramHost(seeded_ctx, api, FakeBrain(), sleep=sleeps.append)
    assert h.wait_for_telegram() == {"username": "recipe_test_bot"}
    assert api.calls == 7
    assert sleeps == [2, 4, 8, 16, 30, 30]  # exponential backoff, capped at 30s

    immediate: list[float] = []
    ok = TelegramHost(seeded_ctx, FakeTelegramApi(), FakeBrain(), sleep=immediate.append)
    assert ok.wait_for_telegram()["username"] == "recipe_test_bot"
    assert immediate == []


def test_poll_once_advances_offset(host: tuple[TelegramHost, FakeTelegramApi, FakeBrain]) -> None:
    h, api, _brain = host
    api.updates = [msg(ALEX_ID, "hello there", 50), msg(ALEX_ID, "and again", 51)]
    assert h.poll_once() == 2 and h.offset == 52
    assert h.poll_once() == 0
    assert len(api.sent) == 2


def test_offset_survives_a_restart(
    host: tuple[TelegramHost, FakeTelegramApi, FakeBrain], seeded_ctx: AppContext
) -> None:
    h, api, _brain = host
    api.updates = [msg(ALEX_ID, "hello there", 60), msg(ALEX_ID, "and again", 61)]
    assert h.poll_once() == 2
    restarted = TelegramHost(seeded_ctx, api, FakeBrain())
    assert restarted.offset == 62
    assert restarted.poll_once() == 0  # nothing replayed, no second reply
    assert len(api.sent) == 2


def test_a_message_that_crashes_the_host_is_not_replayed(seeded_ctx: AppContext) -> None:
    seeded_ctx.settings.telegram_allowed_user_ids = f"{ALEX_ID}"
    seeded_ctx.settings.telegram_group_chat_id = GROUP
    api = FakeTelegramApi()
    api.updates = [msg(ALEX_ID, "this one breaks", 70)]

    class CrashingBrain:
        name = "crashing"

        def reply(self, request: BrainRequest):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        TelegramHost(seeded_ctx, api, CrashingBrain()).poll_once()
    after_restart = TelegramHost(seeded_ctx, api, FakeBrain())
    assert after_restart.poll_once() == 0


def test_member_without_telegram_id(seeded_ctx: AppContext) -> None:
    seeded_ctx.settings.telegram_allowed_user_ids = "9"
    seeded_ctx.settings.telegram_group_chat_id = GROUP
    seeded_ctx.members.create(
        Member(household_id=seeded_ctx.household_id, member_key="x", display_name="X")
    )
    h = TelegramHost(seeded_ctx, FakeTelegramApi(), FakeBrain())
    h.handle_update(msg(9, "something cozy", 60))
    state = seeded_ctx.pending.get(str(GROUP), "recent_results")
    reply = h.handle_update(msg(9, "loved the first one", 61))
    assert state is None or reply is not None
    # A rating from an unmapped Telegram id is refused, never mis-attributed.
    assert all(
        f.member_id
        for r in seeded_ctx.recipes.list_for_household(seeded_ctx.household_id)
        for f in seeded_ctx.feedback.for_recipe(r.id or 0)
    )
    assert Facet.CUISINE  # keep import used


@pytest.fixture
def _restore_http_log_levels() -> Iterator[None]:
    saved = {name: logging.getLogger(name).level for name in QUIET_LOGGERS}
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


@pytest.mark.usefixtures("_restore_http_log_levels")
def test_poll_never_logs_the_bot_token(
    host: tuple[TelegramHost, FakeTelegramApi, FakeBrain], caplog: pytest.LogCaptureFixture
) -> None:
    """Regression: httpx logged full Bot API URLs, which contain the token, at INFO."""
    token = "123456:not-a-real-token-abc"
    update = msg(ALEX_ID, "hi", 30)

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "getUpdates":
            return httpx.Response(200, json={"ok": True, "result": [update]})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 900}})

    h, _fake_api, _brain = host
    h.api = HttpTelegramApi(token, client=httpx.Client(transport=httpx.MockTransport(handler)))
    caplog.set_level(logging.DEBUG)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)

    # Unconfigured, httpx's INFO request line carries the token; the capture must see it.
    h.api.get_me()
    assert token in caplog.text
    caplog.clear()

    configure_logging("DEBUG")
    assert h.poll_once() == 1
    assert token not in caplog.text
    assert all(token not in r.getMessage() for r in caplog.records)
