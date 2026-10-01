"""Nightly database backups: naming, retention and freshness."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from recipe_mcp.db.backup import backup_database

BACKUP_NAME = re.compile(r"^recipes-(\d{4}-\d{2}-\d{2})\.db$")
STALE_AFTER = timedelta(hours=36)


@dataclass
class BackupResult:
    path: Path
    size_bytes: int
    removed: list[Path] = field(default_factory=list)


def list_backups(backup_dir: Path) -> list[Path]:
    """Backups made by this command, oldest first. Other files are left alone."""
    if not backup_dir.is_dir():
        return []
    return sorted(p for p in backup_dir.iterdir() if BACKUP_NAME.match(p.name))


def run_backup(database: Path, backup_dir: Path, keep: int, today: date) -> BackupResult:
    """Back up ``database`` as ``recipes-<today>.db`` and keep the newest ``keep`` copies.

    A second run on the same day replaces that day's copy.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_dir.chmod(0o700)
    dest = backup_dir / f"recipes-{today.isoformat()}.db"
    backup_database(database, dest)
    backups = list_backups(backup_dir)
    removed = backups[:-keep] if len(backups) > keep else []
    for old in removed:
        old.unlink()
    return BackupResult(path=dest, size_bytes=dest.stat().st_size, removed=removed)


def newest_backup_age(backup_dir: Path, now: datetime) -> timedelta | None:
    """How long ago the newest backup was written, or ``None`` when there is none."""
    backups = list_backups(backup_dir)
    if not backups:
        return None
    newest = max(p.stat().st_mtime for p in backups)
    return now - datetime.fromtimestamp(newest, tz=now.tzinfo)
