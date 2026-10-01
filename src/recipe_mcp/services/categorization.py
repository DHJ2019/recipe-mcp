"""Categorization workflow: deterministic extraction -> model proposal -> validation.

Classifications below the configured confidence threshold are still saved but
flagged ``needs_review`` so they appear in the review report and are marked in
confirmations with ``?``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from recipe_mcp.db.repositories import RecipeRepository
from recipe_mcp.domain import dietary, taxonomy
from recipe_mcp.domain.ingredients import ingredient_matches, normalize_ingredients
from recipe_mcp.domain.models import Classification, FacetSource, Recipe
from recipe_mcp.domain.taxonomy import Facet
from recipe_mcp.providers.base import (
    FacetConfidence,
    ModelClient,
    RecipeClassification,
    RecipeClassificationInput,
)
from recipe_mcp.settings import MissingConfigError

DEFAULT_CONFIDENCE_THRESHOLD = 0.8
AGENT_CONFIDENCE = 0.85


@dataclass
class CategorizationOutcome:
    recipe: Recipe
    classifications: list[Classification]
    needs_review: bool = False
    warnings: list[str] = field(default_factory=list)
    proposed_values: dict[str, str] = field(default_factory=dict)


@dataclass
class DietaryRefresh:
    """One recipe whose re-parsed ingredients or dietary labels differ from storage."""

    recipe_id: int
    title: str
    before: list[str]
    after: list[str]
    removed: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)

    @property
    def dietary_changed(self) -> bool:
        return self.before != self.after


@dataclass
class TaxonomyMove:
    """A stored ``other`` whose proposed value is now in the vocabulary."""

    recipe_id: int
    title: str
    facet: Facet
    value: str


@dataclass
class TaxonomyRefresh:
    moves: list[TaxonomyMove] = field(default_factory=list)
    # Proposed values still parked under ``other``: facet -> {proposed value: recipes}.
    remaining: dict[Facet, dict[str, int]] = field(default_factory=dict)


def dietary_classifications(recipe: Recipe) -> list[Classification]:
    return [
        Classification(facet=Facet.DIETARY, value=diet, source=FacetSource.RULE, confidence=1.0)
        for diet in dietary.allowed_diets(recipe.flags)
    ]


def rule_classifications(recipe: Recipe) -> list[Classification]:
    """Classifications that never involve a model: dietary rules, time buckets and
    parsed source hints carried forward from ingestion."""
    result = dietary_classifications(recipe)
    result.extend(
        c
        for c in recipe.classifications
        if c.source == FacetSource.PARSED and c.facet not in {Facet.EFFORT, Facet.DIETARY}
    )
    effort = taxonomy.effort_for_minutes(recipe.total_minutes)
    if effort:
        result.append(
            Classification(
                facet=Facet.EFFORT, value=effort, source=FacetSource.PARSED, confidence=1.0
            )
        )
    return result


def _diet_cell(recipe: Recipe) -> str:
    """ "omnivore (can be vegan)" in the review report."""
    diet = dietary.strictest(recipe.facet_values(Facet.DIETARY)) or ""
    options = dietary.can_be_made(recipe)
    return f"{diet} (can be {next(iter(options))})" if options else diet


class CategorizationService:
    def __init__(
        self,
        recipes: RecipeRepository,
        model_factory: Callable[[], ModelClient],
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ) -> None:
        self.recipes = recipes
        self._model_factory = model_factory
        self.threshold = confidence_threshold

    def classify(self, recipe: Recipe) -> CategorizationOutcome:
        """Compute classifications for a recipe without persisting them.

        With no model configured (the agent-brain setup) only the deterministic rules
        apply and the outcome is flagged for review so the agent can propose facets.
        """
        outcome = CategorizationOutcome(recipe=recipe, classifications=rule_classifications(recipe))
        parsed_cuisine = next(
            (c.value for c in outcome.classifications if c.facet == Facet.CUISINE), None
        )
        try:
            model = self._model_factory()
        except MissingConfigError:
            outcome.needs_review = True
            outcome.warnings.append(
                "not classified: no model configured; an agent can propose facets with "
                "correct_recipe(proposed_by_agent=true)"
            )
            return outcome
        response = model.classify_recipe(
            RecipeClassificationInput(
                title=recipe.title,
                ingredients=list(dict.fromkeys(i.raw_text for i in recipe.ingredients)),
                total_minutes=recipe.total_minutes,
                source_cuisine=parsed_cuisine,
                notes=recipe.notes,
            )
        )
        return self._apply_proposal(
            outcome, response.output, response.model, response.prompt_version
        )

    def proposal_from_facets(
        self, facets: Mapping[str, list[str] | str], confidence: float = AGENT_CONFIDENCE
    ) -> RecipeClassification:
        """Build a classification proposal from an agent's facet dictionary."""

        def many(key: str) -> list[str]:
            raw = facets.get(key, [])
            return [str(v) for v in (raw if isinstance(raw, list) else [raw]) if str(v).strip()]

        def one(key: str) -> str | None:
            values = many(key)
            return values[0] if values else None

        return RecipeClassification(
            cuisine=one("cuisine") or taxonomy.OTHER,
            dish_type=one("dish_type") or taxonomy.OTHER,
            meal=many("meal"),
            primary_ingredients=many("primary_ingredient") + many("primary_ingredients"),
            effort=one("effort"),
            character=many("character"),
            cooking_method=one("cooking_method"),
            health_orientation=one("health_orientation"),
            confidence=confidence,
            facet_confidence=FacetConfidence(
                cuisine=confidence,
                dish_type=confidence,
                meal=confidence,
                primary_ingredient=confidence,
                effort=confidence,
                character=confidence,
                cooking_method=confidence,
                health_orientation=confidence,
            ),
        )

    def apply_agent_proposal(
        self, recipe: Recipe, facets: Mapping[str, list[str] | str], agent: str = "agent"
    ) -> CategorizationOutcome:
        """Persist an MCP client agent's classification proposal (model-grade, not user)."""
        assert recipe.id is not None
        outcome = CategorizationOutcome(recipe=recipe, classifications=rule_classifications(recipe))
        outcome = self._apply_proposal(outcome, self.proposal_from_facets(facets), agent, "agent")
        self.recipes.replace_classifications(recipe.id, outcome.classifications, keep_user=True)
        refreshed = self.recipes.get(recipe.id)
        if refreshed is not None:
            outcome.recipe = refreshed
        return outcome

    def _apply_proposal(
        self,
        outcome: CategorizationOutcome,
        proposal: RecipeClassification,
        model_version: str,
        prompt_version: str,
    ) -> CategorizationOutcome:
        recipe = outcome.recipe
        threshold = self.threshold

        _, rejected = dietary.validate_claims(proposal.dietary_suitability, recipe.flags)
        if rejected:
            outcome.warnings.append(
                "rejected dietary claim(s) contradicted by ingredients: " + ", ".join(rejected)
            )

        def make(facet: Facet, value: str, proposed: str | None) -> Classification:
            confidence = proposal.facet_confidence.for_facet(facet.name.lower())
            flagged = confidence < threshold
            if flagged:
                outcome.needs_review = True
            return Classification(
                facet=facet,
                value=value,
                source=FacetSource.MODEL,
                confidence=confidence,
                model_version=model_version,
                prompt_version=prompt_version,
                needs_review=flagged,
                proposed_value=proposed,
            )

        def add_single(facet: Facet, raw: str | None) -> None:
            if not raw:
                return
            value, proposed = taxonomy.normalize_value(facet, raw)
            if proposed:
                outcome.proposed_values[facet.value] = proposed
            parsed_values = {c.value for c in outcome.classifications if c.facet == facet}
            if value in parsed_values or (value == taxonomy.OTHER and parsed_values):
                return  # keep the parsed source hint; it is stable across re-runs
            if value:
                outcome.classifications.append(make(facet, value, proposed))

        def add_multi(facet: Facet, raws: list[str]) -> None:
            seen: set[str] = set()
            for raw in raws:
                value, proposed = taxonomy.normalize_value(facet, raw)
                if proposed:
                    outcome.proposed_values[facet.value] = proposed
                if value and value not in seen:
                    seen.add(value)
                    outcome.classifications.append(make(facet, value, proposed))

        add_single(Facet.CUISINE, proposal.cuisine)
        add_single(Facet.DISH_TYPE, proposal.dish_type)
        add_multi(Facet.MEAL, proposal.meal)
        add_multi(Facet.CHARACTER, proposal.character)
        add_single(Facet.COOKING_METHOD, proposal.cooking_method)
        add_single(Facet.HEALTH, proposal.health_orientation)
        if recipe.total_minutes is None:
            add_single(Facet.EFFORT, proposal.effort)

        # Primary ingredients must be grounded in the actual ingredient list.
        grounded: list[str] = []
        for candidate in proposal.primary_ingredients:
            name = candidate.strip().lower()
            if any(ingredient_matches(name, i.canonical_name) for i in recipe.ingredients):
                if name not in grounded:
                    grounded.append(name)
            else:
                outcome.warnings.append(f"ignored primary ingredient not in recipe: {name}")
        add_multi(Facet.PRIMARY_INGREDIENT, grounded)

        if outcome.proposed_values:
            outcome.needs_review = True
        return outcome

    def categorize(self, recipe: Recipe) -> CategorizationOutcome:
        """Classify and persist, keeping any user-confirmed values."""
        assert recipe.id is not None
        outcome = self.classify(recipe)
        self.recipes.replace_classifications(recipe.id, outcome.classifications, keep_user=True)
        refreshed = self.recipes.get(recipe.id)
        if refreshed is not None:
            outcome.recipe = refreshed
        return outcome

    def categorize_uncategorized(self, household_id: int) -> list[CategorizationOutcome]:
        return [self.categorize(r) for r in self.recipes.list_uncategorized(household_id)]

    def refresh_rules(self, recipe: Recipe) -> Recipe:
        """Re-run the deterministic rules only (after an ingredient or time change)."""
        assert recipe.id is not None
        rules = [
            c
            for c in rule_classifications(recipe)
            if c.source in {FacetSource.RULE, FacetSource.PARSED}
        ]
        keep = [
            c
            for c in recipe.classifications
            if c.source == FacetSource.MODEL and c.facet not in {Facet.DIETARY, Facet.EFFORT}
        ]
        self.recipes.replace_classifications(recipe.id, [*rules, *keep], keep_user=True)
        refreshed = self.recipes.get(recipe.id)
        assert refreshed is not None
        return refreshed

    def refresh_taxonomy(self, household_id: int, apply: bool = False) -> TaxonomyRefresh:
        """Move stored ``other`` values onto vocabulary added since they were stored.

        Deterministic: a value moves only when its recorded proposal now normalizes to
        a vocabulary value. Source and confirmation are kept, so a person's correction
        stays theirs. With ``apply=False`` nothing is written.
        """
        result = TaxonomyRefresh()
        for recipe in self.recipes.list_for_household(household_id):
            if recipe.id is None:
                continue
            for c in recipe.classifications:
                if c.value != taxonomy.OTHER or not c.proposed_value:
                    continue
                value, _ = taxonomy.normalize_value(c.facet, c.proposed_value)
                if not value or value == taxonomy.OTHER:
                    counts = result.remaining.setdefault(c.facet, {})
                    counts[c.proposed_value] = counts.get(c.proposed_value, 0) + 1
                    continue
                result.moves.append(TaxonomyMove(recipe.id, recipe.title, c.facet, value))
                if apply:
                    self.recipes.move_other_value(recipe.id, c.facet, value)
        return result

    def refresh_dietary(self, household_id: int, apply: bool = False) -> list[DietaryRefresh]:
        """Re-parse stored ingredient lines and re-run the dietary rules.

        Run after the ingredient parser or lexicons change. Only ingredient rows and the
        rule-derived dietary facet are rewritten; model, agent and user classifications
        for every other facet stay as they are. With ``apply=False`` nothing is written.
        """
        changes: list[DietaryRefresh] = []
        for recipe in self.recipes.list_for_household(household_id):
            if recipe.id is None or not recipe.is_recommendable:
                continue
            reparsed = normalize_ingredients([i.raw_text for i in recipe.ingredients])
            overrides = {i.canonical_name: i.food_types_override for i in recipe.ingredients}
            for ingredient in reparsed:
                ingredient.food_types_override = overrides.get(ingredient.canonical_name)
            ingredients_changed = [
                (i.canonical_name, i.preparation, i.flags) for i in recipe.ingredients
            ] != [(i.canonical_name, i.preparation, i.flags) for i in reparsed]
            stored = recipe.facet_values(Facet.DIETARY)
            before = [d for d in dietary.DIET_ORDER if d in stored]
            before += sorted(d for d in stored if d not in dietary.DIET_ORDER)
            after = dietary.allowed_diets(dietary.flags_for(reparsed))
            if not ingredients_changed and before == after:
                continue
            old_names = [i.canonical_name for i in recipe.ingredients]
            new_names = [i.canonical_name for i in reparsed]
            changes.append(
                DietaryRefresh(
                    recipe_id=recipe.id,
                    title=recipe.title,
                    before=before,
                    after=after,
                    removed=[n for n in old_names if n not in new_names],
                    added=[n for n in new_names if n not in old_names],
                )
            )
            if not apply:
                continue
            if ingredients_changed:
                recipe.ingredients = reparsed
                self.recipes.update(recipe)
            self.recipes.replace_facet(recipe.id, Facet.DIETARY, dietary_classifications(recipe))
        return changes

    def report(self, household_id: int) -> str:
        """Markdown review report of every recipe and its proposed classifications."""
        lines = [
            "# Categorization review",
            "",
            "| id | title | dietary | cuisine | dish | character | time | conf | review |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        stubs: list[Recipe] = []
        for recipe in self.recipes.list_for_household(household_id):
            if not recipe.is_recommendable:
                stubs.append(recipe)
                continue
            model_conf = [
                c.confidence for c in recipe.classifications if c.source == FacetSource.MODEL
            ]
            conf = min(model_conf) if model_conf else None
            flagged = sorted({c.facet.value for c in recipe.classifications if c.needs_review})
            proposed = [c.proposed_value for c in recipe.classifications if c.proposed_value]
            review_bits: list[str] = []
            if flagged:
                review_bits.append("review: " + ", ".join(flagged))
            if proposed:
                review_bits.append("proposed: " + ", ".join(p for p in proposed if p))
            if not model_conf:
                review_bits.append("uncategorized")
            lines.append(
                "| {id} | {title} | {diet} | {cuisine} | {dish} | {char} | {time} | {conf} "
                "| {review} |".format(
                    id=recipe.id,
                    title=recipe.title.replace("|", "/"),
                    diet=_diet_cell(recipe),
                    cuisine=", ".join(recipe.facet_values(Facet.CUISINE)),
                    dish=", ".join(recipe.facet_values(Facet.DISH_TYPE)),
                    char=", ".join(recipe.facet_values(Facet.CHARACTER)),
                    time=recipe.total_minutes if recipe.total_minutes is not None else "?",
                    conf=f"{conf:.2f}" if conf is not None else "",
                    review="; ".join(review_bits),
                )
            )
        if stubs:
            lines += ["", "## Unsupported links (stored, not categorized)", ""]
            lines += [f"- {s.id}: {s.title} — {s.canonical_source_url}" for s in stubs]
        lines.append("")
        lines.append("Correct a row with: `recipe-mcp correct <id> <facet> <value>`")
        return "\n".join(lines)
