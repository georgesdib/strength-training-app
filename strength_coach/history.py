"""Audited corrections for completed sessions.

The source tables are append-only. This module never updates clean_set: an edit inserts a
superseding row, a removal inserts a tombstone, and readers use the leaf row. Session aggregates
and the deterministic critique are rebuilt; human marks are flagged stale.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Any

from strength_coach import __version__
from strength_coach.critique import build_facts, score_session
from strength_coach.critique.rubric import persist as persist_critique
from strength_coach.domain import load as load_mod
from strength_coach.store import queries, repositories
from strength_coach.utils import exercises

CURRENT = (
    "s.voided = 0 AND NOT EXISTS "
    "(SELECT 1 FROM clean_set child WHERE child.supersedes_id = s.set_id)"
)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def current_sets(conn, session_id: str) -> list[dict]:
    rows = conn.execute(
        f"SELECT s.* FROM clean_set s WHERE s.session_id = ? AND {CURRENT} "
        "ORDER BY s.set_id",
        (str(session_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def list_sessions(conn, *, limit: int = 50, offset: int = 0,
                  start: str | None = None, end: str | None = None) -> dict:
    clauses = []
    params: list[Any] = []
    if start:
        clauses.append("s.occurred_on >= ?")
        params.append(start)
    if end:
        clauses.append("s.occurred_on <= ?")
        params.append(end)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM session s" + where, params
    ).fetchone()["n"]
    rows = conn.execute(
        "SELECT s.*, "
        "(SELECT COUNT(*) FROM rubric_mark m WHERE m.session_id = s.session_id) AS marks "
        "FROM session s" + where +
        " ORDER BY s.occurred_on DESC, s.session_id DESC LIMIT ? OFFSET ?",
        params + [int(limit), int(offset)],
    ).fetchall()
    return {
        "total": int(total),
        "limit": int(limit),
        "offset": int(offset),
        "sessions": [
            {**dict(row),
             "main_lifts": json.loads(row["main_lifts"] or "[]")}
            for row in rows
        ],
    }


def detail(conn, session_id: str) -> dict:
    row = conn.execute(
        "SELECT * FROM session WHERE session_id = ?", (str(session_id),)
    ).fetchone()
    if row is None:
        raise ValueError("session not found")
    data = dict(row)
    data["main_lifts"] = json.loads(data.get("main_lifts") or "[]")
    data["sets"] = [
        {
            "set_id": item["set_id"],
            "exercise_id": item["exercise_id"],
            "load_kg": item["load_kg"],
            "reps": item["reps"],
            "rir": item["rir"],
            "velocity_mps": item["velocity_mps"],
            "reps_unit": item["reps_unit"],
            "flags": json.loads(item["flags"] or "[]"),
        }
        for item in current_sets(conn, session_id)
    ]
    data["feedback"] = queries.session_feedback(conn, session_id)
    return data


def _refresh_session(conn, session_id: str) -> None:
    rows = current_sets(conn, session_id)
    entities = exercises.taxonomy().entities
    working = [row for row in rows if int(row["is_working_set"])]
    main_lifts = []
    tonnage = 0.0
    tonnage_present = False
    for row in working:
        exercise_id = str(row["exercise_id"])
        if exercise_id not in main_lifts and entities.get(exercise_id, {}).get("main_lift"):
            main_lifts.append(exercise_id)
        external = row.get("external_load_kg")
        reps = row.get("reps")
        if external is not None and reps is not None:
            tonnage += float(external) * int(reps)
            tonnage_present = True
    conn.execute(
        "UPDATE session SET set_count = ?, working_set_count = ?, exercise_count = ?, "
        "main_lifts = ?, tonnage_kg = ?, needs_review = 1, edited_at = ?, updated_at = ? "
        "WHERE session_id = ?",
        (
            len(rows), len(working), len({row["exercise_id"] for row in rows}),
            json.dumps(main_lifts), tonnage if tonnage_present else None,
            _now(), _now(), str(session_id),
        ),
    )


def _insert_set(conn, *, session_id: str, occurred_on: str, edit_id: str,
                exercise_id: str, load_kg: float | None, reps: int | None,
                rir: int | None, velocity_mps: float | None,
                supersedes_id: int | None, voided: bool, source_row: int,
                old: dict | None = None) -> int:
    exercise_id = str(exercise_id)
    if exercise_id not in exercises.taxonomy().entities:
        raise ValueError(f"unknown exercise: {exercise_id}")
    entity = exercises.taxonomy().entities.get(exercise_id, {})
    resolved = load_mod.resolve_load_basis(
        None if load_kg is None else float(load_kg),
        bodyweight_kg=None,
        is_bodyweight_type=bool(entity.get("bodyweight_type", False)),
        is_time_based=bool(entity.get("time_based", False)),
    )
    payload = {
        "edit_id": edit_id,
        "exercise_id": exercise_id,
        "load_kg": load_kg,
        "reps": reps,
        "rir": rir,
        "velocity_mps": velocity_mps,
        "voided": bool(voided),
    }
    raw = conn.execute(
        "INSERT INTO raw_row (table_name, source_row, file_sha256, payload) "
        "VALUES ('training', ?, ?, ?)",
        (int(source_row), "session-edit:" + edit_id, json.dumps(payload, separators=(",", ":"))),
    )
    rir_source = "missing" if rir is None else ("logged_warmup" if int(rir) == 6 else "logged")
    is_working = 0 if rir == 6 else 1
    if old is not None:
        reps_unit = str(old.get("reps_unit") or "reps")
        item_index = old.get("prescription_item_index")
        flags = json.loads(old.get("flags") or "[]")
    else:
        reps_unit = "seconds" if entity.get("time_based") else "reps"
        item_index = None
        flags = []
    flags = sorted(set(flags + ["session_edited"]))
    cursor = conn.execute(
        """
        INSERT INTO clean_set
            (raw_id, session_id, occurred_on, exercise_id, raw_exercise, load_kg,
             load_basis, external_load_kg, reps, reps_unit, rir, rir_source,
             velocity_mps, velocity_present, tonnage_kg, is_working_set, flags,
             supersedes_id, prescription_item_index, voided)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(raw.lastrowid), str(session_id), occurred_on, exercise_id, exercise_id,
            load_kg, resolved.basis, resolved.external_load_kg, reps, reps_unit,
            rir, rir_source, velocity_mps, 1 if velocity_mps is not None else 0,
            (float(resolved.external_load_kg) * int(reps))
            if resolved.external_load_kg is not None and reps is not None else None,
            is_working, json.dumps(flags), supersedes_id, item_index, 1 if voided else 0,
        ),
    )
    return int(cursor.lastrowid)


def edit_session(conn, session_id: str, *, sets: list[dict],
                 session_rpe: float | None = None,
                 duration_min: float | None = None,
                 notes: str | None = None,
                 reason: str | None = None) -> dict:
    session = detail(conn, session_id)
    before = {"sets": session["sets"], "session_rpe": session.get("session_rpe"),
              "duration_min": session.get("duration_min"), "notes": (session.get("feedback") or {}).get("note")}
    existing = {int(item["set_id"]): item for item in session["sets"]}
    incoming = []
    for index, item in enumerate(sets):
        try:
            exercise_id = str(item.get("exercise_id") or "").strip()
            reps = None if item.get("reps") in (None, "") else int(item["reps"])
            rir = None if item.get("rir") in (None, "") else int(item["rir"])
            load_kg = None if item.get("load_kg") in (None, "") else float(item["load_kg"])
            velocity = (None if item.get("velocity_mps") in (None, "")
                        else float(item["velocity_mps"]))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"set {index + 1}: {exc}") from exc
        if not exercise_id:
            raise ValueError(f"set {index + 1}: exercise is required")
        incoming.append({
            "set_id": item.get("set_id"),
            "exercise_id": exercise_id,
            "load_kg": load_kg,
            "reps": reps,
            "rir": rir,
            "velocity_mps": velocity,
        })
    edit_id = uuid.uuid4().hex
    kept = set()
    for index, item in enumerate(incoming):
        old = existing.get(int(item["set_id"])) if item.get("set_id") else None
        if old is not None:
            kept.add(int(old["set_id"]))
            same = all(item[key] == old[key] for key in
                       ("load_kg", "reps", "rir", "velocity_mps")) and                 item["exercise_id"] == old["exercise_id"]
            if same:
                continue
            item["_supersedes"] = int(old["set_id"])
        item["_source_row"] = index + 1
    # Removals are tombstones: they supersede the old row and are themselves excluded.
    for old_id, old in existing.items():
        if old_id not in kept:
            _insert_set(
                conn, session_id=session_id, occurred_on=session["occurred_on"],
                edit_id=edit_id, exercise_id=old["exercise_id"], load_kg=old["load_kg"],
                reps=old["reps"], rir=old["rir"], velocity_mps=old["velocity_mps"],
                supersedes_id=old_id, voided=True, source_row=len(incoming) + old_id,
                old=old,
            )
    for item in incoming:
        if item.get("_supersedes") or not item.get("set_id"):
            _insert_set(
                conn, session_id=session_id, occurred_on=session["occurred_on"],
                edit_id=edit_id, exercise_id=item["exercise_id"],
                load_kg=item["load_kg"], reps=item["reps"], rir=item["rir"],
                velocity_mps=item["velocity_mps"],
                supersedes_id=item.get("_supersedes"),
                voided=False, source_row=int(item["_source_row"]),
                old=existing.get(int(item["set_id"])) if item.get("set_id") else None,
            )
    _refresh_session(conn, session_id)
    if session_rpe is not None or duration_min is not None or notes:
        repositories.append_session_feedback(
            conn, session_id=session_id, srpe=session_rpe,
            duration_min=duration_min, note=notes,
        )
        conn.execute(
            "UPDATE session SET session_rpe = COALESCE(?, session_rpe), "
            "duration_min = COALESCE(?, duration_min), "
            "duration_basis = CASE WHEN ? IS NULL THEN duration_basis ELSE 'measured' END, "
            "session_rpe_recorded = ? WHERE session_id = ?",
            (session_rpe, duration_min, duration_min,
             1 if session_rpe is not None else 0, session_id),
        )
    after = {
        "sets": [
            {key: item.get(key) for key in
             ("exercise_id", "load_kg", "reps", "rir", "velocity_mps")}
            for item in incoming
        ],
        "session_rpe": session_rpe,
        "duration_min": duration_min,
        "notes": notes,
    }
    conn.execute(
        "INSERT INTO session_edit (edit_id, session_id, reason, before_json, after_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (edit_id, session_id, reason, json.dumps(before, separators=(",", ":")),
         json.dumps(after, separators=(",", ":"))),
    )
    warnings = []
    try:
        old_critique = conn.execute(
            "SELECT critique_id FROM critique WHERE session_id = ? "
            "ORDER BY created_at DESC LIMIT 1", (session_id,)
        ).fetchone()
        run = repositories.start_run(
            conn, input_hash="session-edit:" + edit_id, code_version=__version__,
            window_start=session["occurred_on"], window_end=session["occurred_on"],
        )
        critique = score_session(conn, session_id)
        new_id = persist_critique(
            conn, critique, run_id=run.run_id,
            supersedes_id=old_critique["critique_id"] if old_critique else None,
        )
        repositories.finish_run(conn, run.run_id)
        conn.execute(
            "UPDATE workout_session SET critique_id = ?, reviewed_at = NULL "
            "WHERE workout_id = ?", (new_id, session_id)
        )
    except Exception as exc:
        warnings.append(f"critique not rebuilt: {type(exc).__name__}: {exc}")
    return {"session": detail(conn, session_id), "edit_id": edit_id,
            "warnings": warnings}
