"""Deterministic ingredient normalization, aliasing, categorisation and flagging.

No model is involved here. The lexicons are small on purpose: they cover the
ingredients that actually appear in a household recipe collection and grow only
when real recipes require it.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

from recipe_mcp.domain import staples as staples_registry
from recipe_mcp.domain.models import IngredientFlags, RecipeIngredient

_UNITS: frozenset[str] = frozenset(
    {
        "cup",
        "cups",
        "tablespoon",
        "tablespoons",
        "tbsp",
        "teaspoon",
        "teaspoons",
        "tsp",
        "pound",
        "pounds",
        "lb",
        "lbs",
        "ounce",
        "ounces",
        "oz",
        "gram",
        "grams",
        "g",
        "kg",
        "kilogram",
        "ml",
        "milliliter",
        "milliliters",
        "liter",
        "liters",
        "quart",
        "quarts",
        "pint",
        "pints",
        "l",
        "clove",
        "cloves",
        "can",
        "cans",
        "tin",
        "tins",
        "jar",
        "jars",
        "bag",
        "bags",
        "box",
        "boxes",
        "package",
        "packages",
        "bunch",
        "bunches",
        "sprig",
        "sprigs",
        "stalk",
        "stalks",
        "head",
        "heads",
        "pinch",
        "handful",
        "slice",
        "slices",
        "piece",
        "pieces",
        "inch",
        "inches",
        "large",
        "medium",
        "small",
        "whole",
    }
)

_DESCRIPTORS: frozenset[str] = frozenset(
    {
        "fresh",
        "freshly",
        "chopped",
        "diced",
        "minced",
        "sliced",
        "grated",
        "shredded",
        "crushed",
        "ground",
        "peeled",
        "deveined",
        "thinly",
        "finely",
        "roughly",
        "coarsely",
        "boneless",
        "skinless",
        "bone-in",
        "skin-on",
        "ripe",
        "cooked",
        "uncooked",
        "raw",
        "dried",
        "frozen",
        "thawed",
        "unthawed",
        "canned",
        "extra-virgin",
        "extra",
        "virgin",
        "kosher",
        "flaky",
        "unsalted",
        "salted",
        "plus",
        "more",
        "for",
        "serving",
        "to",
        "taste",
        "optional",
        "about",
        "of",
        "or",
        "and",
        "a",
        "the",
        "some",
        "few",
        "such",
        "as",
        "into",
        "cut",
        "halved",
        "quartered",
        "torn",
        "packed",
        "loosely",
        "lightly",
        "roasted",
        "toasted",
        "drained",
        "rinsed",
        "divided",
        "room",
        "temperature",
    }
)

ALIASES: dict[str, str] = {
    "scallions": "green onion",
    "scallion": "green onion",
    "spring onion": "green onion",
    "spring onions": "green onion",
    "green onions": "green onion",
    "coriander leaves": "cilantro",
    "fresh coriander": "cilantro",
    "coriander": "cilantro",
    "aubergine": "eggplant",
    "courgette": "zucchini",
    "capsicum": "bell pepper",
    "red pepper": "bell pepper",
    "green pepper": "bell pepper",
    "yellow pepper": "bell pepper",
    "chickpea": "chickpeas",
    "garbanzo beans": "chickpeas",
    "garbanzos": "chickpeas",
    "tinned tomatoes": "canned tomatoes",
    "crushed tomatoes": "canned tomatoes",
    "tomato puree": "tomato paste",
    "napa cabbage": "cabbage",
    "savoy cabbage": "cabbage",
    "red cabbage": "cabbage",
    "green cabbage": "cabbage",
    "butternut squash": "pumpkin",
    "kabocha": "pumpkin",
    "kabocha squash": "pumpkin",
    "rocket": "arugula",
    "prawn": "shrimp",
    "prawns": "shrimp",
    "canned tuna": "tuna",
    "tinned tuna": "tuna",
    "tuna in olive oil": "tuna",
    "salmon fillet": "salmon",
    "salmon fillets": "salmon",
    "chicken breast": "chicken",
    "chicken breasts": "chicken",
    "chicken thigh": "chicken",
    "chicken thighs": "chicken",
    "boneless chicken thighs": "chicken",
    "ground beef": "beef",
    "minced beef": "beef",
    "beef mince": "beef",
    "firm tofu": "tofu",
    "extra-firm tofu": "tofu",
    "silken tofu": "tofu",
    "coconut cream": "coconut milk",
    "egg": "eggs",
    "yoghurt": "yogurt",
    "greek yogurt": "yogurt",
    "greek yoghurt": "yogurt",
    "parmigiano-reggiano": "parmesan",
    "parmigiano": "parmesan",
    "mixed seeds": "seeds",
    "salt pepper": "salt and pepper",
    "salt black pepper": "salt and pepper",
    "beef short ribs": "beef",
    "filets mignon": "filet mignon",
    "filets mignons": "filet mignon",
    "filet mignons": "filet mignon",
    "fillet mignon": "filet mignon",
    "short ribs": "beef",
    "arborio rice": "rice",
    "jasmine rice": "rice",
    "cooked rice": "rice",
    "white beans": "white beans",
    "cannellini beans": "white beans",
    "pumpkin seeds": "seeds",
    "sunflower seeds": "seeds",
    "sesame seeds": "sesame seeds",
    "olive oil": "olive oil",
    "vegetable stock": "stock",
    "vegetable broth": "stock",
    "chicken stock": "chicken stock",
    "chicken broth": "chicken stock",
    "beef stock": "beef stock",
    "rice noodle": "rice noodles",
    "egg noodle": "egg noodles",
    "potatoes": "potato",
    "tomatoes": "tomato",
    "carrots": "carrot",
    "onions": "onion",
    "lemons": "lemon",
    "limes": "lime",
    "mushrooms": "mushroom",
    "cucumbers": "cucumber",
}

MEAT_TERMS: frozenset[str] = frozenset(
    {
        "chicken",
        "beef",
        "pork",
        "lamb",
        "veal",
        "turkey",
        "duck",
        "bacon",
        "pancetta",
        "ham",
        "prosciutto",
        "sausage",
        "chorizo",
        "salami",
        "pepperoni",
        "mortadella",
        "guanciale",
        "steak",
        "filet mignon",
        "sirloin",
        "ribeye",
        "brisket",
        "oxtail",
        "venison",
        "rabbit",
        "goose",
        "quail",
        "pheasant",
        "cornish hen",
        "game hen",
        "poussin",
        "mince",
        "meatball",
        "meatballs",
        "chicken stock",
        "beef stock",
        "lard",
        "gelatin",
        "anchovy",  # fish, handled below; kept out of meat
    }
    - {"anchovy"}
)
FISH_TERMS: frozenset[str] = frozenset(
    {
        "salmon",
        "tuna",
        "cod",
        "haddock",
        "trout",
        "mackerel",
        "sardine",
        "sardines",
        "anchovy",
        "anchovies",
        "halibut",
        "sea bass",
        "fish",
        "fish sauce",
        "tilapia",
        "seafood",
        "snapper",
        "swordfish",
        "monkfish",
        "branzino",
        "sole",
        "pollock",
        "catfish",
        "herring",
        "bonito",
        "katsuobushi",
        "bottarga",
        "caviar",
        "roe",
        "worcestershire",
    }
)
SHELLFISH_TERMS: frozenset[str] = frozenset(
    {
        "shrimp",
        "prawn",
        "crab",
        "lobster",
        "clam",
        "clams",
        "mussel",
        "mussels",
        "oyster",
        "oysters",
        "oyster sauce",
        "scallop",
        "scallops",
        "squid",
        "calamari",
        "octopus",
        "crawfish",
        "langoustine",
        "shrimp paste",
    }
)
DAIRY_TERMS: frozenset[str] = frozenset(
    {
        "milk",
        "cream",
        "butter",
        "cheese",
        "yogurt",
        "parmesan",
        "mozzarella",
        "feta",
        "cheddar",
        "ricotta",
        "pecorino",
        "gruyere",
        "halloumi",
        "paneer",
        "ghee",
        "creme fraiche",
        "sour cream",
        "mascarpone",
        "buttermilk",
        "cream cheese",
        "labneh",
        "labne",
        "kefir",
        "skyr",
        "burrata",
        "stracciatella",
        "provolone",
        "fontina",
        "gouda",
        "brie",
        "gorgonzola",
        "manchego",
        "cotija",
        "queso",
        "half-and-half",
    }
)
# Egg counts only when egg is listed: mayonnaise and aioli can be made without it.
EGG_TERMS: frozenset[str] = frozenset({"egg", "eggs", "egg noodles"})

# Phrases that contain a flagged word but do not carry the flag.
_FLAG_EXCEPTIONS: dict[str, frozenset[str]] = {
    "dairy": frozenset(
        {
            "coconut milk",
            "coconut cream",
            "almond milk",
            "oat milk",
            "soy milk",
            "peanut butter",
            "almond butter",
            "cocoa butter",
            "cream of tartar",
            "cream tartar",
            "butter bean",
            "butter beans",
            "butter pickle",
            "vegan butter",
            "vegan cheese",
            "cashew cream",
        }
    ),
    "egg": frozenset({"eggplant"}),
    "meat": frozenset({"vegetable stock", "mushroom stock", "vegan sausage", "plant-based mince"}),
    "fish": frozenset({"vegan worcestershire"}),
    "shellfish": frozenset({"oyster mushroom"}),
}

# A food word that means something else in the rest of its line: "mixed mushrooms
# (oyster, shiitake)" lists a mushroom, "butter beans or cannellini" a bean.
_LINE_CONTEXT_EXCEPTIONS: dict[str, tuple[str, ...]] = {
    "oyster": ("mushroom",),
    "butter": ("butter bean", "bread and butter"),
    "cream": ("cream of tartar",),
}


_CATEGORY_TERMS: dict[str, frozenset[str]] = {
    "protein": MEAT_TERMS | FISH_TERMS | SHELLFISH_TERMS | frozenset({"tofu", "tempeh", "eggs"}),
    "legume": frozenset(
        {"chickpeas", "lentils", "black beans", "kidney beans", "white beans", "beans", "edamame"}
    ),
    "vegetable": frozenset(
        {
            "tomato",
            "cucumber",
            "arugula",
            "spinach",
            "kale",
            "cabbage",
            "carrot",
            "celery",
            "pumpkin",
            "squash",
            "zucchini",
            "eggplant",
            "bell pepper",
            "broccoli",
            "cauliflower",
            "potato",
            "sweet potato",
            "mushroom",
            "green onion",
            "leek",
            "corn",
            "peas",
            "green beans",
            "bok choy",
            "lettuce",
            "avocado",
            "beet",
            "beets",
            "asparagus",
            "fennel",
            "radish",
        }
    ),
    "grain": frozenset(
        {
            "quinoa",
            "rice",
            "pasta",
            "noodles",
            "rice noodles",
            "egg noodles",
            "bread",
            "couscous",
            "bulgur",
            "farro",
            "barley",
            "oats",
            "tortillas",
            "spaghetti",
            "penne",
            "orzo",
        }
    ),
    "dairy": DAIRY_TERMS,
    "herb": frozenset(
        {"cilantro", "parsley", "basil", "mint", "dill", "thyme", "rosemary", "chives", "oregano"}
    ),
    "aromatic": frozenset({"garlic", "onion", "ginger", "shallot", "shallots", "lemongrass"}),
    "pantry": frozenset(
        {
            "olive oil",
            "oil",
            "soy sauce",
            "fish sauce",
            "vinegar",
            "sugar",
            "flour",
            "salt",
            "pepper",
            "stock",
            "coconut milk",
            "curry paste",
            "red curry paste",
            "green curry paste",
            "miso",
            "tahini",
            "honey",
            "seeds",
            "sesame seeds",
            "nuts",
            "peanuts",
            "cashews",
            "almonds",
            "tomato paste",
            "canned tomatoes",
            "chili",
            "chilies",
            "chili flakes",
            "cumin",
            "paprika",
            "turmeric",
            "curry powder",
            "garam masala",
        }
    ),
}

# Words that are naturally plural as ingredient names.
_KEEP_PLURAL: frozenset[str] = frozenset(
    {
        "seeds",
        "chickpeas",
        "lentils",
        "oats",
        "noodles",
        "beans",
        "peas",
        "greens",
        "sprouts",
        "peanuts",
        "cashews",
        "almonds",
        "walnuts",
        "olives",
        "capers",
        "herbs",
        "grits",
        "eggs",
        "chives",
        "tortillas",
        "breadcrumbs",
        "raisins",
        "dates",
        "anchovies",
        "sardines",
        "ribs",
    }
)

_QUANTITY_RE = re.compile(
    r"^\s*(?P<qty>(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?|[½¼¾⅓⅔⅛])(?:\s*(?:-|to)\s*\d+(?:\.\d+)?)?)\s*"
)
_PAREN_RE = re.compile(r"\([^)]*\)")
_TOKEN_RE = re.compile(r"[a-z][a-z-]*")
# Cut descriptors written as "bone-in", "skin-on", "shell-on", "tail-off", "head-on".
_CUT_DESCRIPTOR_RE = re.compile(r"^[a-z]+-(?:in|on|off|out)$")
# Packing words that end the ingredient name: "sardines packed in olive oil" names the
# sardines, not the oil.
_NAME_STOP_WORDS: frozenset[str] = frozenset({"in"})
# Where one line can name a second food: "chicken thighs, or 8 shrimp", "(or use pork)".
_ALTERNATIVE_SPLIT_RE = re.compile(r"[,;()/]|\bor\b|\band\b|\bwith\b")


def _singularize(word: str) -> str:
    if len(word) <= 3 or word.endswith("ss") or word in _KEEP_PLURAL:
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("oes"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("us"):
        return word[:-1]
    return word


def _is_descriptor(token: str) -> bool:
    return token in _UNITS or token in _DESCRIPTORS or bool(_CUT_DESCRIPTOR_RE.match(token))


def _content_tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if not _is_descriptor(t)]


def _split_preparation(text: str) -> tuple[str, str | None]:
    """Split "cabbage, shredded" into (name, preparation).

    "boneless, skinless chicken thighs" and "bone-in, skin-on chicken thighs" are *not*
    split because the head carries no ingredient words of its own.
    """
    if "," in text:
        head, _, tail = text.partition(",")
        if _content_tokens(head):
            return head.strip(), tail.strip() or None
        # A descriptor-only head joins the name; a later comma still starts the
        # preparation ("bone-in, skin-on chicken thighs, patted dry").
        return _split_preparation(f"{head.strip()} {tail.strip()}")
    return text.strip(), None


def _strip_accents(text: str) -> str:
    """ "crème fraîche" -> "creme fraiche". NFD, not NFKD, so "½" survives."""
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))


def canonical_name(text: str) -> str:
    """Reduce free-form ingredient text to a canonical lowercase name."""
    lowered = _PAREN_RE.sub(" ", _strip_accents(text.lower()))
    lowered = lowered.replace("\u2019", "'")
    lowered = _QUANTITY_RE.sub("", lowered)
    head, _ = _split_preparation(lowered)
    tokens = _content_tokens(head)
    if not tokens:
        tokens = _TOKEN_RE.findall(head) or [head.strip()]
    phrase = " ".join(tokens).strip()
    if phrase in ALIASES:
        return ALIASES[phrase]
    stop = next((i for i, t in enumerate(tokens) if t in _NAME_STOP_WORDS), None)
    if stop:
        tokens = tokens[:stop]
    # Try progressively shorter tails ("boneless skinless chicken thighs" -> "chicken thighs").
    for start in range(len(tokens)):
        tail = " ".join(tokens[start:])
        if tail in ALIASES:
            return ALIASES[tail]
    singular = " ".join([*tokens[:-1], _singularize(tokens[-1])]) if tokens else phrase
    return ALIASES.get(singular, singular)


def _phrase_matches(name: str, terms: frozenset[str]) -> bool:
    words = name.split()
    if name in terms:
        return True
    for term in terms:
        term_words = term.split()
        n = len(term_words)
        if n == 1:
            if term in words:
                return True
        elif any(words[i : i + n] == term_words for i in range(len(words) - n + 1)):
            return True
    return False


def flags_for_name(name: str) -> IngredientFlags:
    def flagged(kind: str, terms: frozenset[str]) -> bool:
        exceptions = _FLAG_EXCEPTIONS.get(kind, frozenset())
        if any(exc in name for exc in exceptions):
            return False
        return _phrase_matches(name, terms)

    return IngredientFlags(
        contains_meat=flagged("meat", MEAT_TERMS),
        contains_fish=flagged("fish", FISH_TERMS),
        contains_shellfish=flagged("shellfish", SHELLFISH_TERMS),
        contains_dairy=flagged("dairy", DAIRY_TERMS),
        contains_egg=flagged("egg", EGG_TERMS),
    )


_PLANT_PROTEINS: frozenset[str] = frozenset({"tofu", "tempeh", "eggs"})


def category_for_name(name: str) -> str:
    for category, terms in _CATEGORY_TERMS.items():
        if not _phrase_matches(name, terms):
            continue
        # "oyster mushroom" and "cream of tartar" match an animal word but are not one.
        if category == "protein" and not _phrase_matches(name, _PLANT_PROTEINS):
            flags = flags_for_name(name)
            if not (flags.contains_meat or flags.contains_fish or flags.contains_shellfish):
                continue
        if category == "dairy" and not flags_for_name(name).contains_dairy:
            continue
        return category
    return "other"


def is_staple(name: str) -> bool:
    return staples_registry.is_staple(name)


def normalize_ingredient(raw_text: str) -> RecipeIngredient:
    """Parse a single free-form ingredient line into a structured ingredient."""
    lowered = raw_text.strip()
    qty_match = _QUANTITY_RE.match(lowered.lower())
    quantity: str | None = None
    remainder = lowered
    if qty_match:
        quantity = qty_match.group("qty").strip()
        remainder = lowered[qty_match.end() :]
        unit_match = re.match(r"^(\S+)\s+", remainder.lower())
        if unit_match and unit_match.group(1) in _UNITS:
            quantity = f"{quantity} {unit_match.group(1)}"
    _, preparation = _split_preparation(remainder)
    name = canonical_name(raw_text)
    return RecipeIngredient(
        canonical_name=name,
        raw_text=raw_text.strip(),
        quantity=quantity,
        preparation=preparation,
        category=category_for_name(name),
        is_staple=is_staple(name),
        flags=flags_for_name(name),
    )


def _food_terms(name: str) -> list[str]:
    """The lexicon words that give ``name`` its food types, longest phrase first.

    "chicken stock" yields "chicken stock", not also "chicken"; exceptions such as
    "coconut milk" suppress their kind exactly as :func:`flags_for_name` does.
    """
    found: list[str] = []
    for kind, terms in (
        ("meat", MEAT_TERMS),
        ("fish", FISH_TERMS),
        ("shellfish", SHELLFISH_TERMS),
        ("dairy", DAIRY_TERMS),
        ("egg", EGG_TERMS),
    ):
        if any(exc in name for exc in _FLAG_EXCEPTIONS.get(kind, frozenset())):
            continue
        found.extend(t for t in terms if _phrase_matches(name, frozenset({t})))
    return [t for t in found if not any(t != o and f" {t} " in f" {o} " for o in found)]


def other_foods_in_line(raw_text: str, main_name: str) -> list[RecipeIngredient]:
    """Foods with a food type that a line names besides its main ingredient.

    "2 chicken thighs, cut into cubes, or 8 shrimp" can need chicken or shrimp, so the
    recipe carries both food types: alternatives count. Food types belong to an
    ingredient name and are shared across recipes, so each extra food becomes its own
    ingredient, named by the food word itself, rather than widening the main one.
    """
    line = raw_text.lower()
    covered = set(_food_terms(main_name))
    names = {main_name}
    found: list[RecipeIngredient] = []
    for segment in _ALTERNATIVE_SPLIT_RE.split(line):
        # "for forming the meatballs" says how the line is used, not what it is.
        if not _content_tokens(segment) or segment.strip().startswith("for "):
            continue
        for term in _food_terms(canonical_name(segment)):
            if term in covered or any(c in line for c in _LINE_CONTEXT_EXCEPTIONS.get(term, ())):
                continue
            name = ALIASES.get(term, term)
            covered.add(term)
            if name in names:
                continue
            names.add(name)
            found.append(
                RecipeIngredient(
                    canonical_name=name,
                    raw_text=raw_text.strip(),
                    category=category_for_name(name),
                    is_staple=is_staple(name),
                    flags=flags_for_name(name),
                )
            )
    return found


# The author says the line can be left out: optional, or a garnish.
_LEAVE_OUT_RE = re.compile(
    r"\boptional\b|\bif desired\b|\bif you like\b|\bto (?:serve|garnish)\b|\bgarnish"
    r"|\bfor (?:serving|topping|garnishing|sprinkling|drizzling|dipping)\b|^toppings?\b"
)
_OR_RE = re.compile(r"\bor\b")
_SEGMENT_RE = re.compile(r"[,;()/]")
# Foods the lexicons do not categorise but that are real choices on a line
# ("water or chicken broth", "plant-based meat").
_PLAIN_FOOD_WORDS: frozenset[str] = frozenset(
    {"water", "wine", "juice", "broth", "stock", "oil", "vinegar", "margarine", "seitan"}
    | {"plant-based", "vegan", "vegetarian", "cashew", "coconut", "almond", "oat", "soy"}
)


@dataclass(frozen=True)
class LineChoice:
    """One food the author offers on a line: "vegetable broth" in "chicken or vegetable
    broth". ``label`` is the text as written, without quantities or units."""

    label: str
    name: str
    flags: IngredientFlags


@dataclass(frozen=True)
class LineChoices:
    """What the author lets the cook choose on one ingredient line."""

    can_leave_out: bool
    options: tuple[LineChoice, ...]


def _choice(segment: str) -> LineChoice | None:
    """The food a segment names, or ``None`` for a describing word ("Mexican") or a
    preparation ("cut into cubes")."""
    tokens = _content_tokens(segment)
    if not tokens:
        return None
    name = canonical_name(segment)
    flags = flags_for_name(name)
    words = set(name.split()) | set(tokens)
    if (
        not any(flags.model_dump().values())
        and category_for_name(name) == "other"
        and not words & _PLAIN_FOOD_WORDS
    ):
        return None
    label = " ".join(tokens).split(" with ")[0]
    return LineChoice(label=label, name=name, flags=flags)


def line_choices(raw_text: str) -> LineChoices:
    """Read the choices an ingredient line states. Nothing is inferred.

    "1 quart chicken or vegetable broth" offers chicken broth or vegetable broth;
    "Parmesan, for serving" and "(optional)" lines can be left out. Only the foods on
    either side of an "or" are options, so "cut into cubes, or 8 shrimp" offers
    chicken or shrimp, and a list before the "or" ("water, seafood stock or chicken
    stock") offers every item in it.
    """
    line = _strip_accents(raw_text.lower()).strip()
    can_leave_out = bool(_LEAVE_OUT_RE.search(line))
    parts = _OR_RE.split(line)
    # A garnish list with several "or"s ("nuts or seeds, herbs, grated or crumbled
    # cheese, egg") is a list of extras, not a menu: its choice is to leave it out.
    if len(parts) < 2 or (can_leave_out and len(parts) > 2):
        return LineChoices(can_leave_out=can_leave_out, options=())
    options: list[LineChoice] = []
    for index, part in enumerate(parts):
        segments = [s for s in _SEGMENT_RE.split(part) if _content_tokens(s)]
        if index > 0:
            segments.reverse()  # after an "or", read forward from it
        run: list[LineChoice] = []
        for segment in reversed(segments):  # nearest the "or" first
            found = _choice(segment)
            if found is None:
                if run:
                    break
                continue
            run.append(found)
            if index not in (0, len(parts) - 1):
                continue  # a middle part is one option ("…, pancetta or bacon")
        options.extend(run)
    unique = {o.name: o for o in options}
    return LineChoices(can_leave_out=can_leave_out, options=tuple(unique.values()))


def normalize_line(raw_text: str) -> list[RecipeIngredient]:
    """One ingredient line: its main ingredient first, then any other flagged foods."""
    main = normalize_ingredient(raw_text)
    return [main, *other_foods_in_line(raw_text, main.canonical_name)]


def normalize_ingredients(lines: list[str]) -> list[RecipeIngredient]:
    """Main ingredients in line order, then other foods the lines name, deduplicated.

    Main ingredients come first so a line of its own ("1 pound shrimp") keeps its
    quantity even when an earlier line mentioned shrimp as an alternative.
    """
    lines = [line for line in dict.fromkeys(lines) if line.strip()]
    mains = [normalize_ingredient(line) for line in lines]
    seen: set[str] = set()
    result: list[RecipeIngredient] = []
    candidates = [
        *mains,
        *(
            o
            for line, m in zip(lines, mains, strict=True)
            for o in other_foods_in_line(line, m.canonical_name)
        ),
    ]
    for ingredient in candidates:
        if ingredient.canonical_name not in seen:
            seen.add(ingredient.canonical_name)
            result.append(ingredient)
    return result


def ingredient_matches(available: str, canonical: str) -> bool:
    """True when an available pantry item satisfies a recipe ingredient."""
    a = canonical_name(available)
    if a == canonical:
        return True
    a_words = set(a.split())
    c_words = set(canonical.split())
    if not a_words or not c_words:
        return False
    # "salmon" satisfies "salmon fillet"; "cabbage" satisfies "napa cabbage".
    return a_words <= c_words or c_words <= a_words


# Broad main-ingredient requests ("bean-based", "seafood") and what each one covers.
_GROUP_ALIASES: dict[str, str] = {
    "bean": "legumes",
    "beans": "legumes",
    "legume": "legumes",
    "legumes": "legumes",
    "pulse": "legumes",
    "pulses": "legumes",
    "fish": "fish",
    "seafood": "seafood",
    "shellfish": "shellfish",
    "meat": "meat",
    "poultry": "poultry",
}
_LEGUME_WORDS: frozenset[str] = frozenset(
    {"bean", "beans", "lentil", "lentils", "chickpea", "chickpeas", "legumes", "dal", "dhal"}
)
_POULTRY_WORDS: frozenset[str] = frozenset(
    {"chicken", "turkey", "duck", "goose", "quail", "pheasant", "hen", "poussin"}
)
_GROUPS: dict[str, Callable[[str], bool]] = {
    "legumes": lambda n: category_for_name(n) == "legume" or bool(set(n.split()) & _LEGUME_WORDS),
    "fish": lambda n: flags_for_name(n).contains_fish,
    "shellfish": lambda n: flags_for_name(n).contains_shellfish,
    "seafood": lambda n: flags_for_name(n).contains_fish or flags_for_name(n).contains_shellfish,
    "meat": lambda n: flags_for_name(n).contains_meat,
    "poultry": lambda n: bool(set(n.split()) & _POULTRY_WORDS),
}
_BASED_RE = re.compile(r"[\s-]*\bbased\b|\bdish(?:es)?\b|\bmeals?\b|\brecipes?\b")


def main_ingredient_group(wanted: str) -> str | None:
    """The group a broad request names ("bean-based" -> "legumes"), if any."""
    return _GROUP_ALIASES.get(_BASED_RE.sub(" ", wanted.lower()).strip())


def matches_main_ingredient(wanted: str, name: str) -> bool:
    """True when an ingredient name satisfies a main-ingredient request.

    "mushroom" matches "oyster mushroom"; "bean-based" matches chickpeas and lentils.
    """
    group = main_ingredient_group(wanted)
    if group is not None:
        return _GROUPS[group](name)
    cleaned = _BASED_RE.sub(" ", wanted.lower()).strip()
    return bool(cleaned) and ingredient_matches(cleaned, name)


def title_mentions_main_ingredient(wanted: str, title: str) -> bool:
    """Fallback for recipes with no main-ingredient label: does the title name it?"""
    tokens = _TOKEN_RE.findall(title.lower())
    group = main_ingredient_group(wanted)
    if group is not None:
        return any(_GROUPS[group](canonical_name(t)) for t in tokens)
    wanted_words = {_singularize(t) for t in _content_tokens(_BASED_RE.sub(" ", wanted))}
    title_words = {_singularize(t) for t in tokens}
    return bool(wanted_words) and wanted_words <= title_words
