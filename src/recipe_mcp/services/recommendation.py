"""Recommendation: typed constraints in, three meaningfully different recipes out."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from recipe_mcp.db.repositories import FeedbackRepository, MemberRepository, RecipeRepository
from recipe_mcp.domain import feedback as feedback_rules
from recipe_mcp.domain import ranking
from recipe_mcp.domain.models import RecommendationRequest, RecommendationResult
from recipe_mcp.providers.base import ModelClient, QueryConstraints


class RecommendationService:
    def __init__(
        self,
        recipes: RecipeRepository,
        feedback: FeedbackRepository,
        members: MemberRepository,
        model_factory: Callable[[], ModelClient],
        household_id: int,
    ) -> None:
        self.recipes = recipes
        self.feedback = feedback
        self.members = members
        self._model_factory = model_factory
        self.household_id = household_id

    def household_member_ids(self) -> list[int]:
        return [
            m.id for m in self.members.list_for_household(self.household_id) if m.id and m.active
        ]

    def diners_for(self, member_id: int | None) -> list[int]:
        """A named member personalises ranking; no member means the household view."""
        return [member_id] if member_id is not None else self.household_member_ids()

    def recommend(
        self, request: RecommendationRequest, now: datetime | None = None
    ) -> list[RecommendationResult]:
        recipes = [
            r for r in self.recipes.list_for_household(self.household_id) if r.is_recommendable
        ]
        feedback_by_recipe = self.feedback.for_household(self.household_id)
        facets_by_recipe = {
            r.id: [(f, v) for f, vs in r.classification_summary().items() for v in vs]
            for r in recipes
            if r.id is not None
        }
        affinity = {
            diner: feedback_rules.facet_affinity(feedback_by_recipe, facets_by_recipe, diner)
            for diner in request.diners
        }
        ranked = ranking.rank(recipes, request, feedback_by_recipe, affinity, now)
        return [ranking.to_result(s) for s in ranked]

    def request_from_constraints(
        self, constraints: QueryConstraints, member_id: int | None
    ) -> RecommendationRequest:
        diners = (
            self.household_member_ids() if constraints.for_household else self.diners_for(member_id)
        )
        return RecommendationRequest(
            dietary=constraints.dietary,
            cuisine=constraints.cuisine,
            dish_type=constraints.dish_type,
            main_ingredient=constraints.main_ingredient,
            character=constraints.character,
            max_minutes=constraints.max_minutes,
            available_ingredients=constraints.available_ingredients,
            excluded_ingredients=constraints.excluded_ingredients,
            max_missing=constraints.max_missing,
            diners=diners,
            exclude_recent_days=ranking.RECENT_REPETITION_DAYS
            if constraints.exclude_recent
            else None,
        )

    def recommend_from_text(
        self, text: str, member_id: int | None = None
    ) -> tuple[RecommendationRequest, list[RecommendationResult]]:
        constraints = self._model_factory().interpret_query(text).output
        request = self.request_from_constraints(constraints, member_id)
        return request, self.recommend(request)
