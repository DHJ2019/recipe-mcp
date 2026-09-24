"""Domain models shared by services, repositories and adapters."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from recipe_mcp.domain.taxonomy import Facet


def utcnow_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class SourceType(StrEnum):
    NYT = "nyt"
    PERSONAL = "personal"
    OTHER = "other"


class RecipeStatus(StrEnum):
    DRAFT = "draft"
    COMPLETE = "complete"


class FacetSource(StrEnum):
    PARSED = "parsed"
    RULE = "rule"
    MODEL = "model"
    USER = "user"


class Sentiment(StrEnum):
    LOVE = "love"
    LIKE = "like"
    DISLIKE = "dislike"


SENTIMENT_SCORE: dict[Sentiment, float] = {
    Sentiment.LOVE: 2.0,
    Sentiment.LIKE: 1.0,
    Sentiment.DISLIKE: -2.0,
}


FOOD_TYPES: tuple[str, ...] = ("meat", "fish", "shellfish", "dairy", "egg")


class IngredientFlags(BaseModel):
    contains_meat: bool = False
    contains_fish: bool = False
    contains_shellfish: bool = False
    contains_dairy: bool = False
    contains_egg: bool = False

    def merge(self, other: IngredientFlags) -> IngredientFlags:
        return IngredientFlags(
            contains_meat=self.contains_meat or other.contains_meat,
            contains_fish=self.contains_fish or other.contains_fish,
            contains_shellfish=self.contains_shellfish or other.contains_shellfish,
            contains_dairy=self.contains_dairy or other.contains_dairy,
            contains_egg=self.contains_egg or other.contains_egg,
        )

    def food_types(self) -> list[str]:
        """The food types present, in :data:`FOOD_TYPES` order ("meat", "shellfish")."""
        return [t for t in FOOD_TYPES if getattr(self, f"contains_{t}")]

    @classmethod
    def from_food_types(cls, food_types: list[str]) -> IngredientFlags:
        unknown = sorted(set(food_types) - set(FOOD_TYPES))
        if unknown:
            raise ValueError(
                f"unknown food type(s): {', '.join(unknown)}; allowed: {', '.join(FOOD_TYPES)}"
            )
        return cls(**{f"contains_{t}": True for t in food_types})


class RecipeIngredient(BaseModel):
    canonical_name: str
    raw_text: str
    quantity: str | None = None
    preparation: str | None = None
    category: str = "other"
    is_staple: bool = False
    flags: IngredientFlags = Field(default_factory=IngredientFlags)
    food_types_override: IngredientFlags | None = None
    """A person's correction for this recipe only; the lexicon ``flags`` stay shared."""

    @property
    def effective_flags(self) -> IngredientFlags:
        return self.food_types_override if self.food_types_override is not None else self.flags


class Classification(BaseModel):
    facet: Facet
    value: str
    source: FacetSource
    confidence: float = 1.0
    model_version: str | None = None
    prompt_version: str | None = None
    user_confirmed: bool = False
    needs_review: bool = False
    proposed_value: str | None = None


class Household(BaseModel):
    id: int | None = None
    name: str
    created_at: str = Field(default_factory=utcnow_iso)


class Member(BaseModel):
    id: int | None = None
    household_id: int
    member_key: str
    display_name: str
    telegram_user_id: int | None = None
    whatsapp_export_name: str | None = None
    normalized_phone_number: str | None = None
    role: str = "member"
    active: bool = True


class Recipe(BaseModel):
    id: int | None = None
    household_id: int
    source_type: SourceType
    canonical_source_url: str | None = None
    title: str
    servings: str | None = None
    total_minutes: int | None = None
    notes: list[str] = Field(default_factory=list)
    status: RecipeStatus = RecipeStatus.COMPLETE
    content_hash: str = ""
    added_by_member_id: int | None = None
    added_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)
    ingredients: list[RecipeIngredient] = Field(default_factory=list)
    classifications: list[Classification] = Field(default_factory=list)

    @property
    def flags(self) -> IngredientFlags:
        flags = IngredientFlags()
        for ingredient in self.ingredients:
            flags = flags.merge(ingredient.effective_flags)
        return flags

    def facet_values(self, facet: Facet) -> list[str]:
        """Values for a facet, with user-confirmed classifications taking precedence."""
        confirmed = [c.value for c in self.classifications if c.facet == facet and c.user_confirmed]
        if confirmed:
            return confirmed
        return [c.value for c in self.classifications if c.facet == facet and c.value]

    def facet_needs_review(self, facet: Facet) -> bool:
        """True when the facet's shown values rest on a low-confidence guess."""
        relevant = [c for c in self.classifications if c.facet == facet and c.value]
        if any(c.user_confirmed for c in relevant):
            return False
        return any(c.needs_review for c in relevant)

    @property
    def is_recommendable(self) -> bool:
        """Link stubs (unsupported sites) have no ingredients and are never recommended."""
        return bool(self.ingredients)

    def classification_summary(self) -> dict[str, list[str]]:
        summary: dict[str, list[str]] = {}
        for facet in Facet:
            values = self.facet_values(facet)
            if values:
                summary[facet.value] = values
        return summary

    def compute_content_hash(self) -> str:
        parts = [self.title.strip().lower()]
        parts.extend(sorted(i.canonical_name for i in self.ingredients))
        digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
        return digest[:32]


class Feedback(BaseModel):
    id: int | None = None
    recipe_id: int
    member_id: int
    reported_by_member_id: int | None = None
    sentiment: Sentiment
    notes: str | None = None
    cooked_at: str | None = None
    created_at: str = Field(default_factory=utcnow_iso)


class MemberFeedback(BaseModel):
    member_id: int
    member_key: str
    display_name: str
    sentiment: Sentiment
    notes: str | None = None
    reported_by: str | None = None
    created_at: str


class FeedbackSummary(BaseModel):
    recipe_id: int
    members: list[MemberFeedback] = Field(default_factory=list)
    household_verdict: str = "unrated"
    times_cooked: int = 0
    last_cooked_at: str | None = None


class RecommendationRequest(BaseModel):
    dietary: list[str] = Field(default_factory=list)
    cuisine: str | None = None
    dish_type: str | None = None
    main_ingredient: str | None = None
    """What the dish is built around: an ingredient ("mushroom") or a group ("beans")."""
    character: list[str] = Field(default_factory=list)
    max_minutes: int | None = None
    available_ingredients: list[str] = Field(default_factory=list)
    excluded_ingredients: list[str] = Field(default_factory=list)
    max_missing: int | None = None
    diners: list[int] = Field(default_factory=list)
    """Member ids whose preferences apply. Internal: MCP exposes ``member`` instead."""
    exclude_recent_days: int | None = None
    limit: int = 3


class RecommendationResult(BaseModel):
    recipe_id: int
    title: str
    total_minutes: int | None
    status: RecipeStatus
    classifications: dict[str, list[str]]
    contains: list[str] = Field(default_factory=list)
    """Food types behind the dietary label: meat, fish, shellfish, dairy, egg."""
    adapted_for: str | None = None
    """Set when the recipe meets the requested diet or excluded food types only through
    the author's own choices ("vegan", "no dairy"); ``diet_swaps`` says which
    ("use vegetable broth")."""
    diet_swaps: list[str] = Field(default_factory=list)
    ingredients_available: list[str]
    ingredients_missing: list[str]
    reasons: list[str]
    score: float
    source_url: str | None
    household_fit: str | None = None


class ModelRun(BaseModel):
    id: int | None = None
    task: str
    input_hash: str
    provider: str
    model: str
    prompt_version: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    validation_status: str = "ok"
    created_at: str = Field(default_factory=utcnow_iso)
