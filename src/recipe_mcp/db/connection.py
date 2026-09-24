"""SQLite connection with WAL mode and a thin transaction helper."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class Database:
    """Owns one SQLite connection. Repositories receive this rather than raw sqlite3.

    The MCP SDK runs synchronous tool functions on worker threads, so the
    connection is opened with ``check_same_thread=False`` and writes are
    serialised with a re-entrant lock. Reads are already safe under WAL.
    """

    def __init__(self, connection: sqlite3.Connection, path: Path | None) -> None:
        self.connection = connection
        self.path = path
        self._lock = threading.RLock()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self.connection
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise

    def close(self) -> None:
        self.connection.close()


def connect(path: Path | None) -> Database:
    """Open (and create if needed) the database at ``path``; ``None`` means in-memory."""
    if path is None:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return Database(conn, path)
