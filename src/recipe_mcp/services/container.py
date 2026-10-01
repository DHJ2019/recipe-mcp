"""Wire settings, database, repositories and services into one application context."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from recipe_mcp.adapters.nyt.fetcher import (
    ChainedRecipeFetcher,
    HttpRecipeFetcher,
    HttpTitleFetcher,
    RecipeFetcher,
    TitleFetcher,
)
from recipe_mcp.db import Database, apply_migrations, connect
from recipe_mcp.db.migrations import DEFAULT_MIGRATIONS_DIR
from recipe_mcp.db.repositories import (
    AppStateRepository,
    FeedbackRepository,
    HouseholdRepository,
    MemberRepository,
    ModelRunRepository,
    PendingInteractionRepository,
    RecipeRepository,
)
from recipe_mcp.domain.models import Household, Member
from recipe_mcp.providers.base import ModelClient
from recipe_mcp.providers.caching import CachingModelClient
from recipe_mcp.providers.factory import build_model_client
from recipe_mcp.services.categorization import CategorizationService
from recipe_mcp.services.corrections import CorrectionService
from recipe_mcp.services.feedback import FeedbackService
from recipe_mcp.services.ingestion import IngestionService
from recipe_mcp.services.members import sync_members
from recipe_mcp.services.recommendation import RecommendationService
from recipe_mcp.services.whatsapp_import import WhatsAppImportService
from recipe_mcp.settings import Settings


def build_recipe_fetcher(settings: Settings) -> RecipeFetcher:
    """HTTP alone, or HTTP with the authenticated browser behind it when a signed-in
    NYT profile exists. Playwright is imported only in the second case."""
    http = HttpRecipeFetcher()
    if settings.missing_for("nyt_browser"):
        return http
    from recipe_mcp.adapters.nyt.browser import PlaywrightRecipeFetcher

    return ChainedRecipeFetcher(http, PlaywrightRecipeFetcher(settings.nyt_browser_profile_path))


@dataclass
class AppContext:
    settings: Settings
    db: Database
    household: Household
    households: HouseholdRepository
    members: MemberRepository
    recipes: RecipeRepository
    feedback: FeedbackRepository
    model_runs: ModelRunRepository
    pending: PendingInteractionRepository
    state: AppStateRepository
    categorization: CategorizationService
    ingestion: IngestionService
    recommendation: RecommendationService
    feedback_service: FeedbackService
    corrections: CorrectionService
    whatsapp_import: WhatsAppImportService
    _model: ModelClient | None = field(default=None, repr=False)
    _model_override: ModelClient | None = field(default=None, repr=False)

    @property
    def household_id(self) -> int:
        assert self.household.id is not None
        return self.household.id

    def model(self) -> ModelClient:
        """Build the model client on first use so read-only commands need no API key."""
        if self._model is None:
            inner = self._model_override or build_model_client(self.settings)
            self._model = CachingModelClient(inner, self.model_runs)
        return self._model

    def resolve_member(self, member: str | None) -> Member | None:
        """Member by key, display name or id; falls back to ``DEFAULT_MEMBER``."""
        key = (member or "").strip() or self.settings.default_member.strip()
        if not key:
            return None
        if key.isdigit():
            return self.members.get(int(key))
        return self.members.by_key(self.household_id, key) or self.members.by_name(
            self.household_id, key
        )

    def close(self) -> None:
        self.db.close()


def build_context(
    settings: Settings,
    *,
    fetcher: RecipeFetcher | None = None,
    title_fetcher: TitleFetcher | None = None,
    model: ModelClient | None = None,
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
) -> AppContext:
    db = connect(settings.database_path)
    apply_migrations(db, migrations_dir)
    households = HouseholdRepository(db)
    members = MemberRepository(db)
    recipes = RecipeRepository(db)
    feedback = FeedbackRepository(db)
    model_runs = ModelRunRepository(db)
    pending = PendingInteractionRepository(db)
    state = AppStateRepository(db)
    household = households.get_or_create_default()
    assert household.id is not None
    sync_members(members, settings.members_path, household.id)

    holder: dict[str, AppContext] = {}

    def model_factory() -> ModelClient:
        return holder["ctx"].model()

    categorization = CategorizationService(
        recipes, model_factory, settings.classification_confidence_threshold
    )
    ingestion = IngestionService(
        recipes,
        categorization,
        model_factory,
        fetcher or build_recipe_fetcher(settings),
        household.id,
        title_fetcher=title_fetcher if title_fetcher is not None else HttpTitleFetcher(),
    )
    recommendation = RecommendationService(recipes, feedback, members, model_factory, household.id)
    feedback_service = FeedbackService(recipes, feedback, members, household.id)
    private_evals = settings.private_evals_path if settings.app_env != "test" else None
    corrections = CorrectionService(recipes, categorization, private_evals)
    ctx = AppContext(
        settings=settings,
        db=db,
        household=household,
        households=households,
        members=members,
        recipes=recipes,
        feedback=feedback,
        model_runs=model_runs,
        pending=pending,
        state=state,
        categorization=categorization,
        ingestion=ingestion,
        recommendation=recommendation,
        feedback_service=feedback_service,
        corrections=corrections,
        whatsapp_import=WhatsAppImportService(ingestion, members, household.id),
        _model_override=model,
    )
    holder["ctx"] = ctx
    return ctx
