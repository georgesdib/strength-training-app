"""Read-only SQLite access for the MCP process."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote


def connect_readonly(path: str | Path) -> sqlite3.Connection:
    """Open the database in SQLite read-only mode.

    mode=ro is enforced by SQLite itself, not by application convention: a write raises
    "attempt to write a readonly database". PRAGMA query_only is a second, cheaper guard for
    the same intent. No migration is run and no journal is created.
    """
    target = Path(path).expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(f"database not found: {target}")
    connection = sqlite3.connect(f"file:{quote(target.as_posix())}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


@contextmanager
def readonly_connection(path: str | Path) -> Iterator[sqlite3.Connection]:
    connection = connect_readonly(path)
    try:
        yield connection
    finally:
        connection.close()
