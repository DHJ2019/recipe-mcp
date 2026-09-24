"""Feedback aggregation and household preference maths."""

from __future__ import annotations

from collections import defaultdict

from recipe_mcp.domain.models import (
    SENTIMENT_SCORE,
    Feedback,
    FeedbackSummary,
    Member,
    MemberFeedback,
    Sentiment,
)


def latest_by_member(feedback: list[Feedback]) -> dict[int, Feedback]:
    """The most recent feedback entry per member (later entries override)."""
    latest: dict[int, Feedback] = {}
    for entry in sorted(feedback, key=lambda f: (f.created_at, f.id or 0)):
        latest[entry.member_id] = entry
    return latest


def member_score(feedback: list[Feedback], member_id: int) -> float | None:
    latest = latest_by_member(feedback).get(member_id)
    if latest is None:
        return None
    return SENTIMENT_SCORE[latest.sentiment]


def household_score(feedback: list[Feedback], diners: list[int]) -> float | None:
    """Household preference is the *lowest* individual score among diners who rated.

    One person's enthusiasm never erases another person's dislike. Returns
    ``None`` when no diner has rated the recipe.
    """
    scores = [s for s in (member_score(feedback, m) for m in diners) if s is not None]
    if not scores:
        return None
    return min(scores)


def household_verdict(feedback: list[Feedback], member_ids: list[int]) -> str:
    latest = latest_by_member(feedback)
    rated = [latest[m].sentiment for m in member_ids if m in latest]
    if not rated:
        return "unrated"
    if any(s == Sentiment.DISLIKE for s in rated):
        return "one_dislikes" if len(rated) > 1 else "disliked"
    if len(rated) == len(member_ids) and len(member_ids) > 1:
        return "both_positive"
    return "positive"


def summarize(recipe_id: int, feedback: list[Feedback], members: list[Member]) -> FeedbackSummary:
    by_id = {m.id: m for m in members if m.id is not None}
    latest = latest_by_member(feedback)

    def key_of(member_id: int | None) -> str | None:
        if member_id is None:
            return None
        member = by_id.get(member_id)
        return member.member_key if member else str(member_id)

    entries = [
        MemberFeedback(
            member_id=member_id,
            member_key=key_of(member_id) or str(member_id),
            display_name=by_id[member_id].display_name if member_id in by_id else str(member_id),
            sentiment=entry.sentiment,
            notes=entry.notes,
            reported_by=key_of(entry.reported_by_member_id),
            created_at=entry.created_at,
        )
        for member_id, entry in sorted(latest.items())
    ]
    cooked = sorted((f.cooked_at for f in feedback if f.cooked_at), reverse=True)
    return FeedbackSummary(
        recipe_id=recipe_id,
        members=entries,
        household_verdict=household_verdict(
            feedback, [m.id for m in members if m.id is not None and m.active]
        ),
        times_cooked=len(cooked),
        last_cooked_at=cooked[0] if cooked else None,
    )


def facet_affinity(
    feedback_by_recipe: dict[int, list[Feedback]],
    facets_by_recipe: dict[int, list[tuple[str, str]]],
    member_id: int,
) -> dict[tuple[str, str], float]:
    """Average score a member has given to recipes carrying each (facet, value).

    Used to estimate whether an *uncooked* recipe is likely to suit someone.
    """
    totals: dict[tuple[str, str], list[float]] = defaultdict(list)
    for recipe_id, feedback in feedback_by_recipe.items():
        score = member_score(feedback, member_id)
        if score is None:
            continue
        for key in facets_by_recipe.get(recipe_id, []):
            totals[key].append(score)
    return {key: sum(values) / len(values) for key, values in totals.items()}
