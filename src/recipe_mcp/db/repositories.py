"""Repositories: the only place SQL is written.

Each repository takes a :class:`Database` and returns domain models. Replacing
SQLite with Postgres later means re-implementing this module, nothing else.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict

from recipe_mcp.db.connection import Database
from recipe_mcp.domain.models import (
    Classification,
    FacetSource,
    Feedback,
    Household,
    IngredientFlags,
    Member,
    ModelRun,
    Recipe,
    RecipeIngredient,
    RecipeStatus,
    Sentiment,
    SourceType,
    utcnow_iso,
)
from recipe_mcp.domain.taxonomy import Facet

PENDING_KINDS: tuple[str, ...] = (
    "recent_results",
    "photo_confirmation",
    "draft_confirmation",
    "turn_history",
)


def _flags_from_row(row: sqlite3.Row) -> IngredientFlags:
    return IngredientFlags(
        contains_meat=bool(row["contains_meat"]),
        contains_fish=bool(row["contains_fish"]),
        contains_shellfish=bool(row["contains_shellfish"]),
        contains_dairy=bool(row["contains_dairy"]),
        contains_egg=bool(row["contains_egg"]),
    )


class HouseholdRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, name: str) -> Household:
        household = Household(name=name)
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO households (name, created_at) VALUES (?, ?)",
                (household.name, household.created_at),
            )
            household.id = cur.lastrowid
        return household

    def get(self, household_id: int) -> Household | None:
        row = self.db.connection.execute(
            "SELECT * FROM households WHERE id = ?", (household_id,)
        ).fetchone()
        return Household(**dict(row)) if row else None

    def first(self) -> Household | None:
        row = self.db.connection.execute("SELECT * FROM households ORDER BY id LIMIT 1").fetchone()
        return Household(**dict(row)) if row else None

    def get_or_create_default(self, name: str = "Home") -> Household:
        return self.first() or self.create(name)


class MemberRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, member: Member) -> Member:
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO members (household_id, member_key, display_name, telegram_user_id, "
                "whatsapp_export_name, normalized_phone_number, role, active) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    member.household_id,
                    member.member_key.lower(),
                    member.display_name,
                    member.telegram_user_id,
                    member.whatsapp_export_name,
                    member.normalized_phone_number,
                    member.role,
                    int(member.active),
                ),
            )
            member.id = cur.lastrowid
        return member

    def upsert(self, member: Member) -> Member:
        """Insert or update by (household, member_key). Used by the members.yaml sync."""
        existing = self.by_key(member.household_id, member.member_key)
        if existing is None:
            return self.create(member)
        member.id = existing.id
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE members SET display_name=?, telegram_user_id=?, whatsapp_export_name=?, "
                "normalized_phone_number=?, role=?, active=? WHERE id=?",
                (
                    member.display_name,
                    member.telegram_user_id,
                    member.whatsapp_export_name,
                    member.normalized_phone_number,
                    member.role,
                    int(member.active),
                    member.id,
                ),
            )
        return member

    def get(self, member_id: int) -> Member | None:
        row = self.db.connection.execute(
            "SELECT * FROM members WHERE id = ?", (member_id,)
        ).fetchone()
        return self._to_model(row) if row else None

    def by_key(self, household_id: int, member_key: str) -> Member | None:
        row = self.db.connection.execute(
            "SELECT * FROM members WHERE household_id = ? AND member_key = ?",
            (household_id, member_key.strip().lower()),
        ).fetchone()
        return self._to_model(row) if row else None

    def by_telegram_id(self, telegram_user_id: int) -> Member | None:
        row = self.db.connection.execute(
            "SELECT * FROM members WHERE telegram_user_id = ?", (telegram_user_id,)
        ).fetchone()
        return self._to_model(row) if row else None

    def by_export_name(self, household_id: int, name: str) -> Member | None:
        row = self.db.connection.execute(
            "SELECT * FROM members WHERE household_id = ? AND ("
            "lower(whatsapp_export_name) = lower(?) OR lower(display_name) = lower(?))",
            (household_id, name.strip(), name.strip()),
        ).fetchone()
        return self._to_model(row) if row else None

    def by_name(self, household_id: int, display_name: str) -> Member | None:
        row = self.db.connection.execute(
            "SELECT * FROM members WHERE household_id = ? AND ("
            "lower(display_name) = lower(?) OR member_key = lower(?))",
            (household_id, display_name.strip(), display_name.strip()),
        ).fetchone()
        return self._to_model(row) if row else None

    def list_for_household(self, household_id: int) -> list[Member]:
        rows = self.db.connection.execute(
            "SELECT * FROM members WHERE household_id = ? ORDER BY id", (household_id,)
        ).fetchall()
        return [self._to_model(r) for r in rows]

    @staticmethod
    def _to_model(row: sqlite3.Row) -> Member:
        data = dict(row)
        data["active"] = bool(data["active"])
        return Member(**data)


class RecipeRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- writes -----------------------------------------------------------

    def create(self, recipe: Recipe) -> Recipe:
        if not recipe.content_hash:
            recipe.content_hash = recipe.compute_content_hash()
        now = utcnow_iso()
        recipe.added_at = recipe.added_at or now
        recipe.updated_at = now
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO recipes (household_id, source_type, canonical_source_url, title, "
                "servings, total_minutes, notes, status, content_hash, added_by_member_id, "
                "added_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    recipe.household_id,
                    recipe.source_type.value,
                    recipe.canonical_source_url,
                    recipe.title,
                    recipe.servings,
                    recipe.total_minutes,
                    json.dumps(recipe.notes),
                    recipe.status.value,
                    recipe.content_hash,
                    recipe.added_by_member_id,
                    recipe.added_at,
                    recipe.updated_at,
                ),
            )
            recipe.id = cur.lastrowid
            assert recipe.id is not None
            self._write_ingredients(conn, recipe.id, recipe.ingredients)
            self._write_classifications(conn, recipe.id, recipe.classifications)
        return recipe

    def update(self, recipe: Recipe) -> Recipe:
        assert recipe.id is not None, "recipe must be stored before update"
        recipe.updated_at = utcnow_iso()
        recipe.content_hash = recipe.compute_content_hash()
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE recipes SET title=?, servings=?, total_minutes=?, notes=?, status=?, "
                "content_hash=?, added_by_member_id=?, updated_at=? WHERE id=?",
                (
                    recipe.title,
                    recipe.servings,
                    recipe.total_minutes,
                    json.dumps(recipe.notes),
                    recipe.status.value,
                    recipe.content_hash,
                    recipe.added_by_member_id,
                    recipe.updated_at,
                    recipe.id,
                ),
            )
            conn.execute("DELETE FROM recipe_ingredients WHERE recipe_id = ?", (recipe.id,))
            self._write_ingredients(conn, recipe.id, recipe.ingredients)
        return recipe

    def replace_classifications(
        self, recipe_id: int, classifications: list[Classification], keep_user: bool = True
    ) -> None:
        with self.db.transaction() as conn:
            if keep_user:
                conn.execute(
                    "DELETE FROM recipe_facets WHERE recipe_id = ? AND user_confirmed = 0",
                    (recipe_id,),
                )
                existing = {
                    (r["facet"], r["value"])
                    for r in conn.execute(
                        "SELECT facet, value FROM recipe_facets WHERE recipe_id = ?", (recipe_id,)
                    )
                }
                user_facets = {f for f, _ in existing}
                classifications = [
                    c
                    for c in classifications
                    if (c.facet.value, c.value) not in existing
                    and (c.facet.value not in user_facets or c.source == FacetSource.RULE)
                ]
            else:
                conn.execute("DELETE FROM recipe_facets WHERE recipe_id = ?", (recipe_id,))
            self._write_classifications(conn, recipe_id, classifications)

    def replace_facet(
        self, recipe_id: int, facet: Facet, classifications: list[Classification]
    ) -> None:
        """Replace one facet's unconfirmed values, leaving every other facet untouched."""
        with self.db.transaction() as conn:
            conn.execute(
                "DELETE FROM recipe_facets "
                "WHERE recipe_id = ? AND facet = ? AND user_confirmed = 0",
                (recipe_id, facet.value),
            )
            self._write_classifications(
                conn, recipe_id, [c for c in classifications if c.facet == facet]
            )

    def set_food_types(
        self,
        recipe_id: int,
        canonical_name: str,
        flags: IngredientFlags,
        member_id: int | None = None,
    ) -> None:
        """Record a person's food types for one ingredient in one recipe."""
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO recipe_ingredient_food_types (recipe_id, canonical_name, "
                "contains_meat, contains_fish, contains_shellfish, contains_dairy, contains_egg, "
                "member_id, created_at) VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(recipe_id, canonical_name) DO UPDATE SET "
                "contains_meat=excluded.contains_meat, contains_fish=excluded.contains_fish, "
                "contains_shellfish=excluded.contains_shellfish, "
                "contains_dairy=excluded.contains_dairy, contains_egg=excluded.contains_egg, "
                "member_id=excluded.member_id, created_at=excluded.created_at",
                (
                    recipe_id,
                    canonical_name,
                    int(flags.contains_meat),
                    int(flags.contains_fish),
                    int(flags.contains_shellfish),
                    int(flags.contains_dairy),
                    int(flags.contains_egg),
                    member_id,
                    utcnow_iso(),
                ),
            )

    def confirm_facet(self, recipe_id: int, facet: Facet, values: list[str]) -> None:
        """Record a user correction: the given values replace every value for the facet."""
        now = utcnow_iso()
        with self.db.transaction() as conn:
            conn.execute(
                "DELETE FROM recipe_facets WHERE recipe_id = ? AND facet = ?",
                (recipe_id, facet.value),
            )
            for value in values:
                conn.execute(
                    "INSERT INTO recipe_facets (recipe_id, facet, value, source, confidence, "
                    "user_confirmed, needs_review, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (recipe_id, facet.value, value, FacetSource.USER.value, 1.0, 1, 0, now, now),
                )

    def refresh_staples(self, staples: frozenset[str]) -> int:
        """Re-apply the staples list to stored ingredients. Returns rows changed."""
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT id, canonical_name, is_staple FROM ingredients").fetchall()
            changed = 0
            for row in rows:
                should = int(row["canonical_name"] in staples)
                if should != row["is_staple"]:
                    conn.execute(
                        "UPDATE ingredients SET is_staple = ? WHERE id = ?", (should, row["id"])
                    )
                    changed += 1
        return changed

    # -- reads ------------------------------------------------------------

    def get(self, recipe_id: int) -> Recipe | None:
        row = self.db.connection.execute(
            "SELECT * FROM recipes WHERE id = ?", (recipe_id,)
        ).fetchone()
        if not row:
            return None
        return self._hydrate([row])[0]

    def find_by_url(self, household_id: int, canonical_url: str) -> Recipe | None:
        row = self.db.connection.execute(
            "SELECT * FROM recipes WHERE household_id = ? AND canonical_source_url = ?",
            (household_id, canonical_url),
        ).fetchone()
        return self._hydrate([row])[0] if row else None

    def find_by_content_hash(self, household_id: int, content_hash: str) -> Recipe | None:
        row = self.db.connection.execute(
            "SELECT * FROM recipes WHERE household_id = ? AND content_hash = ?",
            (household_id, content_hash),
        ).fetchone()
        return self._hydrate([row])[0] if row else None

    def list_for_household(self, household_id: int) -> list[Recipe]:
        rows = self.db.connection.execute(
            "SELECT * FROM recipes WHERE household_id = ? ORDER BY id", (household_id,)
        ).fetchall()
        return self._hydrate(rows)

    def list_uncategorized(self, household_id: int) -> list[Recipe]:
        """Recipes with ingredients but no model or user classification yet."""
        rows = self.db.connection.execute(
            "SELECT r.* FROM recipes r WHERE r.household_id = ? "
            "AND EXISTS (SELECT 1 FROM recipe_ingredients ri WHERE ri.recipe_id = r.id) "
            "AND NOT EXISTS (SELECT 1 FROM recipe_facets f WHERE f.recipe_id = r.id "
            "AND f.source IN ('model','user')) ORDER BY r.id",
            (household_id,),
        ).fetchall()
        return self._hydrate(rows)

    def count(self, household_id: int) -> int:
        row = self.db.connection.execute(
            "SELECT COUNT(*) AS n FROM recipes WHERE household_id = ?", (household_id,)
        ).fetchone()
        return int(row["n"])

    # -- internals --------------------------------------------------------

    def _write_ingredients(
        self, conn: sqlite3.Connection, recipe_id: int, ingredients: list[RecipeIngredient]
    ) -> None:
        for position, ingredient in enumerate(ingredients):
            f = ingredient.flags
            conn.execute(
                "INSERT INTO ingredients (canonical_name, category, is_staple, contains_meat, "
                "contains_fish, contains_shellfish, contains_dairy, contains_egg) "
                "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(canonical_name) DO UPDATE SET "
                "category=excluded.category, is_staple=excluded.is_staple, "
                "contains_meat=excluded.contains_meat, contains_fish=excluded.contains_fish, "
                "contains_shellfish=excluded.contains_shellfish, "
                "contains_dairy=excluded.contains_dairy, contains_egg=excluded.contains_egg",
                (
                    ingredient.canonical_name,
                    ingredient.category,
                    int(ingredient.is_staple),
                    int(f.contains_meat),
                    int(f.contains_fish),
                    int(f.contains_shellfish),
                    int(f.contains_dairy),
                    int(f.contains_egg),
                ),
            )
            ingredient_id = conn.execute(
                "SELECT id FROM ingredients WHERE canonical_name = ?", (ingredient.canonical_name,)
            ).fetchone()["id"]
            conn.execute(
                "INSERT OR REPLACE INTO recipe_ingredients (recipe_id, ingredient_id, position, "
                "raw_text, quantity, preparation) VALUES (?,?,?,?,?,?)",
                (
                    recipe_id,
                    ingredient_id,
                    position,
                    ingredient.raw_text,
                    ingredient.quantity,
                    ingredient.preparation,
                ),
            )

    @staticmethod
    def _write_classifications(
        conn: sqlite3.Connection, recipe_id: int, classifications: list[Classification]
    ) -> None:
        now = utcnow_iso()
        for c in classifications:
            if not c.value:
                continue
            conn.execute(
                "INSERT INTO recipe_facets (recipe_id, facet, value, source, confidence, "
                "model_version, prompt_version, user_confirmed, needs_review, proposed_value, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(recipe_id, facet, value) DO UPDATE SET source=excluded.source, "
                "confidence=excluded.confidence, model_version=excluded.model_version, "
                "prompt_version=excluded.prompt_version, needs_review=excluded.needs_review, "
                "proposed_value=excluded.proposed_value, updated_at=excluded.updated_at",
                (
                    recipe_id,
                    c.facet.value,
                    c.value,
                    c.source.value,
                    c.confidence,
                    c.model_version,
                    c.prompt_version,
                    int(c.user_confirmed),
                    int(c.needs_review),
                    c.proposed_value,
                    now,
                    now,
                ),
            )

    def _hydrate(self, rows: list[sqlite3.Row]) -> list[Recipe]:
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" * len(ids))
        ingredient_rows = self.db.connection.execute(
            "SELECT ri.recipe_id, ri.raw_text, ri.quantity, ri.preparation, i.* "
            "FROM recipe_ingredients ri JOIN ingredients i ON i.id = ri.ingredient_id "
            f"WHERE ri.recipe_id IN ({placeholders}) ORDER BY ri.recipe_id, ri.position",
            ids,
        ).fetchall()
        facet_rows = self.db.connection.execute(
            f"SELECT * FROM recipe_facets WHERE recipe_id IN ({placeholders}) ORDER BY id", ids
        ).fetchall()
        overrides = {
            (r["recipe_id"], r["canonical_name"]): _flags_from_row(r)
            for r in self.db.connection.execute(
                f"SELECT * FROM recipe_ingredient_food_types WHERE recipe_id IN ({placeholders})",
                ids,
            )
        }

        ingredients: dict[int, list[RecipeIngredient]] = defaultdict(list)
        for r in ingredient_rows:
            ingredients[r["recipe_id"]].append(
                RecipeIngredient(
                    canonical_name=r["canonical_name"],
                    raw_text=r["raw_text"],
                    quantity=r["quantity"],
                    preparation=r["preparation"],
                    category=r["category"],
                    is_staple=bool(r["is_staple"]),
                    flags=_flags_from_row(r),
                    food_types_override=overrides.get((r["recipe_id"], r["canonical_name"])),
                )
            )
        classifications: dict[int, list[Classification]] = defaultdict(list)
        for r in facet_rows:
            classifications[r["recipe_id"]].append(
                Classification(
                    facet=Facet(r["facet"]),
                    value=r["value"],
                    source=FacetSource(r["source"]),
                    confidence=r["confidence"],
                    model_version=r["model_version"],
                    prompt_version=r["prompt_version"],
                    user_confirmed=bool(r["user_confirmed"]),
                    needs_review=bool(r["needs_review"]),
                    proposed_value=r["proposed_value"],
                )
            )
        recipes: list[Recipe] = []
        for row in rows:
            data = dict(row)
            recipes.append(
                Recipe(
                    id=data["id"],
                    household_id=data["household_id"],
                    source_type=SourceType(data["source_type"]),
                    canonical_source_url=data["canonical_source_url"],
                    title=data["title"],
                    servings=data["servings"],
                    total_minutes=data["total_minutes"],
                    notes=json.loads(data["notes"] or "[]"),
                    status=RecipeStatus(data["status"]),
                    content_hash=data["content_hash"],
                    added_by_member_id=data["added_by_member_id"],
                    added_at=data["added_at"],
                    updated_at=data["updated_at"],
                    ingredients=ingredients.get(data["id"], []),
                    classifications=classifications.get(data["id"], []),
                )
            )
        return recipes


class FeedbackRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, feedback: Feedback) -> Feedback:
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO recipe_feedback (recipe_id, member_id, reported_by_member_id, "
                "sentiment, notes, cooked_at, created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    feedback.recipe_id,
                    feedback.member_id,
                    feedback.reported_by_member_id,
                    feedback.sentiment.value,
                    feedback.notes,
                    feedback.cooked_at,
                    feedback.created_at,
                ),
            )
            feedback.id = cur.lastrowid
        return feedback

    def for_recipe(self, recipe_id: int) -> list[Feedback]:
        rows = self.db.connection.execute(
            "SELECT * FROM recipe_feedback WHERE recipe_id = ? ORDER BY created_at, id",
            (recipe_id,),
        ).fetchall()
        return [self._to_model(r) for r in rows]

    def for_household(self, household_id: int) -> dict[int, list[Feedback]]:
        rows = self.db.connection.execute(
            "SELECT f.* FROM recipe_feedback f JOIN recipes r ON r.id = f.recipe_id "
            "WHERE r.household_id = ? ORDER BY f.created_at, f.id",
            (household_id,),
        ).fetchall()
        grouped: dict[int, list[Feedback]] = defaultdict(list)
        for r in rows:
            grouped[r["recipe_id"]].append(self._to_model(r))
        return dict(grouped)

    @staticmethod
    def _to_model(row: sqlite3.Row) -> Feedback:
        data = dict(row)
        data["sentiment"] = Sentiment(data["sentiment"])
        return Feedback(**data)


class ModelRunRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(self, run: ModelRun) -> ModelRun:
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO model_runs (task, input_hash, provider, model, prompt_version, "
                "latency_ms, input_tokens, output_tokens, validation_status, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    run.task,
                    run.input_hash,
                    run.provider,
                    run.model,
                    run.prompt_version,
                    run.latency_ms,
                    run.input_tokens,
                    run.output_tokens,
                    run.validation_status,
                    run.created_at,
                ),
            )
            run.id = cur.lastrowid
        return run

    def count(self) -> int:
        row = self.db.connection.execute("SELECT COUNT(*) AS n FROM model_runs").fetchone()
        return int(row["n"])

    def cache_get(self, task: str, input_hash: str, prompt_version: str, model: str) -> str | None:
        row = self.db.connection.execute(
            "SELECT output_json FROM model_cache "
            "WHERE task=? AND input_hash=? AND prompt_version=? AND model=?",
            (task, input_hash, prompt_version, model),
        ).fetchone()
        return row["output_json"] if row else None

    def cache_put(
        self, task: str, input_hash: str, prompt_version: str, model: str, output_json: str
    ) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO model_cache (task, input_hash, prompt_version, model, "
                "output_json, created_at) VALUES (?,?,?,?,?,?)",
                (task, input_hash, prompt_version, model, output_json, utcnow_iso()),
            )


class AppStateRepository:
    """Operational values kept across restarts, such as the Telegram update offset."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, key: str) -> str | None:
        row = self.db.connection.execute(
            "SELECT value FROM app_state WHERE key = ?", (key,)
        ).fetchone()
        return str(row["value"]) if row else None

    def set(self, key: str, value: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO app_state (key, value, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at",
                (key, value, utcnow_iso()),
            )


class PendingInteractionRepository:
    """Per-chat conversation state. Rows are removed on expiry; nothing lives elsewhere."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def put(self, chat_id: str, kind: str, payload: dict[str, object], expires_at: str) -> None:
        if kind not in PENDING_KINDS:
            raise ValueError(f"unknown pending interaction kind: {kind}")
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO pending_interactions (chat_id, kind, payload, expires_at, created_at)"
                " VALUES (?,?,?,?,?) ON CONFLICT(chat_id, kind) DO UPDATE SET "
                "payload=excluded.payload, expires_at=excluded.expires_at, "
                "created_at=excluded.created_at",
                (str(chat_id), kind, json.dumps(payload), expires_at, utcnow_iso()),
            )

    def get(self, chat_id: str, kind: str) -> dict[str, object] | None:
        self.purge_expired()
        row = self.db.connection.execute(
            "SELECT payload FROM pending_interactions WHERE chat_id = ? AND kind = ?",
            (str(chat_id), kind),
        ).fetchone()
        if not row:
            return None
        payload: dict[str, object] = json.loads(row["payload"])
        return payload

    def clear(self, chat_id: str, kind: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "DELETE FROM pending_interactions WHERE chat_id = ? AND kind = ?",
                (str(chat_id), kind),
            )

    def purge_expired(self) -> int:
        with self.db.transaction() as conn:
            cur = conn.execute(
                "DELETE FROM pending_interactions WHERE expires_at < ?", (utcnow_iso(),)
            )
            return int(cur.rowcount)
