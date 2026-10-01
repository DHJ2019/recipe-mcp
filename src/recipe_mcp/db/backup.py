"""Consistent copies of the SQLite database, safe while other processes are writing."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


class BackupError(RuntimeError):
    """The copy could not be made or failed its integrity check."""


def backup_database(source: Path, dest: Path) -> None:
    """Copy ``source`` to ``dest`` with SQLite's online backup API.

    The copy is written next to ``dest``, checked with ``PRAGMA integrity_check`` and only
    then renamed into place, so ``dest`` is never a partial or damaged file. It is created
    with mode 600 because it holds the whole household collection.
    """
    if not source.exists():
        raise BackupError(f"database not found: {source}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.unlink(missing_ok=True)
    tmp.touch(mode=0o600)
    try:
        src = sqlite3.connect(source)
        try:
            out = sqlite3.connect(tmp)
            try:
                src.backup(out)
                # A single self-contained file, so restoring is a plain copy.
                out.execute("PRAGMA journal_mode=DELETE")
                result = out.execute("PRAGMA integrity_check").fetchone()
            finally:
                out.close()
        finally:
            src.close()
        if not result or result[0] != "ok":
            raise BackupError(f"integrity check failed on the copy: {result}")
        tmp.chmod(0o600)
        os.replace(tmp, dest)
    except sqlite3.Error as exc:
        raise BackupError(f"{exc.__class__.__name__}: {exc}") from exc
    finally:
        tmp.unlink(missing_ok=True)
