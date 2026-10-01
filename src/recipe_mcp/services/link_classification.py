"""Classify saved recipes with one brain turn: shared Telegram links and the backlog.

With no server-side model a recipe saved from a link has only rule-derived facets. The
brain (headless Claude Code) classifies it by calling ``get_recipe`` and
``correct_recipe(proposed_by_agent=true)`` on the MCP server it spawns. Success is
judged from the database afterwards, never from the brain's reply text.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from recipe_mcp.db.repositories import RecipeRepository
from recipe_mcp.domain.models import FacetSource, Recipe
from recipe_mcp.providers.agent_brain import Brain, BrainRequest
from recipe_mcp.providers.prompts import classify_saved_link_task

DEFAULT_PAUSE_SECONDS = 2.0
MAX_CONSECUTIVE_FAILURES = 3
NOTHING_STORED = "no classification stored"


def needs_classification(recipe: Recipe) -> bool:
    """Recommendable and no model or user facet yet (the ``list_uncategorized`` rule)."""
    return recipe.is_recommendable and not any(
        c.source in (FacetSource.MODEL, FacetSource.USER) for c in recipe.classifications
    )


@dataclass
class ClassificationAttempt:
    recipe_id: int
    # Re-read from the database after the brain ran (``None`` if it has gone).
    recipe: Recipe | None
    # Safe to log: a status such as "exit 1" or "timed out after 120s", never brain output.
    error: str | None = None
    duration_ms: int = 0

    @property
    def classified(self) -> bool:
        return self.error is None


@dataclass
class BacklogResult:
    pending: int
    attempts: list[ClassificationAttempt] = field(default_factory=list)
    stopped_early: bool = False

    @property
    def classified(self) -> int:
        return sum(1 for a in self.attempts if a.classified)

    @property
    def failed(self) -> int:
        return len(self.attempts) - self.classified


class LinkClassificationService:
    def __init__(
        self,
        recipes: RecipeRepository,
        brain: Brain,
        household_id: int,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.recipes = recipes
        self.brain = brain
        self.household_id = household_id
        self._sleep = sleep

    def classify(self, recipe_id: int) -> ClassificationAttempt:
        """Run one brain turn for ``recipe_id`` and report what it stored."""
        reply = self.brain.reply(
            BrainRequest(
                chat_id="",
                member_key=None,
                display_name="recipe host",
                text=classify_saved_link_task(recipe_id),
                host_task=True,
            )
        )
        recipe = self.recipes.get(recipe_id)
        if recipe is not None and not needs_classification(recipe):
            # Stored is what counts, even if the run then timed out or erred.
            return ClassificationAttempt(recipe_id, recipe, duration_ms=reply.duration_ms)
        return ClassificationAttempt(
            recipe_id, recipe, error=reply.error or NOTHING_STORED, duration_ms=reply.duration_ms
        )

    def backlog(self) -> list[Recipe]:
        return self.recipes.list_uncategorized(self.household_id)

    def classify_backlog(
        self,
        *,
        limit: int | None = None,
        pause_seconds: float = DEFAULT_PAUSE_SECONDS,
        max_consecutive_failures: int = MAX_CONSECUTIVE_FAILURES,
        report: Callable[[int, int, Recipe, ClassificationAttempt], None] | None = None,
    ) -> BacklogResult:
        """Classify uncategorized recipes oldest first. Classified recipes drop out of the
        backlog, so stopping and running again picks up where this left off."""
        pending = self.backlog()
        todo = pending[:limit] if limit else pending
        result = BacklogResult(pending=len(pending))
        failures = 0
        for index, recipe in enumerate(todo, start=1):
            assert recipe.id is not None
            if index > 1 and pause_seconds > 0:
                self._sleep(pause_seconds)
            attempt = self.classify(recipe.id)
            result.attempts.append(attempt)
            if report is not None:
                report(index, len(todo), recipe, attempt)
            failures = 0 if attempt.classified else failures + 1
            if failures >= max_consecutive_failures:
                result.stopped_early = index < len(todo)
                break
        return result
