"""MCP server: five tools, no business logic. Everything delegates to services."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from recipe_mcp import __version__
from recipe_mcp.adapters.mcp.schemas import (
    CorrectRecipeOut,
    GetRecipeOut,
    RateRecipeOut,
    RecipeOut,
    RecommendRecipesOut,
    SaveRecipeOut,
)
from recipe_mcp.domain.models import FacetSource, Recipe, RecommendationRequest, Sentiment
from recipe_mcp.services.container import AppContext
from recipe_mcp.services.corrections import CorrectionError
from recipe_mcp.services.feedback import parse_sentiment
from recipe_mcp.services.ingestion import IngestionError
from recipe_mcp.settings import MissingConfigError

TOOL_NAMES: tuple[str, ...] = (
    "save_recipe",
    "recommend_recipes",
    "get_recipe",
    "rate_recipe",
    "correct_recipe",
)

VOCAB = (
    "cuisine: thai, italian, indian, japanese, korean, mexican, mediterranean, american, "
    "french, other. dish_type: soup, salad, curry, stew, pasta, roast, stir-fry, sandwich, "
    "rice dish, noodle dish, other. character: bright, fresh, light, cozy, rich, spicy. "
    "meal: breakfast, lunch, dinner, starter, dessert, snack. effort: quick, weeknight, "
    "weekend, project. cooking_method: no-cook, roast, bake, grill, braise, pressure cook, "
    "other. health_orientation: light, balanced, rich. primary_ingredient: 1-3 ingredients "
    "from the recipe. Dietary suitability is derived from ingredients by rules; do not set it."
)

INSTRUCTIONS = (
    "Shared household recipe store. The server is deterministic and calls no model: you, "
    "the client agent, do the parsing and classifying. Results come only from stored "
    "recipes; never invent recipes. "
    "recommend_recipes takes typed constraints (dietary, cuisine, dish_type, main_ingredient, "
    "character/mood, max_minutes, available_ingredients). main_ingredient is what the dish is "
    "built around: an ingredient ('mushroom') or a group (beans, legumes, fish, seafood, "
    "shellfish, meat, poultry). "
    "Dietary labels come from each ingredient's food types (meat, fish, shellfish, dairy, "
    "egg; shown as 'contains'). If a person says a food type is wrong, correct it with "
    'correct_recipe field_updates.food_types, e.g. {"oyster mushroom": []}. '
    "A dietary filter also returns recipes that reach the diet only through the recipe's "
    "own stated choices (an 'or' between foods, an optional or garnish line); those rank "
    "after exact matches and carry adapted_for and diet_swaps: always tell the person the "
    "swap. "
    "save_recipe: for an NYT Cooking link pass input=url; the server extracts the recipe. "
    "For an informal description parse it yourself and pass title, ingredients (only what "
    "was said), total_minutes only if stated, notes for reminders, and classifications. "
    "If a result says needs_classification, call correct_recipe with proposed_by_agent=true "
    "and your best facet values. Pass member (a member key such as 'alex') on writes when "
    "known; otherwise DEFAULT_MEMBER applies. correct_recipe without proposed_by_agent "
    "records a user's correction, which overrides everything. Vocabulary: " + VOCAB
)


def _member_id(ctx: AppContext, member: str | None, required: bool = False) -> int | None:
    found = ctx.resolve_member(member)
    if found is None:
        if member or required:
            keys = ", ".join(m.member_key for m in ctx.members.list_for_household(ctx.household_id))
            raise ToolError(
                f"unknown member {member!r}; known member keys: {keys or 'none configured'}. "
                "Set DEFAULT_MEMBER in .env or pass member explicitly."
            )
        return None
    return found.id


def _recipe_out(ctx: AppContext, recipe: Recipe) -> RecipeOut:
    added_by = None
    if recipe.added_by_member_id is not None:
        member = ctx.members.get(recipe.added_by_member_id)
        added_by = member.member_key if member else None
    return RecipeOut.from_recipe(recipe, added_by=added_by)


def build_server(ctx: AppContext) -> MCPServer[Any]:
    server: MCPServer[Any] = MCPServer(
        name="recipe-mcp", version=__version__, instructions=INSTRUCTIONS
    )

    @server.tool(
        name="save_recipe",
        description=(
            "Save a recipe from an NYT Cooking URL or an informal description "
            "(parse it first and pass title + ingredients + classifications). Extracts, "
            "normalizes, validates dietary rules and stores it. Idempotent for the same "
            "canonical URL. Other sites are stored as links only. Facets: " + VOCAB
        ),
        annotations=ToolAnnotations(idempotent_hint=True, destructive_hint=False),
    )
    def save_recipe(
        input: str,
        notes: str | None = None,
        member: str | None = None,
        title: str | None = None,
        ingredients: list[str] | None = None,
        total_minutes: int | None = None,
        servings: str | None = None,
        classifications: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        """input: a recipe URL or the original description. When the agent has parsed an
        informal description, also pass title, ingredients and classifications."""
        member_id = _member_id(ctx, member)
        try:
            if title and ingredients:
                result = ctx.ingestion.save_structured(
                    title,
                    ingredients,
                    total_minutes=total_minutes,
                    servings=servings,
                    notes=[notes] if notes else [],
                    classifications=classifications,
                    member_id=member_id,
                )
            else:
                result = ctx.ingestion.save(input, notes=notes, member_id=member_id)
        except IngestionError as exc:
            raise ToolError(str(exc)) from exc
        except MissingConfigError as exc:
            raise ToolError(
                "no server-side model is configured; parse the description yourself and pass "
                "title and ingredients (missing: " + ", ".join(exc.names) + ")"
            ) from exc
        recipe = result.recipe
        needs_classification = recipe.is_recommendable and not any(
            c.source in {FacetSource.MODEL, FacetSource.USER} for c in recipe.classifications
        )
        return SaveRecipeOut(
            created=result.created,
            confirmation=result.confirmation(),
            recipe=_recipe_out(ctx, recipe),
            warnings=result.warnings,
            needs_review=result.needs_review,
            needs_classification=needs_classification,
        ).model_dump()

    @server.tool(
        name="recommend_recipes",
        description=(
            "Recommend up to three stored recipes matching typed constraints. dietary values: "
            "vegan, vegetarian, pescatarian, omnivore. character values: bright, fresh, light, "
            "cozy, rich, spicy. main_ingredient: what the dish is built around, an ingredient "
            "('mushroom', 'chickpeas') or a group (beans, legumes, fish, seafood, shellfish, "
            "meat, poultry); only matching recipes are returned. excluded_ingredients takes "
            "ingredients ('carrots') or whole food types (dairy, egg, meat, fish, shellfish, "
            "seafood) for 'nothing with egg'. member personalises "
            "ranking; omit it for the household view (something everyone likes). Read-only."
        ),
        annotations=ToolAnnotations(read_only_hint=True),
    )
    def recommend_recipes(
        dietary: list[str] | None = None,
        cuisine: str | None = None,
        dish_type: str | None = None,
        main_ingredient: str | None = None,
        character: list[str] | None = None,
        max_minutes: int | None = None,
        available_ingredients: list[str] | None = None,
        excluded_ingredients: list[str] | None = None,
        max_missing: int | None = None,
        exclude_recent_days: int | None = None,
        member: str | None = None,
        limit: int = 3,
    ) -> dict[str, Any]:
        member_id = _member_id(ctx, member) if member else None
        request = RecommendationRequest(
            dietary=[d.lower() for d in dietary or []],
            cuisine=cuisine.lower() if cuisine else None,
            dish_type=dish_type.lower() if dish_type else None,
            main_ingredient=main_ingredient.strip().lower() if main_ingredient else None,
            character=[c.lower() for c in character or []],
            max_minutes=max_minutes,
            available_ingredients=available_ingredients or [],
            excluded_ingredients=excluded_ingredients or [],
            max_missing=max_missing,
            diners=ctx.recommendation.diners_for(member_id),
            exclude_recent_days=exclude_recent_days,
            limit=max(1, min(limit, 10)),
        )
        results = ctx.recommendation.recommend(request)
        return RecommendRecipesOut(
            request=request, results=results, count=len(results)
        ).model_dump()

    @server.tool(
        name="get_recipe",
        description="Return a stored recipe: metadata, ingredients, classifications, notes, "
        "feedback summary and source link. Read-only.",
        annotations=ToolAnnotations(read_only_hint=True),
    )
    def get_recipe(recipe_id: int) -> dict[str, Any]:
        recipe = ctx.recipes.get(recipe_id)
        if recipe is None:
            raise ToolError(f"recipe {recipe_id} not found")
        return GetRecipeOut(
            recipe=_recipe_out(ctx, recipe), feedback=ctx.feedback_service.summary(recipe_id)
        ).model_dump()

    @server.tool(
        name="rate_recipe",
        description=(
            "Record feedback on a recipe. sentiment: love, like, dislike (emoji such as ❤️ 👍 👎 "
            "also accepted). member: who is speaking (defaults to DEFAULT_MEMBER). on_behalf_of: "
            "set when reporting another member's opinion ('Sam didn't like it')."
        ),
        annotations=ToolAnnotations(destructive_hint=False),
    )
    def rate_recipe(
        recipe_id: int,
        sentiment: str,
        member: str | None = None,
        on_behalf_of: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        parsed = (
            Sentiment(sentiment.lower())
            if sentiment.lower() in Sentiment.__members__.values()
            else parse_sentiment(sentiment)
        )
        if parsed is None:
            raise ToolError("sentiment must be one of love, like, dislike (or ❤️ 👍 👎)")
        speaker_id = _member_id(ctx, member, required=True)
        assert speaker_id is not None
        subject_id = _member_id(ctx, on_behalf_of, required=True) if on_behalf_of else speaker_id
        assert subject_id is not None
        try:
            summary = ctx.feedback_service.rate(
                recipe_id,
                subject_id,
                parsed,
                notes=notes,
                reported_by_member_id=speaker_id if subject_id != speaker_id else None,
            )
        except LookupError as exc:
            raise ToolError(str(exc)) from exc
        recipe = ctx.recipes.get(recipe_id)
        return RateRecipeOut(
            recipe_id=recipe_id,
            title=recipe.title if recipe else "",
            recorded=parsed.value,
            feedback=summary,
        ).model_dump()

    @server.tool(
        name="correct_recipe",
        description=(
            "Apply a user correction. facet_corrections maps a facet (cuisine, dish_type, "
            "character, meal, primary_ingredient, effort, cooking_method, health_orientation) "
            "to its correct values and overrides the model. field_updates may set title, "
            "total_minutes, servings, notes, add_ingredients, remove_ingredients, and food_types "
            "(ingredient -> its complete list of food types for this recipe, from meat, fish, "
            "shellfish, dairy, egg; [] for none); dietary rules re-run afterwards. A person's "
            "correction becomes a private regression case; with proposed_by_agent=true the "
            "values are stored as the agent's classification instead."
        ),
        annotations=ToolAnnotations(destructive_hint=False, idempotent_hint=True),
    )
    def correct_recipe(
        recipe_id: int,
        facet_corrections: dict[str, list[str]] | None = None,
        field_updates: dict[str, Any] | None = None,
        member: str | None = None,
        proposed_by_agent: bool = False,
    ) -> dict[str, Any]:
        """proposed_by_agent=true stores facet_corrections as the agent's classification
        proposal (overridable, no regression case); false records a person's correction."""
        try:
            if proposed_by_agent:
                if field_updates:
                    raise ToolError("proposed_by_agent only accepts facet_corrections")
                result = ctx.corrections.propose(recipe_id, facet_corrections or {})
            else:
                result = ctx.corrections.correct(
                    recipe_id,
                    facet_corrections=facet_corrections,
                    field_updates=field_updates,
                    member_id=_member_id(ctx, member),
                )
        except CorrectionError as exc:
            raise ToolError(str(exc)) from exc
        return CorrectRecipeOut(
            recipe=_recipe_out(ctx, result.recipe), changes=result.changes
        ).model_dump()

    return server
