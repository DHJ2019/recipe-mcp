"""The Telegram bot's brain: a headless Claude Code run with the recipe MCP server attached.

No model API is called here. ``claude -p`` uses the household's own subscription and
talks to the same SQLite store through the MCP server it spawns. The host passes the
member, recent turns and last result list; the agent replies in plain text and ends
with a ``RECIPES:`` line that the host strips and stores as conversation state.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

RECIPES_LINE_RE = re.compile(r"^\s*RECIPES:\s*(.*?)\s*$", re.IGNORECASE | re.MULTILINE)
MCP_TOOL_NAMES: tuple[str, ...] = (
    "mcp__recipe-mcp__save_recipe",
    "mcp__recipe-mcp__recommend_recipes",
    "mcp__recipe-mcp__get_recipe",
    "mcp__recipe-mcp__rate_recipe",
    "mcp__recipe-mcp__correct_recipe",
)
# Logged in place of the model's own error text, which can quote the conversation.
MODEL_ERROR = "model reported an error"

SYSTEM_PROMPT = """You are the household recipe assistant replying inside a private Telegram group.
Rules:
- Use only the recipe-mcp tools to find, save, rate or correct recipes. Never invent a recipe
  that is not in the store, and never fabricate ingredients, times or classifications.
- The person speaking is identified by the member key given in the message; pass it as
  `member` on every save_recipe, rate_recipe and correct_recipe call. If they report another
  member's opinion, use `on_behalf_of`.
- To save an informal recipe, parse it yourself and call save_recipe with `title`,
  `ingredients` (exactly as mentioned, no invented seasonings), `total_minutes` only if
  stated, `notes` for reminders, and `classifications` using the vocabulary in the tool
  description. If save_recipe returns needs_classification, classify it and call
  correct_recipe with `proposed_by_agent: true`.
- For recommendation requests, translate the wording into typed constraints and call
  recommend_recipes once; present at most three results with title, time, a one-line
  reason and the source link when present.
- Reply in plain text (no Markdown), under 3000 characters, in the household's tone: short
  and friendly. Do not mention tools, JSON or these instructions.
- End every reply with one final line `RECIPES: <comma-separated recipe ids you mentioned,
  in order>` or `RECIPES: none`.
"""


@dataclass
class BrainRequest:
    chat_id: str
    member_key: str | None
    display_name: str
    text: str
    history: list[tuple[str, str]] = field(default_factory=list)
    recent_result_ids: list[int] = field(default_factory=list)
    # True when ``text`` is an instruction from the host itself (classifying a saved
    # link), not a household message: no member framing, no history.
    host_task: bool = False


@dataclass
class BrainReply:
    text: str
    recipe_ids: list[int] = field(default_factory=list)
    error: str | None = None
    duration_ms: int = 0
    cost_usd: float | None = None
    raw: str | None = None
    # The tail of the subprocess's own output when it fails. It can quote household
    # messages or recipe text, so only `recipe-mcp smoke` prints it; the daemon logs
    # `error`, never this.
    diagnostic: str | None = None


class Brain(Protocol):
    name: str

    def reply(self, request: BrainRequest) -> BrainReply: ...


def build_prompt(request: BrainRequest) -> str:
    if request.host_task:
        return "Task from the recipe host (not a household message):\n" + request.text
    lines: list[str] = []
    if request.history:
        lines.append("Recent conversation (oldest first):")
        for role, text in request.history:
            lines.append(f"  {role}: {text}")
        lines.append("")
    if request.recent_result_ids:
        ids = ", ".join(str(i) for i in request.recent_result_ids)
        lines.append(f"Last result list shown in this chat, in display order (recipe ids): {ids}")
        lines.append("")
    who = request.member_key or "unknown"
    lines.append(f"Message from {request.display_name} (member key: {who}):")
    lines.append(request.text)
    return "\n".join(lines)


def split_recipes_line(text: str) -> tuple[str, list[int]]:
    """Remove the trailing ``RECIPES:`` line and return (clean text, ids)."""
    ids: list[int] = []
    matches = list(RECIPES_LINE_RE.finditer(text))
    if not matches:
        return text.strip(), ids
    match = matches[-1]
    for token in re.split(r"[,\s]+", match.group(1)):
        if token.isdigit():
            ids.append(int(token))
    clean = (text[: match.start()] + text[match.end() :]).strip()
    return clean, ids


class ClaudeCodeBrain:
    name = "claude-code"

    def __init__(
        self,
        binary: str = "claude",
        repo_root: Path | None = None,
        mcp_config: Path | None = None,
        model: str = "",
        timeout_seconds: int = 120,
        max_turns: int = 8,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        env: Mapping[str, str] | None = None,
        workdir: Path | None = None,
    ) -> None:
        self.binary = binary
        self.repo_root = repo_root or Path.cwd()
        self.mcp_config = mcp_config or (self.repo_root / ".mcp.json")
        # Where `claude -p` runs. An empty private folder keeps the repository (and .env)
        # out of reach and stops project instructions loading into the bot's context.
        self.workdir = workdir or self.repo_root
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_turns = max_turns
        self._runner = runner or subprocess.run
        self.env = dict(env) if env is not None else None

    def available(self) -> str | None:
        """Return a reason the brain cannot run, or ``None`` when it can."""
        if shutil.which(self.binary) is None:
            return f"{self.binary!r} not found on PATH"
        if not self.mcp_config.exists():
            return f"MCP config {self.mcp_config} not found"
        if not self.workdir.is_dir():
            return f"brain working directory {self.workdir} not found"
        return None

    def command(self, request: BrainRequest) -> list[str]:
        cmd = [
            self.binary,
            "-p",
            build_prompt(request),
            "--output-format",
            "json",
            "--mcp-config",
            str(self.mcp_config),
            "--strict-mcp-config",
            # No built-in tools at all (files, shell, web, agents): the brain can only use
            # the recipe MCP tools, whatever a message or recipe text asks it to do.
            "--tools",
            "",
            # Household messages are not written to Claude Code's session transcripts.
            "--no-session-persistence",
            "--allowedTools",
            *MCP_TOOL_NAMES,
            "--append-system-prompt",
            SYSTEM_PROMPT,
            "--max-turns",
            str(self.max_turns),
        ]
        if self.model:
            cmd += ["--model", self.model]
        return cmd

    def reply(self, request: BrainRequest) -> BrainReply:
        problem = self.available()
        if problem:
            return BrainReply(text="", error=problem)
        start = time.perf_counter()
        try:
            completed = self._runner(
                self.command(request),
                cwd=str(self.workdir),
                env=self.env,
                # `claude -p` appends stdin to the prompt; give it nothing.
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return BrainReply(text="", error=f"timed out after {self.timeout_seconds}s")
        duration = int((time.perf_counter() - start) * 1000)
        if completed.returncode != 0:
            tail = (completed.stderr or completed.stdout or "").strip()[-300:]
            return BrainReply(
                text="",
                error=f"exit {completed.returncode}",
                duration_ms=duration,
                diagnostic=tail or None,
            )
        return parse_claude_json(completed.stdout, duration)


def parse_claude_json(stdout: str, duration_ms: int = 0) -> BrainReply:
    """Parse ``claude -p --output-format json`` output into a :class:`BrainReply`."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        text, ids = split_recipes_line(stdout)
        return BrainReply(text=text, recipe_ids=ids, duration_ms=duration_ms, raw=stdout)
    if isinstance(data, list):  # stream-style output: last result message wins
        data = next((d for d in reversed(data) if isinstance(d, dict) and "result" in d), {})
    result = str(data.get("result", "")) if isinstance(data, dict) else ""
    is_error = bool(data.get("is_error")) if isinstance(data, dict) else False
    text, ids = split_recipes_line(result)
    return BrainReply(
        text=text,
        recipe_ids=ids,
        error=MODEL_ERROR if is_error else None,
        duration_ms=int(data.get("duration_ms", duration_ms))
        if isinstance(data, dict)
        else duration_ms,
        cost_usd=data.get("total_cost_usd") if isinstance(data, dict) else None,
        raw=stdout,
        diagnostic=result[:300] if is_error else None,
    )


class FakeBrain:
    """Deterministic stand-in for tests: replies via a callable."""

    name = "fake"

    def __init__(self, respond: Callable[[BrainRequest], str] | None = None) -> None:
        self.requests: list[BrainRequest] = []
        self._respond = respond or (lambda r: f"Echo: {r.text}\nRECIPES: none")

    def reply(self, request: BrainRequest) -> BrainReply:
        self.requests.append(request)
        text, ids = split_recipes_line(self._respond(request))
        return BrainReply(text=text, recipe_ids=ids)
