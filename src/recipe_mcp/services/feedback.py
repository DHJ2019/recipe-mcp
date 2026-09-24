"""Record ratings and summarise individual plus household feedback."""

from __future__ import annotations

import re

from recipe_mcp.db.repositories import FeedbackRepository, MemberRepository, RecipeRepository
from recipe_mcp.domain import feedback as feedback_rules
from recipe_mcp.domain.models import Feedback, FeedbackSummary, Sentiment, utcnow_iso

_SENTIMENT_PATTERNS: list[tuple[Sentiment, re.Pattern[str]]] = [
    (
        Sentiment.DISLIKE,
        re.compile(
            r"👎|\bdon'?t recommend|\bdidn'?t like|\bhated|\bnot again|\bno thanks|\bdislike", re.I
        ),
    ),
    (
        Sentiment.LOVE,
        re.compile(r"❤️|❤|😍|🤩|\bloved?\b|\bfavou?rite|\bamazing|\bdefinitely again", re.I),
    ),
    (Sentiment.LIKE, re.compile(r"👍|🙂|\bliked?\b|\bgood\b|\bnice\b|\benjoyed|\bwas fine", re.I)),
]


def parse_sentiment(text: str) -> Sentiment | None:
    """Map an emoji or short natural-language reply to a sentiment."""
    for sentiment, pattern in _SENTIMENT_PATTERNS:
        if pattern.search(text):
            return sentiment
    return None


class FeedbackService:
    def __init__(
        self,
        recipes: RecipeRepository,
        feedback: FeedbackRepository,
        members: MemberRepository,
        household_id: int,
    ) -> None:
        self.recipes = recipes
        self.feedback = feedback
        self.members = members
        self.household_id = household_id

    def rate(
        self,
        recipe_id: int,
        member_id: int,
        sentiment: Sentiment,
        notes: str | None = None,
        cooked: bool = True,
        reported_by_member_id: int | None = None,
    ) -> FeedbackSummary:
        """Store feedback for ``member_id``. When one member reports another's opinion,
        ``reported_by_member_id`` records who said it so the distinction is auditable."""
        if self.recipes.get(recipe_id) is None:
            raise LookupError(f"recipe {recipe_id} not found")
        if self.members.get(member_id) is None:
            raise LookupError(f"member {member_id} not found")
        if reported_by_member_id == member_id:
            reported_by_member_id = None
        self.feedback.add(
            Feedback(
                recipe_id=recipe_id,
                member_id=member_id,
                reported_by_member_id=reported_by_member_id,
                sentiment=sentiment,
                notes=notes,
                cooked_at=utcnow_iso() if cooked else None,
            )
        )
        return self.summary(recipe_id)

    def summary(self, recipe_id: int) -> FeedbackSummary:
        members = self.members.list_for_household(self.household_id)
        return feedback_rules.summarize(recipe_id, self.feedback.for_recipe(recipe_id), members)
