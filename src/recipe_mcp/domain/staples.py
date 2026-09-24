"""Household staples registry, seeded from ``evals/recipes/staples.yaml``.

Kept separate from the ingredient lexicon so the household can edit the list
without touching code. Loading happens once per process; ``reload`` exists for
``make categorize`` and tests.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STAPLES_FILE = REPO_ROOT / "evals" / "recipes" / "staples.yaml"

_FALLBACK: frozenset[str] = frozenset(
    {
        "salt",
        "pepper",
        "salt and pepper",
        "olive oil",
        "oil",
        "water",
        "sugar",
        "flour",
        "garlic",
        "onion",
        "butter",
        "soy sauce",
        "vinegar",
        "lemon",
        "lime",
        "stock",
        "eggs",
    }
)

_staples: frozenset[str] = _FALLBACK


def load_staples(path: Path = DEFAULT_STAPLES_FILE) -> frozenset[str]:
    if not path.exists():
        return _FALLBACK
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    values = data.get("staples", []) if isinstance(data, dict) else data
    return frozenset(str(v).strip().lower() for v in values if str(v).strip())


def reload(path: Path = DEFAULT_STAPLES_FILE) -> frozenset[str]:
    global _staples
    _staples = load_staples(path)
    return _staples


def staples() -> frozenset[str]:
    return _staples


def is_staple(name: str) -> bool:
    return name in _staples


reload()
