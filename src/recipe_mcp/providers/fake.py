"""Deterministic keyword-based model stand-in for offline tests, demos and CI.

It is intentionally simple: good enough to exercise the whole vertical slice
without a network, and stable so tests never flake.
"""

from __future__ import annotations

import re
import time

from pydantic import BaseModel

from recipe_mcp.domain import dietary, taxonomy
from recipe_mcp.domain import ingredients as ing
from recipe_mcp.providers import prompts
from recipe_mcp.providers.base import (
    FacetConfidence,
    ImageIngredients,
    ModelResponse,
    PersonalRecipeDraft,
    ProposedValue,
    QueryConstraints,
    RecipeClassification,
    RecipeClassificationInput,
)

_CUISINE_HINTS: dict[str, tuple[str, ...]] = {
    "thai": ("thai", "lemongrass", "fish sauce", "curry paste", "galangal", "thai basil"),
    "italian": ("italian", "pasta", "parmesan", "risotto", "spaghetti", "penne", "orzo", "pesto"),
    "indian": ("indian", "curry powder", "garam masala", "dal", "paneer", "masala", "turmeric"),
    "japanese": ("japanese", "miso", "dashi", "mirin", "soba", "udon", "teriyaki"),
    "korean": ("korean", "gochujang", "kimchi", "bibimbap", "gochugaru"),
    "chinese": ("chinese", "hoisin", "shaoxing", "sichuan", "doubanjiang", "five-spice"),
    "vietnamese": ("vietnamese", "banh mi", "nuoc cham", "bun cha", "pho"),
    "mexican": ("mexican", "tortilla", "tortillas", "taco", "tacos", "salsa", "jalapeno"),
    "mediterranean": ("mediterranean", "feta", "olives", "tahini", "chickpeas", "za'atar", "greek"),
    "american": ("american", "burger", "mac and cheese", "barbecue", "bbq", "chowder"),
    "french": ("french", "gratin", "ratatouille", "beurre", "bourguignon", "tarte"),
}
_DISH_HINTS: dict[str, tuple[str, ...]] = {
    "soup": ("soup", "broth", "chowder", "ramen", "pho"),
    "salad": ("salad", "slaw"),
    "curry": ("curry", "dal", "masala"),
    "stew": ("stew", "braise", "braised", "chili", "cassoulet", "tagine"),
    "pasta": ("pasta", "spaghetti", "penne", "orzo", "lasagna", "linguine", "rigatoni"),
    "roast": ("roast", "roasted", "sheet-pan", "sheet pan", "baked"),
    "stir-fry": ("stir-fry", "stir fry", "stir-fried", "wok"),
    "sandwich": ("sandwich", "burger", "toast", "wrap"),
    "rice dish": ("rice", "risotto", "fried rice", "bibimbap", "pilaf", "bowl"),
    "noodle dish": ("noodle", "noodles", "soba", "udon", "pad thai"),
}
_CHARACTER_HINTS: dict[str, tuple[str, ...]] = {
    "cozy": ("soup", "stew", "braise", "braised", "chowder", "cozy", "comfort", "baked", "pumpkin"),
    "fresh": ("salad", "herb", "cilantro", "mint", "lime", "cucumber", "fresh"),
    "light": ("salad", "light", "steamed", "poached", "broth", "lean"),
    "bright": ("lemon", "lime", "citrus", "vinegar", "bright", "zest"),
    "rich": ("cream", "butter", "cheese", "coconut milk", "rich", "bacon", "gratin", "braised"),
    "spicy": ("chili", "chilies", "spicy", "gochujang", "curry paste", "harissa", "jalapeno"),
}
_METHOD_HINTS: dict[str, tuple[str, ...]] = {
    "no-cook": ("salad", "no-cook", "raw"),
    "roast": ("roast", "roasted", "sheet-pan", "sheet pan"),
    "bake": ("bake", "baked", "gratin", "casserole"),
    "grill": ("grill", "grilled"),
    "braise": ("braise", "braised", "stew"),
    "pressure cook": ("pressure cook", "instant pot"),
}
_DIET_WORDS = {
    "vegan": "vegan",
    "vegetarian": "vegetarian",
    "veggie": "vegetarian",
    "pescatarian": "pescatarian",
}
_MOOD_WORDS = {
    "cozy": "cozy",
    "comforting": "cozy",
    "comfort": "cozy",
    "warming": "cozy",
    "hearty": "cozy",
    "light": "light",
    "healthy": "light",
    "lighter": "light",
    "fresh": "fresh",
    "bright": "bright",
    "zingy": "bright",
    "rich": "rich",
    "richer": "rich",
    "indulgent": "rich",
    "spicy": "spicy",
}
_MINUTES_RE = re.compile(
    r"(?:under|less than|within|max(?:imum)?|no more than|in)\s+(\d+)\s*(?:min|minutes)"
)
_MINUTES_RE_ALT = re.compile(r"(\d+)\s*(?:min|minutes)\s+or less")
_MISSING_RE = re.compile(
    r"no more than (\w+) missing|at most (\w+) missing|(\w+) missing ingredients? (?:or fewer|max)"
)
_HAVE_RE = re.compile(
    r"(?:we have|i have|we've got|i've got|using|with)\s+(.+?)(?:[.?!]|$)", re.IGNORECASE
)
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "zero": 0, "no": 0}


def _lower_bag(recipe: RecipeClassificationInput) -> str:
    return " ".join([recipe.title, *recipe.ingredients, *recipe.notes]).lower()


def _first_hit(bag: str, hints: dict[str, tuple[str, ...]]) -> str | None:
    for value, words in hints.items():
        if any(w in bag for w in words):
            return value
    return None


def _all_hits(bag: str, hints: dict[str, tuple[str, ...]]) -> list[str]:
    return [value for value, words in hints.items() if any(w in bag for w in words)]


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


class FakeModelClient:
    provider = "fake"
    model = "fake-v1"

    def _respond[T: BaseModel](
        self, output: T, prompt: prompts.Prompt, start: float
    ) -> ModelResponse[T]:
        return ModelResponse(
            output=output,
            provider=self.provider,
            model=self.model,
            prompt_version=prompt.version,
            latency_ms=_elapsed_ms(start),
            input_tokens=0,
            output_tokens=0,
        )

    def classify_recipe(
        self, recipe: RecipeClassificationInput
    ) -> ModelResponse[RecipeClassification]:
        start = time.perf_counter()
        bag = _lower_bag(recipe)
        title = recipe.title.lower()
        normalized = ing.normalize_ingredients(recipe.ingredients)
        flags = dietary.flags_for(normalized)

        cuisine = _first_hit(bag, _CUISINE_HINTS) or (
            (recipe.source_cuisine or "").lower() if recipe.source_cuisine else None
        )
        cuisine_value, cuisine_proposed = taxonomy.normalize_value(
            taxonomy.Facet.CUISINE, cuisine or taxonomy.OTHER
        )
        dish = _first_hit(title, _DISH_HINTS) or _first_hit(bag, _DISH_HINTS) or taxonomy.OTHER
        character = _all_hits(bag, _CHARACTER_HINTS)
        if "salad" in title and "rich" in character:
            character.remove("rich")
        method = _first_hit(bag, _METHOD_HINTS)
        primaries = [
            i.canonical_name
            for i in normalized
            if i.canonical_name in taxonomy.PRIMARY_INGREDIENT_VALUES
            or i.category in {"protein", "legume"}
        ]
        primaries = [p for p in primaries if not ing.is_staple(p)][:3]
        if not primaries:
            primaries = [i.canonical_name for i in normalized if not i.is_staple][:1]
        health = (
            "light" if "light" in character else ("rich" if "rich" in character else "balanced")
        )
        confident = cuisine is not None and dish != taxonomy.OTHER
        facet_confidence = FacetConfidence(
            cuisine=0.9 if cuisine else 0.4,
            dish_type=0.9 if dish != taxonomy.OTHER else 0.4,
            meal=0.85,
            primary_ingredient=0.9 if primaries else 0.4,
            effort=0.95 if recipe.total_minutes is not None else 0.5,
            character=0.85 if character else 0.4,
            cooking_method=0.8 if method else 0.4,
            health_orientation=0.7,
        )
        proposed: list[ProposedValue] = []
        if cuisine_proposed:
            proposed.append(ProposedValue(facet="cuisine", value=cuisine_proposed))
        output = RecipeClassification(
            dietary_suitability=dietary.allowed_diets(flags),
            cuisine=cuisine_value or taxonomy.OTHER,
            dish_type=dish,
            meal=["dinner"] if "breakfast" not in bag else ["breakfast"],
            primary_ingredients=primaries,
            effort=taxonomy.effort_for_minutes(recipe.total_minutes),
            character=character,
            cooking_method=method,
            health_orientation=health,
            confidence=0.9 if confident else 0.55,
            facet_confidence=facet_confidence,
            proposed_values=proposed,
        )
        return self._respond(output, prompts.CLASSIFY_RECIPE, start)

    def parse_personal_recipe(self, text: str) -> ModelResponse[PersonalRecipeDraft]:
        start = time.perf_counter()
        cleaned = re.sub(
            r"^\s*(save this|save|add this|add)\s*[:\-]?\s*", "", text.strip(), flags=re.I
        )
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", cleaned) if s.strip()]
        head = sentences[0] if sentences else cleaned
        rest = sentences[1:]
        dish, _, ingredient_text = head.partition(" with ")
        if not ingredient_text:
            dish, _, ingredient_text = head.partition(":")
        ingredient_list = [
            i.strip(" .") for i in re.split(r",|\band\b|\n|;", ingredient_text) if i.strip(" .")
        ]
        dish_words = re.findall(r"[A-Za-z][A-Za-z'-]*", dish)
        first_words = [
            w for w in dish_words if w.lower() not in {"a", "an", "the", "my", "our", "some"}
        ]
        # Lead ingredient of the dish name (e.g. "tuna" from "tuna salad") counts as an ingredient.
        leading = [w.lower() for w in first_words[:-1]] if len(first_words) > 1 else []
        ingredients = [*leading, *ingredient_list]
        seen: set[str] = set()
        deduped: list[str] = []
        for item in ingredients:
            key = item.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(item.lower())
        minutes = None
        m = re.search(r"(\d+)\s*(?:min|minutes)", cleaned, re.I)
        if m:
            minutes = int(m.group(1))
        servings = None
        s = re.search(r"(?:serves|for)\s+(\d+)\b", cleaned, re.I)
        if s:
            servings = s.group(1)
        notes = [r.rstrip(".") for r in rest if not re.search(r"\d+\s*(?:min|minutes)", r, re.I)]
        title = " ".join(w.capitalize() for w in first_words) or "Untitled Recipe"
        output = PersonalRecipeDraft(
            title=title,
            ingredients=deduped,
            servings=servings,
            total_minutes=minutes,
            notes=notes,
        )
        return self._respond(output, prompts.PARSE_PERSONAL_RECIPE, start)

    def interpret_query(self, text: str) -> ModelResponse[QueryConstraints]:
        start = time.perf_counter()
        lowered = text.lower()
        out = QueryConstraints()
        out.dietary = sorted({v for w, v in _DIET_WORDS.items() if re.search(rf"\b{w}\b", lowered)})
        for value, words in _CUISINE_HINTS.items():
            if re.search(rf"\b{re.escape(words[0])}\b", lowered):
                out.cuisine = value
                break
        for value, words in _DISH_HINTS.items():
            if any(re.search(rf"\b{re.escape(w)}s?\b", lowered) for w in words[:2]):
                out.dish_type = value
                break
        out.character = sorted(
            {v for w, v in _MOOD_WORDS.items() if re.search(rf"\b{w}\b", lowered)}
        )
        m = _MINUTES_RE.search(lowered) or _MINUTES_RE_ALT.search(lowered)
        if m:
            out.max_minutes = int(m.group(1))
        elif re.search(r"\bquick\b|\bfast\b", lowered):
            out.max_minutes = 30
        mm = _MISSING_RE.search(lowered)
        if mm:
            word = next(g for g in mm.groups() if g)
            out.max_missing = _NUMBER_WORDS.get(word, int(word) if word.isdigit() else None)
        have = _HAVE_RE.search(lowered)
        if have and (out.dish_type != "salad" or "we have" in lowered):
            items = [i.strip() for i in re.split(r",|\band\b", have.group(1)) if i.strip()]
            out.available_ingredients = [i for i in items if len(i) < 30]
        if re.search(r"\bboth\b|\bwe both\b|\bus both\b|\bboth of us\b", lowered):
            out.for_household = True
        if re.search(
            r"not (?:been )?cooked recently|haven'?t (?:had|made|cooked)|not recently|in a while",
            lowered,
        ):
            out.exclude_recent = True
        based = re.search(r"\b([a-z]+)[- ]based\b", lowered)
        if based:
            out.main_ingredient = based.group(1)
        without = re.search(r"(?:without|no|avoid)\s+([a-z ]+?)(?:[.,]|$)", lowered)
        if without and "no more than" not in lowered:
            out.excluded_ingredients = [without.group(1).strip()]
        return self._respond(out, prompts.INTERPRET_QUERY, start)

    def extract_image_ingredients(
        self, image_bytes: bytes, mime_type: str
    ) -> ModelResponse[ImageIngredients]:
        del image_bytes, mime_type
        start = time.perf_counter()
        return self._respond(ImageIngredients(items=[]), prompts.EXTRACT_IMAGE_INGREDIENTS, start)
