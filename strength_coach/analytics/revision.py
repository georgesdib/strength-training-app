"""Durable analytics source revisions.

Every source mutation that can change a derived family appends one row to
`analytics_revision` **in the same transaction as the mutation**. A committed mutation without a
revision row, or a revision row without the mutation, is therefore impossible.

`MAX(clean_set.set_id)` and `PRAGMA data_version` are deliberately not used as the revision
identity: they miss supersessions, tombstones, void/unvoid, configuration changes and methodology
bumps, and `data_version` is per connection and not durable. See design §4.4.1–4.4.2.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from strength_coach.store import db

SOURCE_KINDS = ("workout_end", "import", "correction", "void", "unvoid")
DEPENDENCY_KINDS = ("config", "methodology")
KINDS = SOURCE_KINDS + DEPENDENCY_KINDS


def current_revision(conn: sqlite3.Connection) -> int:
    """The highest committed revision, or 0 before any mutation."""
    return int(
        conn.execute("SELECT COALESCE(MAX(revision_id), 0) FROM analytics_revision").fetchone()[0]
    )


def _append(
    conn: sqlite3.Connection,
    kind: str,
    *,
    session_id: str | None,
    family: str | None,
    config_digest: str | None,
    detail: dict | None,
) -> int:
    if kind not in KINDS:
        raise ValueError(f"unknown analytics revision kind: {kind}")
    if kind in DEPENDENCY_KINDS and not config_digest:
        raise ValueError("dependency revisions require a config digest")
    if not conn.in_transaction:
        raise RuntimeError("analytics revisions must be recorded inside the mutation transaction")
    cursor = conn.execute(
        "INSERT INTO analytics_revision (kind, session_id, family, config_digest, "
        "detail_json) VALUES (?, ?, ?, ?, ?)",
        (
            kind,
            session_id,
            family,
            config_digest,
            json.dumps(detail or {}, separators=(",", ":"), sort_keys=True),
        ),
    )
    return int(cursor.lastrowid or 0)


def _mark_stale(conn: sqlite3.Connection, families: Iterable[str] | None) -> None:
    """A published family cannot stay ready after a revision it has not processed."""
    if families is None:
        conn.execute("UPDATE analytics_build SET status = 'stale' WHERE status = 'ready'")
        return
    names = tuple(dict.fromkeys(str(family) for family in families))
    if not names:
        return
    placeholders = ", ".join("?" for _ in names)
    conn.execute(
        f"UPDATE analytics_build SET status = 'stale' "
        f"WHERE status = 'ready' AND family IN ({placeholders})",
        names,
    )


def record_mutation(
    conn: sqlite3.Connection,
    kind: str,
    *,
    session_id: str | None = None,
    detail: dict | None = None,
) -> int:
    """Append a source-data revision inside the caller's transaction.

    The caller must already be in the transaction that writes the source rows. Any currently
    published family becomes `stale`; a running build is left to finish and is stopped at
    publication by the revision check.
    """
    if kind not in SOURCE_KINDS:
        raise ValueError(f"{kind!r} is not a source mutation kind")
    revision = _append(
        conn, kind, session_id=session_id, family=None, config_digest=None, detail=detail
    )
    _mark_stale(conn, None)
    return revision


def family_revision(conn: sqlite3.Connection, family: str) -> int:
    """Highest revision applicable to one family: global source changes and its own deps."""
    return int(
        conn.execute(
            "SELECT COALESCE(MAX(revision_id), 0) FROM analytics_revision "
            "WHERE family IS NULL OR family = ?",
            (family,),
        ).fetchone()[0]
    )


def record_dependency_change(
    conn: sqlite3.Connection,
    kind: str,
    *,
    config_digest: str,
    families: Iterable[str] | None = None,
    detail: dict | None = None,
) -> int:
    """Append a configuration or methodology revision and invalidate affected families.

    `families=None` invalidates every published family; a list limits it to those families.
    The function opens a transaction when the caller has none, so it is safe to call from a
    configuration hook.
    """
    if kind not in DEPENDENCY_KINDS:
        raise ValueError(f"{kind!r} is not a dependency change kind")

    names = None if families is None else tuple(dict.fromkeys(str(f) for f in families))
    with db.transaction(conn):
        if names is None:
            revisions = [
                _append(conn, kind, session_id=None, family=None,
                        config_digest=config_digest, detail=detail)
            ]
        else:
            revisions = [
                _append(conn, kind, session_id=None, family=name,
                        config_digest=config_digest, detail=detail)
                for name in names
            ]
        _mark_stale(conn, names)
    return revisions[-1] if revisions else 0
