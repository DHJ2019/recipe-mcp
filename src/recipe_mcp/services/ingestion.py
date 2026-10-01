"""Save recipes from a supported URL or informal text. Idempotent for canonical URLs.

Links to sites other than NYT Cooking are stored as ``source_type: other`` stubs
(URL plus page title when fetchable) so the collection is complete, but they are
neither categorized nor recommended.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from recipe_mcp.adapters.nyt.fetcher import FetchError, RecipeFetcher, TitleFetcher
from recipe_mcp.adapters.nyt.jsonld import ParsedRecipe, parse_recipe_jsonld
from recipe_mcp.db.repositories import RecipeRepository
from recipe_mcp.domain import dietary, limits, taxonomy
from recipe_mcp.domain.ingredients import normalize_ingredients
from recipe_mcp.domain.models import Classification, FacetSource, Recipe, RecipeStatus, SourceType
from recipe_mcp.domain.taxonomy import Facet
from recipe_mcp.domain.urls import (
    UrlKind,
    canonicalize_url,
    classify_url,
    extract_urls,
    looks_like_url,
)
from recipe_mcp.providers.base import ModelClient
from recipe_mcp.services.categorization import CategorizationService
from recipe_mcp.settings import MissingConfigError


class IngestionError(RuntimeError):
    pass


@dataclass
class SaveResult:
    recipe: Recipe
    created: bool
    warnings: list[str] = field(default_factory=list)
    needs_review: bool = False

    def confirmation(self) -> str:
        """Compact confirmation used by Telegram and MCP. Low-confidence facets get ``?``."""
        r = self.recipe
        verb = "Saved" if self.created else "Already saved"
        if not r.is_recommendable:
            return (
                f"{verb} link: {r.title}\n{r.canonical_source_url}\n"
                "Not an NYT recipe; kept for reference only."
            )

        def facet(f: Facet, text: str) -> str:
            return f"{text}?" if text and r.facet_needs_review(f) else text

        def shown(f: Facet) -> str:
            # "other" means nothing in the vocabulary fits; not worth a place in the reply.
            return ", ".join(v for v in r.facet_values(f) if v != taxonomy.OTHER)

        bits = [
            (dietary.strictest(r.facet_values(Facet.DIETARY)) or "").capitalize(),
            facet(Facet.CUISINE, shown(Facet.CUISINE).capitalize()),
            facet(Facet.DISH_TYPE, shown(Facet.DISH_TYPE)),
            facet(Facet.CHARACTER, shown(Facet.CHARACTER)),
            f"{r.total_minutes} minutes" if r.total_minutes else "time unknown",
        ]
        status = " (draft)" if r.status == RecipeStatus.DRAFT else ""
        return f"{verb}: {r.title}{status}\n" + " · ".join(b for b in bits if b)


class IngestionService:
    def __init__(
        self,
        recipes: RecipeRepository,
        categorizer: CategorizationService,
        model_factory: Callable[[], ModelClient],
        fetcher: RecipeFetcher,
        household_id: int,
        title_fetcher: TitleFetcher | None = None,
    ) -> None:
        self.recipes = recipes
        self.categorizer = categorizer
        self._model_factory = model_factory
        self.fetcher = fetcher
        self.title_fetcher = title_fetcher
        self.household_id = household_id

    def save(self, text: str, notes: str | None = None, member_id: int | None = None) -> SaveResult:
        try:
            limits.check_text("input", text, limits.MAX_INPUT_CHARS)
            limits.check_text("notes", notes, limits.MAX_NOTE_CHARS)
        except limits.InputTooLarge as exc:
            raise IngestionError(str(exc)) from exc
        urls = extract_urls(text)
        if urls and (looks_like_url(text) or classify_url(urls[0]) != UrlKind.OTHER):
            return self.save_url(urls[0], notes=notes, member_id=member_id)
        return self.save_personal(text, notes=notes, member_id=member_id)

    # -- URL path ---------------------------------------------------------

    def save_url(
        self, url: str, notes: str | None = None, member_id: int | None = None
    ) -> SaveResult:
        kind = classify_url(url)
        if kind == UrlKind.INVALID:
            raise IngestionError(f"not a valid http(s) URL: {url}")
        if kind == UrlKind.OTHER:
            return self._save_unsupported(url, notes, member_id)
        canonical = canonicalize_url(url)
        existing = self.recipes.find_by_url(self.household_id, canonical)
        if existing is not None:
            return SaveResult(recipe=existing, created=False, warnings=["duplicate URL"])
        try:
            fetched = self.fetcher.fetch(url)
        except FetchError as exc:
            raise IngestionError(str(exc)) from exc
        # The redirect target may differ from the guessed canonical form (short links).
        existing = self.recipes.find_by_url(self.household_id, fetched.canonical_url)
        if existing is not None:
            return SaveResult(recipe=existing, created=False, warnings=["duplicate URL"])
        parsed = parse_recipe_jsonld(fetched.html)
        if parsed is None or not parsed.ingredients:
            raise IngestionError(
                "no usable schema.org Recipe data on the page (authentication may be required)"
            )
        recipe = self._recipe_from_parsed(parsed, fetched.canonical_url, notes, member_id)
        return self._store_and_categorize(recipe)

    def _save_unsupported(self, url: str, notes: str | None, member_id: int | None) -> SaveResult:
        canonical = canonicalize_url(url)
        existing = self.recipes.find_by_url(self.household_id, canonical)
        if existing is not None:
            return SaveResult(recipe=existing, created=False, warnings=["duplicate URL"])
        title = None
        if self.title_fetcher is not None:
            title = self.title_fetcher.fetch_title(url)
        recipe = Recipe(
            household_id=self.household_id,
            source_type=SourceType.OTHER,
            canonical_source_url=canonical,
            title=title or canonical,
            notes=[notes] if notes else [],
            status=RecipeStatus.COMPLETE,
            added_by_member_id=member_id,
        )
        stored = self.recipes.create(recipe)
        return SaveResult(
            recipe=stored,
            created=True,
            warnings=["unsupported site: stored as a link only, not categorized"],
        )

    @staticmethod
    def _parsed_classifications(parsed: ParsedRecipe) -> list[Classification]:
        """Source metadata (cuisine, category) kept as parsed hints."""
        hints: list[Classification] = []
        pairs = ((Facet.CUISINE, parsed.cuisine), (Facet.MEAL, parsed.category))
        for facet, raw in pairs:
            if not raw:
                continue
            value, _ = taxonomy.normalize_value(facet, raw)
            if value and value != taxonomy.OTHER:
                hints.append(
                    Classification(
                        facet=facet, value=value, source=FacetSource.PARSED, confidence=0.7
                    )
                )
        return hints

    def _recipe_from_parsed(
        self, parsed: ParsedRecipe, canonical_url: str, notes: str | None, member_id: int | None
    ) -> Recipe:
        return Recipe(
            household_id=self.household_id,
            source_type=SourceType.NYT,
            canonical_source_url=canonical_url,
            title=parsed.title,
            servings=parsed.servings,
            total_minutes=parsed.total_minutes,
            notes=[notes] if notes else [],
            status=RecipeStatus.COMPLETE,
            added_by_member_id=member_id,
            ingredients=normalize_ingredients(parsed.ingredients),
            classifications=self._parsed_classifications(parsed),
        )

    # -- personal path ----------------------------------------------------

    def save_structured(
        self,
        title: str,
        ingredients: list[str],
        *,
        total_minutes: int | None = None,
        servings: str | None = None,
        notes: list[str] | None = None,
        classifications: Mapping[str, list[str] | str] | None = None,
        member_id: int | None = None,
        agent: str = "agent",
    ) -> SaveResult:
        """Save a recipe an MCP client agent has already parsed. No model is involved."""
        try:
            limits.check_recipe_fields(
                title=title, ingredients=ingredients, notes=notes or [], servings=servings
            )
            limits.check_facets("classifications", classifications)
        except limits.InputTooLarge as exc:
            raise IngestionError(str(exc)) from exc
        cleaned = [i.strip() for i in ingredients if i and i.strip()]
        if not title.strip():
            raise IngestionError("title is required")
        if not cleaned:
            raise IngestionError("at least one ingredient is required")
        recipe = Recipe(
            household_id=self.household_id,
            source_type=SourceType.PERSONAL,
            title=title.strip(),
            servings=str(servings) if servings else None,
            total_minutes=total_minutes,
            notes=[n.strip() for n in notes or [] if n and n.strip()],
            status=RecipeStatus.COMPLETE if total_minutes else RecipeStatus.DRAFT,
            added_by_member_id=member_id,
            ingredients=normalize_ingredients(cleaned),
        )
        recipe.content_hash = recipe.compute_content_hash()
        existing = self.recipes.find_by_content_hash(self.household_id, recipe.content_hash)
        if existing is not None:
            return SaveResult(recipe=existing, created=False, warnings=["duplicate recipe"])
        stored = self.recipes.create(recipe)
        if classifications:
            outcome = self.categorizer.apply_agent_proposal(stored, classifications, agent)
        else:
            outcome = self.categorizer.categorize(stored)
        return SaveResult(
            recipe=outcome.recipe,
            created=True,
            warnings=outcome.warnings,
            needs_review=outcome.needs_review,
        )

    def save_personal(
        self, text: str, notes: str | None = None, member_id: int | None = None
    ) -> SaveResult:
        try:
            draft = self._model_factory().parse_personal_recipe(text).output
        except MissingConfigError as exc:
            raise IngestionError(
                "no model is configured to parse free text; pass title and ingredients "
                "explicitly (the MCP client agent should parse the description)"
            ) from exc
        if not draft.ingredients:
            raise IngestionError("could not identify any ingredients in the description")
        all_notes = [*draft.notes]
        if notes:
            all_notes.append(notes)
        recipe = Recipe(
            household_id=self.household_id,
            source_type=SourceType.PERSONAL,
            title=draft.title,
            servings=draft.servings,
            total_minutes=draft.total_minutes,
            notes=all_notes,
            status=RecipeStatus.DRAFT,
            added_by_member_id=member_id,
            ingredients=normalize_ingredients(draft.ingredients),
        )
        recipe.content_hash = recipe.compute_content_hash()
        existing = self.recipes.find_by_content_hash(self.household_id, recipe.content_hash)
        if existing is not None:
            return SaveResult(recipe=existing, created=False, warnings=["duplicate recipe"])
        return self._store_and_categorize(recipe)

    # -- shared -----------------------------------------------------------

    def _store_and_categorize(self, recipe: Recipe) -> SaveResult:
        stored = self.recipes.create(recipe)
        outcome = self.categorizer.categorize(stored)
        return SaveResult(
            recipe=outcome.recipe,
            created=True,
            warnings=outcome.warnings,
            needs_review=outcome.needs_review,
        )
