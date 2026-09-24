"""Forward-only SQL migration runner.

Migration files live in ``migrations/NNNN_name.sql`` and are applied in
lexical order exactly once. Files are never edited after release; add a new one.
"""

from __future__ import annotations

from pathlib import Path

from recipe_mcp.db.connection import Database
from recipe_mcp.domain.models import utcnow_iso

DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"


def _ensure_table(db: Database) -> None:
    db.connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )


def applied_migrations(db: Database) -> list[str]:
    _ensure_table(db)
    rows = db.connection.execute("SELECT name FROM schema_migrations ORDER BY name").fetchall()
    return [row["name"] for row in rows]


def pending_migrations(db: Database, directory: Path = DEFAULT_MIGRATIONS_DIR) -> list[Path]:
    done = set(applied_migrations(db))
    return [p for p in sorted(directory.glob("*.sql")) if p.name not in done]


def apply_migrations(db: Database, directory: Path = DEFAULT_MIGRATIONS_DIR) -> list[str]:
    """Apply every pending migration and return the names applied."""
    applied: list[str] = []
    for path in pending_migrations(db, directory):
        sql = path.read_text(encoding="utf-8")
        with db.transaction() as conn:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                (path.name, utcnow_iso()),
            )
        applied.append(path.name)
    return applied
