"""Classifying shared links after the instant reply, and the backlog command.

The store runs with MODEL_PROVIDER=none, as in production. The fake brain behaves like
the real one: it reads the recipe id from the host's task and writes a proposal through
the same service the MCP ``correct_recipe(proposed_by_agent=true)`` tool calls.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from recipe_mcp.adapters.telegram.api import TelegramApiError
from recipe_mcp.adapters.telegram.host import TelegramHost
from recipe_mcp.cli import main as cli
from recipe_mcp.domain.models import FacetSource
from recipe_mcp.domain.taxonomy import Facet
from recipe_mcp.providers.agent_brain import BrainReply, BrainRequest
from recipe_mcp.services import fixtures
from recipe_mcp.services.container import AppContext, build_context
from recipe_mcp.services.link_classification import (
    NOTHING_STORED,
    LinkClassificationService,
    needs_classification,
)
from recipe_mcp.settings import Settings
from tests.conftest import NYT_FIXTURE_URL, FixtureFetcher, StubTitleFetcher

GROUP = -100777
ALEX_ID = 1001
PROPOSAL: dict[str, list[str]] = {
    "cuisine": ["mediterranean"],
    "dish_type": ["roast"],
    "character": ["bright", "cozy"],
    "cooking_method": ["roast"],
    "primary_ingredient": ["chicken thigh"],
}


class FakeTelegramApi:
    def __init__(self, fail_edits: bool = False) -> None:
        self.sent: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []
        self.fail_edits = fail_edits
        self._next_id = 500

    def get_me(self) -> dict[str, Any]:
        return {"username": "recipe_test_bot"}

    def get_updates(self, offset: int | None, timeout: int) -> list[dict[str, Any]]:
        return []

    def send_message(
        self, chat_id: int | str, text: str, reply_to_message_id: int | None = None
    ) -> dict[str, Any]:
        self._next_id += 1
        self.sent.append({"chat_id": chat_id, "text": text, "message_id": self._next_id})
        return {"message_id": self._next_id}

    def edit_message_text(self, chat_id: int | str, message_id: int, text: str) -> None:
        if self.fail_edits:
            raise TelegramApiError("editMessageText: Bad Request")
        self.edits.append({"chat_id": chat_id, "message_id": message_id, "text": text})


class ProposingBrain:
    """Proposes ``facets`` for the recipe named in the task, like the real brain would."""

    name = "proposing"

    def __init__(self, ctx: AppContext, facets: dict[str, list[str]] | None = None) -> None:
        self.ctx = ctx
        self.facets = PROPOSAL if facets is None else facets
        self.requests: list[BrainRequest] = []

    def reply(self, request: BrainRequest) -> BrainReply:
        self.requests.append(request)
        match = re.search(r"get_recipe with recipe_id (\d+)", request.text)
        assert request.host_task and match
        if self.facets:
            self.ctx.corrections.propose(int(match.group(1)), self.facets)
        return BrainReply(text="", recipe_ids=[int(match.group(1))], duration_ms=5)


class FailingBrain:
    name = "failing"

    def __init__(self) -> None:
        self.requests: list[BrainRequest] = []

    def reply(self, request: BrainRequest) -> BrainReply:
        self.requests.append(request)
        return BrainReply(text="", error="exit 1", diagnostic="stderr: Lemon Chicken secret")


@pytest.fixture
def agent_ctx(settings: Settings, fetcher: FixtureFetcher) -> Iterator[AppContext]:
    settings.model_provider = "none"
    settings.telegram_allowed_user_ids = str(ALEX_ID)
    settings.telegram_group_chat_id = GROUP
    context = build_context(settings, fetcher=fetcher, title_fetcher=StubTitleFetcher())
    alex = next(m for m in fixtures.ensure_demo_members(context) if m.member_key == "alex")
    alex.telegram_user_id = ALEX_ID
    context.members.upsert(alex)
    try:
        yield context
    finally:
        context.close()


def link(text: str, mid: int) -> dict[str, Any]:
    return {
        "update_id": mid,
        "message": {
            "message_id": mid,
            "chat": {"id": GROUP},
            "from": {"id": ALEX_ID},
            "text": text,
        },
    }


def make_host(
    ctx: AppContext, brain: Any, api: FakeTelegramApi | None = None
) -> tuple[TelegramHost, FakeTelegramApi]:
    api = api or FakeTelegramApi()
    return TelegramHost(ctx, api, brain), api


# -- shared links ----------------------------------------------------------


def test_shared_link_reply_is_edited_with_new_categories(agent_ctx: AppContext) -> None:
    brain = ProposingBrain(agent_ctx)
    host, api = make_host(agent_ctx, brain)

    reply = host.handle_update(link(NYT_FIXTURE_URL + "?smid=share", 10))

    assert reply is not None and "Saved: Test Kitchen Lemon Chicken Thighs" in reply
    assert "roast" not in reply  # the instant reply has rule-derived facets only
    assert len(api.sent) == 1 and len(api.edits) == 1
    edit = api.edits[0]
    assert edit["message_id"] == api.sent[0]["message_id"] and edit["chat_id"] == GROUP
    assert "Omnivore · Mediterranean · roast · bright, cozy · 45 minutes" in edit["text"]
    assert edit["text"].startswith("<b>Saved: Test Kitchen Lemon Chicken Thighs</b>")

    # One host task, no household framing or history.
    assert len(brain.requests) == 1
    request = brain.requests[0]
    assert request.host_task and request.history == [] and request.member_key is None

    saved = agent_ctx.recipes.find_by_url(agent_ctx.household_id, NYT_FIXTURE_URL)
    assert saved is not None and not needs_classification(saved)
    primary = [c for c in saved.classifications if c.facet == Facet.PRIMARY_INGREDIENT]
    assert primary and all(c.source == FacetSource.MODEL for c in primary)

    # The classification turn is not part of the chat's conversation history.
    turns = (agent_ctx.pending.get(str(GROUP), "turn_history") or {}).get("turns", [])
    assert all("Classify saved recipe" not in text for _, text in turns)

    # Ratings by reply still resolve: the edited message keeps its id.
    rated = host.handle_update(
        {
            "update_id": 11,
            "message": {
                "message_id": 11,
                "chat": {"id": GROUP},
                "from": {"id": ALEX_ID},
                "text": "👍",
                "reply_to_message": {"message_id": edit["message_id"]},
            },
        }
    )
    assert rated is not None and "Alex likes" in rated


def test_proposal_written_by_another_process_is_seen(
    agent_ctx: AppContext, fetcher: FixtureFetcher
) -> None:
    # The real brain writes through the MCP server it spawns: its own SQLite connection.
    server_ctx = build_context(
        agent_ctx.settings, fetcher=fetcher, title_fetcher=StubTitleFetcher()
    )
    try:
        host, api = make_host(agent_ctx, ProposingBrain(server_ctx))
        host.handle_update(link(NYT_FIXTURE_URL, 10))
    finally:
        server_ctx.close()
    assert len(api.edits) == 1 and "roast · bright, cozy" in api.edits[0]["text"]


def test_already_classified_link_runs_no_brain_and_no_edit(agent_ctx: AppContext) -> None:
    brain = ProposingBrain(agent_ctx)
    host, api = make_host(agent_ctx, brain)
    host.handle_update(link(NYT_FIXTURE_URL, 10))
    assert len(brain.requests) == 1

    again = host.handle_update(link(NYT_FIXTURE_URL, 11))

    assert again is not None and "Already saved" in again and "roast" in again
    assert len(brain.requests) == 1 and len(api.edits) == 1


def test_already_saved_but_unclassified_link_is_classified(agent_ctx: AppContext) -> None:
    agent_ctx.ingestion.save_url(NYT_FIXTURE_URL)
    brain = ProposingBrain(agent_ctx)
    host, api = make_host(agent_ctx, brain)

    host.handle_update(link(NYT_FIXTURE_URL, 10))

    assert len(brain.requests) == 1 and len(api.edits) == 1
    assert api.edits[0]["text"].startswith("<b>Already saved: ")


def test_failing_brain_leaves_reply_unedited_and_logs_no_content(
    agent_ctx: AppContext, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    brain = FailingBrain()
    host, api = make_host(agent_ctx, brain)

    reply = host.handle_update(link(NYT_FIXTURE_URL, 10))

    assert reply is not None and reply.startswith("<b>Saved: ")
    assert len(brain.requests) == 1 and api.edits == []
    assert "link classification failed" in caplog.text and "exit 1" in caplog.text
    assert "secret" not in caplog.text and "Lemon" not in caplog.text


def test_brain_that_stores_nothing_leaves_reply_unedited(
    agent_ctx: AppContext, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    host, api = make_host(agent_ctx, ProposingBrain(agent_ctx, facets={}))

    host.handle_update(link(NYT_FIXTURE_URL, 10))

    assert api.edits == [] and NOTHING_STORED in caplog.text


def test_rejected_proposal_is_a_normal_failure(agent_ctx: AppContext) -> None:
    from recipe_mcp.services.corrections import CorrectionError

    class OversizedBrain(ProposingBrain):
        def reply(self, request: BrainRequest) -> BrainReply:
            # The MCP tool turns this into a tool error; the brain then gives up.
            with pytest.raises(CorrectionError):
                super().reply(request)
            return BrainReply(text="RECIPES: none")

    host, api = make_host(agent_ctx, OversizedBrain(agent_ctx, facets={"cuisine": ["x" * 5000]}))
    host.handle_update(link(NYT_FIXTURE_URL, 10))
    assert api.edits == []


def test_no_edit_when_the_confirmation_would_not_change(agent_ctx: AppContext) -> None:
    brain = ProposingBrain(agent_ctx, facets={"cooking_method": ["roast"]})
    host, api = make_host(agent_ctx, brain)

    host.handle_update(link(NYT_FIXTURE_URL, 10))

    # Stored, but nothing the confirmation shows changed ("other" dish type is hidden).
    saved = agent_ctx.recipes.find_by_url(agent_ctx.household_id, NYT_FIXTURE_URL)
    assert saved is not None and saved.facet_values(Facet.COOKING_METHOD) == ["roast"]
    assert len(brain.requests) == 1 and api.edits == []


def test_failed_edit_is_logged_and_the_host_carries_on(
    agent_ctx: AppContext, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    host, api = make_host(agent_ctx, ProposingBrain(agent_ctx), FakeTelegramApi(fail_edits=True))

    reply = host.handle_update(link(NYT_FIXTURE_URL, 10))

    assert reply is not None and len(api.sent) == 1 and api.edits == []
    assert "edit failed" in caplog.text


def test_confirmation_never_shows_other(agent_ctx: AppContext) -> None:
    saved = agent_ctx.ingestion.save_structured(
        "Mystery Bake", ["flour", "butter"], classifications={"cuisine": "other"}
    )
    assert saved.recipe.facet_values(Facet.CUISINE) == ["other"]
    assert "other" not in saved.confirmation().lower()


def test_unsupported_link_runs_no_brain(agent_ctx: AppContext) -> None:
    brain = ProposingBrain(agent_ctx)
    host, api = make_host(agent_ctx, brain)

    host.handle_update(link("https://example.com/knife-skills", 10))

    assert brain.requests == [] and api.edits == []


# -- backlog ---------------------------------------------------------------


def save_links(ctx: AppContext, count: int) -> list[int]:
    ids = []
    for n in range(count):
        url = f"https://cooking.nytimes.com/recipes/{2000001 + n}-test-dish-{n}"
        recipe_id = ctx.ingestion.save_url(url).recipe.id
        assert recipe_id is not None
        ids.append(recipe_id)
    return ids


def test_backlog_classifies_only_uncategorized_and_is_idempotent(agent_ctx: AppContext) -> None:
    ids = save_links(agent_ctx, 3)
    agent_ctx.ingestion.save_structured(
        "Already Classified Soup", ["leek", "potato"], classifications={"dish_type": "soup"}
    )
    brain = ProposingBrain(agent_ctx)
    sleeps: list[float] = []
    service = LinkClassificationService(
        agent_ctx.recipes, brain, agent_ctx.household_id, sleep=sleeps.append
    )
    assert [r.id for r in service.backlog()] == ids

    first = service.classify_backlog(limit=2, pause_seconds=0.5)
    assert first.pending == 3 and first.classified == 2 and first.failed == 0
    assert [a.recipe_id for a in first.attempts] == ids[:2]
    assert sleeps == [0.5]

    second = service.classify_backlog()
    assert second.pending == 1 and [a.recipe_id for a in second.attempts] == ids[2:]

    third = service.classify_backlog()
    assert third.pending == 0 and third.attempts == []
    assert len(brain.requests) == 3


def test_backlog_stops_after_consecutive_failures(agent_ctx: AppContext) -> None:
    save_links(agent_ctx, 5)
    brain = FailingBrain()
    reported: list[tuple[int, int, bool]] = []
    service = LinkClassificationService(
        agent_ctx.recipes, brain, agent_ctx.household_id, sleep=lambda _: None
    )

    result = service.classify_backlog(
        report=lambda i, n, _r, a: reported.append((i, n, a.classified))
    )

    assert result.stopped_early and result.failed == 3 and len(brain.requests) == 3
    assert reported == [(1, 5, False), (2, 5, False), (3, 5, False)]
    assert all(a.error == "exit 1" for a in result.attempts)


# -- command line ----------------------------------------------------------


def run_cli(
    agent_ctx: AppContext,
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    brain_factory: Callable[[], Any] | None = None,
) -> int:
    monkeypatch.setattr(cli, "_ctx", lambda _settings: agent_ctx)
    if brain_factory is not None:
        monkeypatch.setattr(cli, "_build_brain", lambda _settings: brain_factory())
        monkeypatch.setattr(agent_ctx.settings, "claude_code_bin", "python3")
    args = cli.build_parser().parse_args(argv)
    code: int = args.fn(args, agent_ctx.settings)
    return code


def test_cli_dry_run_lists_without_a_brain(
    agent_ctx: AppContext, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ids = save_links(agent_ctx, 3)
    monkeypatch.setattr(agent_ctx.settings, "brain", "none")

    code = run_cli(agent_ctx, monkeypatch, ["classify-backlog", "--dry-run", "--limit", "2"])

    out = capsys.readouterr().out
    assert code == 0
    assert f"{ids[0]}: " in out and f"{ids[1]}: " in out and f"{ids[2]}: " not in out
    assert "3 recipe(s) need classification; would classify 2" in out


def test_cli_classifies_with_limit_and_reports(
    agent_ctx: AppContext, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    save_links(agent_ctx, 3)

    code = run_cli(
        agent_ctx,
        monkeypatch,
        ["classify-backlog", "--limit", "2", "--pause", "0"],
        lambda: ProposingBrain(agent_ctx),
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "[1/2]" in out and "[2/2]" in out and "mediterranean · roast" in out
    assert "classified 2, failed 0; 1 recipe(s) still need classification" in out


def test_cli_needs_the_brain_unless_dry_run(
    agent_ctx: AppContext, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(agent_ctx.settings, "brain", "none")
    assert run_cli(agent_ctx, monkeypatch, ["classify-backlog"]) == 2
    assert "BRAIN (none)" in capsys.readouterr().out


def test_cli_rejects_a_zero_limit() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["classify-backlog", "--limit", "0"])
