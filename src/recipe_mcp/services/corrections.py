"""Apply user corrections. Every correction becomes a private regression case."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from recipe_mcp.db.repositories import RecipeRepository
from recipe_mcp.domain import limits, taxonomy
from recipe_mcp.domain.ingredients import canonical_name, ingredient_matches, normalize_line
from recipe_mcp.domain.models import (
    IngredientFlags,
    Recipe,
    RecipeIngredient,
    RecipeStatus,
    utcnow_iso,
)
from recipe_mcp.domain.taxonomy import Facet
from recipe_mcp.services.categorization import CategorizationService, dietary_classifications

FIELD_KEYS: frozenset[str] = frozenset(
    {
        "title",
        "total_minutes",
        "servings",
        "notes",
        "add_ingredients",
        "remove_ingredients",
        "food_types",
    }
)


class CorrectionError(ValueError):
    pass


@dataclass
class CorrectionResult:
    recipe: Recipe
    changes: list[str] = field(default_factory=list)


class CorrectionService:
    def __init__(
        self,
        recipes: RecipeRepository,
        categorizer: CategorizationService,
        private_evals_path: Path | None,
    ) -> None:
        self.recipes = recipes
        self.categorizer = categorizer
        self.private_evals_path = private_evals_path

    def correct(
        self,
        recipe_id: int,
        facet_corrections: dict[str, list[str]] | None = None,
        field_updates: dict[str, Any] | None = None,
        member_id: int | None = None,
    ) -> CorrectionResult:
        recipe = self.recipes.get(recipe_id)
        if recipe is None:
            raise CorrectionError(f"recipe {recipe_id} not found")
        if not facet_corrections and not field_updates:
            raise CorrectionError("nothing to correct: pass facet_corrections or field_updates")
        # Checked up front: food_types writes inside the loop below.
        try:
            limits.check_facets("facet_corrections", facet_corrections)
            limits.check_field_updates(field_updates)
        except limits.InputTooLarge as exc:
            raise CorrectionError(str(exc)) from exc
        changes: list[str] = []
        before = {
            "facets": recipe.classification_summary(),
            "title": recipe.title,
            "total_minutes": recipe.total_minutes,
            "ingredients": [i.canonical_name for i in recipe.ingredients],
            "contains": recipe.flags.food_types(),
        }

        fields_changed = False
        food_types_changed = False
        for key, value in (field_updates or {}).items():
            if key not in FIELD_KEYS:
                raise CorrectionError(
                    f"unknown field {key!r}; allowed: {', '.join(sorted(FIELD_KEYS))}"
                )
            if key == "title" and isinstance(value, str) and value.strip():
                recipe.title = value.strip()
                changes.append(f"title -> {recipe.title}")
            elif key == "total_minutes":
                if value is not None and (not isinstance(value, int) or value <= 0):
                    raise CorrectionError("total_minutes must be a positive integer or null")
                recipe.total_minutes = value
                changes.append(f"total_minutes -> {value}")
                fields_changed = True
            elif key == "servings":
                recipe.servings = str(value) if value is not None else None
                changes.append(f"servings -> {recipe.servings}")
            elif key == "notes":
                notes = [value] if isinstance(value, str) else [str(v) for v in value or []]
                recipe.notes = [n.strip() for n in notes if n.strip()]
                changes.append(f"notes -> {len(recipe.notes)} note(s)")
            elif key == "add_ingredients":
                for raw in value or []:
                    for ingredient in normalize_line(str(raw)):
                        if ingredient.canonical_name not in {
                            i.canonical_name for i in recipe.ingredients
                        }:
                            recipe.ingredients.append(ingredient)
                            changes.append(f"added ingredient {ingredient.canonical_name}")
                            fields_changed = True
            elif key == "remove_ingredients":
                targets = {canonical_name(str(v)) for v in value or []}
                kept = [i for i in recipe.ingredients if i.canonical_name not in targets]
                removed = {i.canonical_name for i in recipe.ingredients} - {
                    i.canonical_name for i in kept
                }
                recipe.ingredients = kept
                for name in sorted(removed):
                    changes.append(f"removed ingredient {name}")
                    fields_changed = True
            elif key == "food_types":
                if not isinstance(value, Mapping) or not value:
                    raise CorrectionError(
                        "food_types maps an ingredient to its food types, e.g. "
                        '{"oyster mushroom": []} or {"stock": ["meat"]}'
                    )
                for ingredient_text, types in value.items():
                    target = self._find_ingredient(recipe, str(ingredient_text))
                    wanted = [types] if isinstance(types, str) else list(types or [])
                    wanted = [str(t).strip().lower() for t in wanted if str(t).strip()]
                    wanted = [t for t in wanted if t != "none"]
                    try:
                        flags = IngredientFlags.from_food_types(wanted)
                    except ValueError as exc:
                        raise CorrectionError(str(exc)) from exc
                    assert recipe.id is not None
                    self.recipes.set_food_types(recipe.id, target.canonical_name, flags, member_id)
                    target.food_types_override = flags
                    changes.append(
                        f"{target.canonical_name} contains -> "
                        f"{', '.join(flags.food_types()) or 'none'}"
                    )
                    food_types_changed = True
        if field_updates:
            if recipe.status == RecipeStatus.DRAFT and recipe.total_minutes is not None:
                recipe.status = RecipeStatus.COMPLETE
                changes.append("status -> complete")
            self.recipes.update(recipe)
            if fields_changed:
                recipe = self.categorizer.refresh_rules(recipe)
                changes.append("re-ran dietary and effort rules")
            elif food_types_changed:
                assert recipe.id is not None
                self.recipes.replace_facet(
                    recipe.id, Facet.DIETARY, dietary_classifications(recipe)
                )
                changes.append("re-ran dietary rules")

        for facet_name, values in (facet_corrections or {}).items():
            try:
                facet = Facet(facet_name)
            except ValueError as exc:
                raise CorrectionError(
                    f"unknown facet {facet_name!r}; allowed: {', '.join(f.value for f in Facet)}"
                ) from exc
            if facet == Facet.DIETARY:
                raise CorrectionError(
                    "dietary_suitability is derived from ingredients; correct the ingredients"
                )
            cleaned: list[str] = []
            proposed: dict[str, str] = {}
            for raw in values if isinstance(values, list) else [values]:
                value, unknown = taxonomy.normalize_value(facet, str(raw))
                if value and value not in cleaned:
                    cleaned.append(value)
                    if unknown:  # kept next to "other" so refresh-taxonomy can move it later
                        proposed[value] = unknown
            if not cleaned:
                raise CorrectionError(f"no valid value for {facet_name}: {values}")
            if facet not in taxonomy.MULTI_VALUE_FACETS:
                cleaned = cleaned[:1]
            assert recipe.id is not None
            self.recipes.confirm_facet(recipe.id, facet, cleaned, proposed)
            changes.append(f"{facet.value} -> {', '.join(cleaned)}")

        refreshed = self.recipes.get(recipe_id)
        assert refreshed is not None
        self._record_case(refreshed, before, facet_corrections, field_updates, member_id, changes)
        return CorrectionResult(recipe=refreshed, changes=changes)

    def propose(
        self, recipe_id: int, facets: Mapping[str, list[str] | str], agent: str = "agent"
    ) -> CorrectionResult:
        """Store an agent's classification *proposal*: model-grade, overridable, no case."""
        recipe = self.recipes.get(recipe_id)
        if recipe is None:
            raise CorrectionError(f"recipe {recipe_id} not found")
        if not facets:
            raise CorrectionError("nothing proposed: pass facet_corrections")
        try:
            limits.check_facets("facet_corrections", facets)
        except limits.InputTooLarge as exc:
            raise CorrectionError(str(exc)) from exc
        if "dietary_suitability" in facets:
            raise CorrectionError(
                "dietary_suitability is derived from ingredients; correct the ingredients"
            )
        for facet_name in facets:
            try:
                Facet(facet_name)
            except ValueError as exc:
                raise CorrectionError(
                    f"unknown facet {facet_name!r}; allowed: {', '.join(f.value for f in Facet)}"
                ) from exc
        outcome = self.categorizer.apply_agent_proposal(recipe, facets, agent)
        changes = [
            f"{facet}: proposed {', '.join(outcome.recipe.facet_values(Facet(facet)))}"
            for facet in facets
        ]
        changes.extend(outcome.warnings)
        return CorrectionResult(recipe=outcome.recipe, changes=changes)

    @staticmethod
    def _find_ingredient(recipe: Recipe, text: str) -> RecipeIngredient:
        """The one recipe ingredient a person means by ``text``."""
        name = canonical_name(text)
        exact = [i for i in recipe.ingredients if i.canonical_name in {name, text.strip().lower()}]
        loose = [i for i in recipe.ingredients if ingredient_matches(text, i.canonical_name)]
        found = exact or loose
        if len(found) != 1:
            names = ", ".join(i.canonical_name for i in recipe.ingredients)
            what = "matches several ingredients" if found else "is not in this recipe"
            raise CorrectionError(f"{text!r} {what}; ingredients: {names}")
        return found[0]

    def _record_case(
        self,
        recipe: Recipe,
        before: dict[str, Any],
        facet_corrections: dict[str, list[str]] | None,
        field_updates: dict[str, Any] | None,
        member_id: int | None,
        changes: list[str],
    ) -> None:
        """Append a regression case to the private evaluation set (never committed)."""
        if self.private_evals_path is None:
            return
        case = {
            "recorded_at": utcnow_iso(),
            "recipe_id": recipe.id,
            "title": recipe.title,
            "source_url": recipe.canonical_source_url,
            "member_id": member_id,
            "before": before,
            "facet_corrections": facet_corrections or {},
            "field_updates": field_updates or {},
            "expected": {
                "facets": recipe.classification_summary(),
                "total_minutes": recipe.total_minutes,
                "ingredients": [i.canonical_name for i in recipe.ingredients],
                "contains": recipe.flags.food_types(),
                "food_types": {
                    i.canonical_name: i.food_types_override.food_types()
                    for i in recipe.ingredients
                    if i.food_types_override is not None
                },
            },
            "changes": changes,
        }
        self.private_evals_path.mkdir(parents=True, exist_ok=True)
        with (self.private_evals_path / "corrections.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(case) + "\n")
