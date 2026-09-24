from recipe_mcp.domain import feedback as fb
from recipe_mcp.domain.models import Feedback, Member, Sentiment
from recipe_mcp.services.feedback import parse_sentiment

MEMBERS = [
    Member(id=1, household_id=1, member_key="alex", display_name="Alex"),
    Member(id=2, household_id=1, member_key="sam", display_name="Sam"),
]


def _f(member: int, sentiment: Sentiment, created: str, fid: int) -> Feedback:
    return Feedback(id=fid, recipe_id=1, member_id=member, sentiment=sentiment, created_at=created)


def test_latest_entry_per_member_wins() -> None:
    entries = [
        _f(1, Sentiment.LIKE, "2026-01-01T00:00:00+00:00", 1),
        _f(1, Sentiment.DISLIKE, "2026-02-01T00:00:00+00:00", 2),
    ]
    assert fb.member_score(entries, 1) == -2.0


def test_household_score_is_minimum_of_diners() -> None:
    entries = [
        _f(1, Sentiment.LOVE, "2026-01-01T00:00:00+00:00", 1),
        _f(2, Sentiment.LIKE, "2026-01-01T00:00:00+00:00", 2),
    ]
    assert fb.household_score(entries, [1, 2]) == 1.0
    assert fb.household_score(entries, [3]) is None


def test_verdicts() -> None:
    love = _f(1, Sentiment.LOVE, "2026-01-01T00:00:00+00:00", 1)
    like = _f(2, Sentiment.LIKE, "2026-01-01T00:00:00+00:00", 2)
    dislike = _f(2, Sentiment.DISLIKE, "2026-01-01T00:00:00+00:00", 3)
    assert fb.household_verdict([], [1, 2]) == "unrated"
    assert fb.household_verdict([love, like], [1, 2]) == "both_positive"
    assert fb.household_verdict([love], [1, 2]) == "positive"
    assert fb.household_verdict([love, dislike], [1, 2]) == "one_dislikes"


def test_summary_uses_display_names() -> None:
    entries = [_f(1, Sentiment.LOVE, "2026-01-01T00:00:00+00:00", 1)]
    summary = fb.summarize(1, entries, MEMBERS)
    assert summary.members[0].display_name == "Alex"
    assert summary.members[0].member_key == "alex"
    assert summary.members[0].reported_by is None
    assert summary.household_verdict == "positive"


def test_summary_records_who_reported() -> None:
    entry = Feedback(
        id=1,
        recipe_id=1,
        member_id=2,
        reported_by_member_id=1,
        sentiment=Sentiment.DISLIKE,
        created_at="2026-01-01T00:00:00+00:00",
    )
    summary = fb.summarize(1, [entry], MEMBERS)
    assert summary.members[0].member_key == "sam"
    assert summary.members[0].reported_by == "alex"
    assert summary.household_verdict == "disliked"


def test_parse_sentiment_from_emoji_and_words() -> None:
    assert parse_sentiment("❤️") == Sentiment.LOVE
    assert parse_sentiment("👍 pretty good") == Sentiment.LIKE
    assert parse_sentiment("👎") == Sentiment.DISLIKE
    assert parse_sentiment("We both loved this") == Sentiment.LOVE
    assert parse_sentiment("Don't recommend this to me again") == Sentiment.DISLIKE
    assert parse_sentiment("what's for dinner?") is None
