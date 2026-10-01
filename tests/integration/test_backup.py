"""Database backups: a consistent copy while the database is open, retention, freshness."""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from recipe_mcp.db.backup import BackupError, backup_database
from recipe_mcp.services.backups import (
    STALE_AFTER,
    list_backups,
    newest_backup_age,
    run_backup,
)
from recipe_mcp.services.container import AppContext
from recipe_mcp.settings import Settings


def _recipe_count(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0])
    finally:
        conn.close()


def test_backup_of_an_open_database_holds_everything(
    seeded_ctx: AppContext, settings: Settings, tmp_path: Path
) -> None:
    assert settings.database_path is not None
    expected = seeded_ctx.recipes.count(seeded_ctx.household_id)
    assert expected > 0
    backups = tmp_path / "backups"
    # The context's connection stays open, as the running bot's would.
    result = run_backup(settings.database_path, backups, keep=14, today=date(2026, 10, 1))
    assert result.path == backups / "recipes-2026-10-01.db"
    assert _recipe_count(result.path) == expected
    assert result.path.stat().st_mode & 0o777 == 0o600
    assert backups.stat().st_mode & 0o777 == 0o700
    conn = sqlite3.connect(result.path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        conn.close()
    assert sorted(p.name for p in backups.iterdir()) == ["recipes-2026-10-01.db"]


def test_keeps_the_newest_copies_and_leaves_other_files_alone(
    seeded_ctx: AppContext, settings: Settings, tmp_path: Path
) -> None:
    assert settings.database_path is not None
    backups = tmp_path / "backups"
    backups.mkdir()
    (backups / "notes.txt").write_text("mine")
    removed: list[str] = []
    for day in range(1, 6):
        result = run_backup(settings.database_path, backups, keep=3, today=date(2026, 10, day))
        removed += [p.name for p in result.removed]
    assert [p.name for p in list_backups(backups)] == [
        "recipes-2026-10-03.db",
        "recipes-2026-10-04.db",
        "recipes-2026-10-05.db",
    ]
    assert removed == ["recipes-2026-10-01.db", "recipes-2026-10-02.db"]
    assert (backups / "notes.txt").read_text() == "mine"


def test_a_second_run_on_the_same_day_replaces_that_days_copy(
    seeded_ctx: AppContext, settings: Settings, tmp_path: Path
) -> None:
    assert settings.database_path is not None
    backups = tmp_path / "backups"
    run_backup(settings.database_path, backups, keep=14, today=date(2026, 10, 1))
    run_backup(settings.database_path, backups, keep=14, today=date(2026, 10, 1))
    assert [p.name for p in list_backups(backups)] == ["recipes-2026-10-01.db"]


def test_a_failed_backup_leaves_no_file_behind(tmp_path: Path) -> None:
    dest = tmp_path / "backups" / "recipes-2026-10-01.db"
    with pytest.raises(BackupError, match="not found"):
        backup_database(tmp_path / "missing.db", dest)
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"this is not a database" * 100)
    with pytest.raises(BackupError):
        backup_database(broken, dest)
    assert not dest.exists()
    assert list((tmp_path / "backups").iterdir()) == []


def test_newest_backup_age(seeded_ctx: AppContext, settings: Settings, tmp_path: Path) -> None:
    assert settings.database_path is not None
    backups = tmp_path / "backups"
    now = datetime.now(UTC)
    assert newest_backup_age(backups, now) is None
    result = run_backup(settings.database_path, backups, keep=14, today=date(2026, 10, 1))
    age = newest_backup_age(backups, now + timedelta(minutes=1))
    assert age is not None and age < STALE_AFTER
    two_days_ago = (now - timedelta(days=2)).timestamp()
    os.utime(result.path, (two_days_ago, two_days_ago))
    age = newest_backup_age(backups, now)
    assert age is not None and age > STALE_AFTER
