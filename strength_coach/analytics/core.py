"""Milestone B core materialisation: per-set e1RM and session/exercise aggregates.

The analytical owners keep their formulas. This module calls the same domain and monitoring
functions during materialisation, stores their output, and the owners read the stored rows only
when the `core` family is published and current. A failed or incomplete build falls back to the
on-demand path.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict
from dataclasses import asdict

from strength_coach.analytics.coordinator import is_ready, run_build
from strength_coach.analytics.families import REGISTRY, FamilySpec
from strength_coach.domain import e1rm as e1rm_mod
from strength_coach.features import strength_observations
from strength_coach.store import db, queries
from strength_coach.utils import exercises

LOGGER = logging.getLogger(__name__)

METHOD_VERSION = "core_v1"
DEPENDENCIES = {
    "e1rm": e1rm_mod.E1RM_METHOD_VERSION,
    "strength_observation": "raw_set_e1rm_v1",
    "materialiser": METHOD_VERSION,
}
CORE_SPEC = FamilySpec("core", METHOD_VERSION, DEPENDENCIES)
REGISTRY.setdefault(CORE_SPEC.family, CORE_SPEC)


def _excluded_sets(conn: sqlite3.Connection) -> dict[int, str]:
    return {
        int(row["set_id"]): str(row["kind"])
        for row in conn.execute(
            "SELECT set_id, kind FROM high_intensity_exposure WHERE set_id IS NOT NULL"
        )
    }


def _insert_set(
    conn: sqlite3.Connection,
    row: dict,
    *,
    estimate: float | None,
    usable: bool,
    strength_json: str | None,
) -> None:
    conn.execute(
        "INSERT INTO derived_set "
        "(set_id, method_version, session_id, exercise_id, occurred_on, e1rm_kg, "
        " e1rm_usable, strength_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            int(row["set_id"]),
            METHOD_VERSION,
            str(row["session_id"]),
            str(row["exercise_id"]),
            str(row["occurred_on"]),
            estimate,
            1 if usable else 0,
            strength_json,
        ),
    )


def materialise_session(conn: sqlite3.Connection, session_id: str) -> None:
    """Replace the derived rows for one session fragment from the authoritative clean sets."""
    sid = str(session_id)
    conn.execute("DELETE FROM derived_set WHERE session_id = ?", (sid,))
    conn.execute(
        "DELETE FROM derived_session_exercise WHERE session_id = ? AND method_version = ?",
        (sid, METHOD_VERSION),
    )
    session = conn.execute(
        "SELECT voided, occurred_on FROM session WHERE session_id = ?", (sid,)
    ).fetchone()
    if session is None or int(session["voided"]):
        return

    rows = queries.session_clean_sets(conn, sid)
    entities = exercises.taxonomy().entities
    excluded = _excluded_sets(conn)
    aggregates: dict[str, dict] = defaultdict(
        lambda: {"best": None, "working": 0, "tonnage": 0.0, "reps": 0, "loads": []}
    )

    for raw in rows:
        row = dict(raw)
        row["date"] = row["occurred_on"]
        # clean_set stores flags as a JSON list; the monitoring helper expects the store's
        # ";"-joined ingest form (queries.clean_sets converts it the same way).
        flags_raw = row.get("flags")
        if isinstance(flags_raw, str):
            try:
                parsed_flags = json.loads(flags_raw)
            except ValueError:
                parsed_flags = flags_raw
            if isinstance(parsed_flags, list):
                row["flags"] = ";".join(str(flag) for flag in parsed_flags)
        exercise_id = str(row["exercise_id"])
        props = dict(entities.get(exercise_id, {}))

        estimate = None
        usable = False
        load = row.get("load_kg")
        reps = row.get("reps")
        if (
            int(row.get("is_working_set") or 0)
            and load is not None and float(load) > 0
            and reps is not None and 1 <= int(reps) <= 20
        ):
            value = e1rm_mod.estimate_e1rm(
                float(load), int(reps), int(row["rir"]) if row.get("rir") is not None else None
            )
            if value is not None and value.is_usable:
                estimate = float(value.value_kg)
                usable = True

        observation = strength_observations.raw_set_e1rm(
            row, props, excluded_set_kinds=excluded
        )
        strength_json = (
            json.dumps(
                {
                    "estimate": asdict(observation),
                    "load_basis": row.get("load_basis"),
                    "raw_exercise": row.get("raw_exercise"),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            if isinstance(observation, strength_observations.RawEstimate)
            else None
        )
        _insert_set(
            conn, row, estimate=estimate, usable=usable, strength_json=strength_json
        )

        aggregate = aggregates[exercise_id]
        if int(row.get("is_working_set") or 0):
            aggregate["working"] += 1
            aggregate["reps"] += int(reps or 0)
            if load is not None:
                aggregate["loads"].append(float(load))
            tonnage = row.get("tonnage_kg")
            if tonnage is not None:
                aggregate["tonnage"] += float(tonnage)
        if estimate is not None:
            aggregate["best"] = max(aggregate["best"] or 0.0, estimate)

    for exercise_id, aggregate in aggregates.items():
        loads = aggregate["loads"]
        conn.execute(
            "INSERT OR REPLACE INTO derived_session_exercise "
            "(session_id, exercise_id, method_version, occurred_on, best_e1rm_kg, "
            " working_sets, tonnage_kg, total_reps, mean_load_kg) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sid,
                exercise_id,
                METHOD_VERSION,
                str(session["occurred_on"]),
                aggregate["best"],
                aggregate["working"],
                aggregate["tonnage"] if aggregate["working"] else None,
                aggregate["reps"],
                sum(loads) / len(loads) if loads else None,
            ),
        )


def backfill_batch(
    conn: sqlite3.Connection, cursor: str | None, batch_size: int
) -> tuple[str | None, bool]:
    rows = conn.execute(
        "SELECT session_id FROM session WHERE session_id > ? "
        "ORDER BY session_id LIMIT ?",
        (cursor or "", int(batch_size)),
    ).fetchall()
    for row in rows:
        materialise_session(conn, str(row["session_id"]))
    return (
        str(rows[-1]["session_id"]) if rows else cursor,
        len(rows) < int(batch_size),
    )


def apply_revision(conn: sqlite3.Connection, revision: sqlite3.Row) -> None:
    if revision["kind"] == "import":
        try:
            detail = json.loads(revision["detail_json"] or "{}")
        except ValueError:
            detail = {}
        for session_id in detail.get("session_ids") or ():
            materialise_session(conn, str(session_id))
        return
    if revision["session_id"]:
        materialise_session(conn, str(revision["session_id"]))


def build(conn: sqlite3.Connection, *, batch_size: int = 200) -> dict:
    """Explicit build/rebuild entry point (also used lazily by the owners)."""
    return run_build(
        conn,
        CORE_SPEC,
        apply_revision,
        backfill=backfill_batch,
        batch_size=batch_size,
    )


def ensure(conn: sqlite3.Connection) -> bool:
    """True only when the published family is verified current; reads never build."""
    return is_ready(conn, CORE_SPEC)


def refresh_sessions(
    conn: sqlite3.Connection, session_ids, *, was_ready: bool
) -> None:
    """Incrementally refresh already-materialised sessions inside the source transaction.

    `was_ready` is captured before the source revision is appended (the append marks the
    family stale). Large batches are left to an explicit build so an import does not block on
    materialisation. A failure marks the family stale; the source mutation still commits.
    """
    ids = [str(session_id) for session_id in dict.fromkeys(session_ids)]
    if not ids or not was_ready:
        return
    try:
        if len(ids) > 50:
            conn.execute(
                "UPDATE analytics_build SET status = 'stale' WHERE family = ?",
                (CORE_SPEC.family,),
            )
            return
        from strength_coach.analytics.revision import family_revision

        with db.transaction(conn):
            for session_id in ids:
                materialise_session(conn, session_id)
            current = family_revision(conn, CORE_SPEC.family)
            conn.execute(
                "UPDATE analytics_build SET status = 'ready', processed_revision = ?, "
                "source_revision = ?, last_error = NULL WHERE family = ?",
                (current, current, CORE_SPEC.family),
            )
    except Exception:
        LOGGER.warning("core incremental refresh failed; family marked stale", exc_info=True)
        with db.transaction(conn):
            conn.execute(
                "UPDATE analytics_build SET status = 'stale', last_error = ? WHERE family = ?",
                ("incremental materialisation failed", CORE_SPEC.family),
            )


def session_lift_e1rms(conn: sqlite3.Connection) -> tuple[dict, dict]:
    """Same shape as `progress._session_lift_e1rms`, from the materialised aggregate."""
    best: dict[str, dict[str, float]] = defaultdict(dict)
    dates: dict[str, str] = {}
    rows = conn.execute(
        "SELECT d.session_id, d.exercise_id, d.best_e1rm_kg, d.occurred_on "
        "FROM derived_session_exercise d JOIN session s ON s.session_id = d.session_id "
        "WHERE d.method_version = ? AND d.best_e1rm_kg IS NOT NULL AND s.voided = 0",
        (METHOD_VERSION,),
    ).fetchall()
    for row in rows:
        sid = str(row["session_id"])
        best[sid][str(row["exercise_id"])] = float(row["best_e1rm_kg"])
        dates[sid] = str(row["occurred_on"])
    return dict(best), dates


def strength_sets(
    conn: sqlite3.Connection, exercise_id: str, start: str, end: str
) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM derived_set WHERE method_version = ? AND exercise_id = ? "
        "AND occurred_on BETWEEN ? AND ? AND strength_json IS NOT NULL",
        (METHOD_VERSION, str(exercise_id), str(start), str(end)),
    ).fetchall()
    return [dict(row) for row in rows]
