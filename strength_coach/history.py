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
    rep_rows = conn.execute(
        "SELECT r.clean_set_id, r.rep_index, r.velocity_mps FROM clean_rep r "
        "JOIN clean_set s ON s.set_id = r.clean_set_id "
        "WHERE s.session_id = ? AND NOT EXISTS (SELECT 1 FROM clean_set child "
        "WHERE child.supersedes_id = s.set_id) ORDER BY r.rep_index",
        (str(session_id),),
    ).fetchall()
    device_reps: dict[int, list[dict]] = {}
    for row in rep_rows:
        device_reps.setdefault(int(row["clean_set_id"]), []).append({
            "rep_index": int(row["rep_index"]),
            "velocity_mps": float(row["velocity_mps"]),
        })
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
            "device_reps": device_reps.get(int(item["set_id"]), []),
        }
        for item in current_sets(conn, session_id)
    ]
    vbt = current_vbt(conn, session_id)
    for item in data["sets"]:
        override = vbt.get(int(item["set_id"]), {"mean": None, "reps": {}})
        item["vbt_mean"] = override["mean"]
        item["vbt_reps"] = [
            {"rep_index": index, "velocity_mps": value}
            for index, value in sorted(override["reps"].items())
        ]
    data["vbt_override_count"] = sum(
        1 for value in vbt.values() if value["mean"] is not None or value["reps"]
    )
    data["feedback"] = queries.session_feedback(conn, session_id)
    data["forms"] = _current_forms(conn, session_id)
    return data


def _current_forms(conn, session_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT f.form_id, f.exercise_id, f.rating, f.note "
        "FROM session_form_rating f WHERE f.session_id = ? "
        "AND NOT EXISTS (SELECT 1 FROM session_form_rating child "
        "WHERE child.supersedes_id = f.form_id) ORDER BY f.form_id",
        (str(session_id),),
    ).fetchall()
    return [dict(row) for row in rows]


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
                 forms: list[dict] | None = None,
                 session_rpe: float | None = None,
                 duration_min: float | None = None,
                 notes: str | None = None,
                 reason: str | None = None) -> dict:
    session = detail(conn, session_id)
    if session.get("voided"):
        raise ValueError("unvoid the session before editing it")
    before = {"sets": session["sets"], "forms": session.get("forms") or [],
              "session_rpe": session.get("session_rpe"),
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
            vbt_mean = (None if item.get("vbt_mean") in (None, "")
                        else float(item["vbt_mean"]))
            vbt_reps = item.get("vbt_reps") or []
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
            "vbt_mean": vbt_mean,
            "vbt_reps": vbt_reps,
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
                item["_target_set_id"] = int(old["set_id"])
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
            item["_target_set_id"] = _insert_set(
                conn, session_id=session_id, occurred_on=session["occurred_on"],
                edit_id=edit_id, exercise_id=item["exercise_id"],
                load_kg=item["load_kg"], reps=item["reps"], rir=item["rir"],
                velocity_mps=item["velocity_mps"],
                supersedes_id=item.get("_supersedes"),
                voided=False, source_row=int(item["_source_row"]),
                old=existing.get(int(item["set_id"])) if item.get("set_id") else None,
            )
    vbt_entries = []
    for item in incoming:
        target = item.get("_target_set_id")
        if not target:
            continue
        reps = item.get("vbt_reps") or []
        if item.get("vbt_mean") not in (None, "") or reps:
            vbt_entries.append({
                "set_id": int(target),
                "mean": item.get("vbt_mean"),
                "reps": reps,
            })
    if vbt_entries:
        apply_vbt(conn, session_id, vbt_entries, reason="VBT override with correction")
    if forms is not None:
        if not isinstance(forms, list):
            raise ValueError("forms must be a list")
        known_exercises = {str(item["exercise_id"]) for item in session["sets"]}
        known_exercises.update(str(item["exercise_id"]) for item in session.get("forms") or [])
        existing_forms = {str(item["exercise_id"]): item for item in session.get("forms") or []}
        for index, item in enumerate(forms):
            if not isinstance(item, dict):
                raise ValueError(f"form {index + 1}: must be an object")
            exercise_id = str(item.get("exercise_id") or "").strip()
            if not exercise_id:
                raise ValueError(f"form {index + 1}: exercise is required")
            if exercise_id not in known_exercises:
                raise ValueError(f"form {index + 1}: exercise is not in this session")
            rating = item.get("rating")
            if rating in (None, ""):
                continue
            try:
                rating = int(rating)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"form {index + 1}: rating {rating!r} is not a number") from exc
            if not 1 <= rating <= 5:
                raise ValueError(f"form {index + 1}: rating must be between 1 and 5")
            note = item.get("note") or None
            old = existing_forms.get(exercise_id)
            if old and int(old["rating"]) == rating and (old.get("note") or None) == note:
                continue
            conn.execute(
                "INSERT INTO session_form_rating "
                "(session_id, exercise_id, rating, note, supersedes_id) VALUES (?, ?, ?, ?, ?)",
                (str(session_id), exercise_id, rating, note,
                 int(old["form_id"]) if old else None),
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
        "forms": forms,
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

def void_session(conn, session_id: str, *, reason: str | None = None,
                 unvoid: bool = False) -> dict:
    """Mark a session excluded from metrics/calibration; never delete its rows."""
    detail(conn, session_id)
    action = "unvoid" if unvoid else "void"
    conn.execute(
        "INSERT INTO session_void (session_id, action, reason) VALUES (?, ?, ?)",
        (session_id, action, reason),
    )
    conn.execute(
        "UPDATE session SET voided = ?, voided_at = ?, void_reason = ?, "
        "needs_review = 1, updated_at = ? WHERE session_id = ?",
        (0 if unvoid else 1, _now(), None if unvoid else reason, _now(), session_id),
    )
    return detail(conn, session_id)

def _latest_vbt(conn, set_id: int, rep_index: int | None) -> dict | None:
    row = conn.execute(
        "SELECT * FROM vbt_override o WHERE o.set_id = ? "
        "AND ((? IS NULL AND o.rep_index IS NULL) OR o.rep_index = ?) "
        "AND NOT EXISTS (SELECT 1 FROM vbt_override child "
        "WHERE child.supersedes_id = o.override_id) "
        "ORDER BY o.override_id DESC LIMIT 1",
        (int(set_id), rep_index, rep_index),
    ).fetchone()
    return dict(row) if row else None


def current_vbt(conn, session_id: str) -> dict:
    sets = current_sets(conn, session_id)
    out = {}
    for item in sets:
        set_id = int(item["set_id"])
        mean = _latest_vbt(conn, set_id, None)
        reps = conn.execute(
            "SELECT o.* FROM vbt_override o WHERE o.set_id = ? AND o.rep_index IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM vbt_override child "
            "WHERE child.supersedes_id = o.override_id) ORDER BY o.rep_index",
            (set_id,),
        ).fetchall()
        out[set_id] = {
            "mean": mean["velocity_mps"] if mean else None,
            "reps": {int(row["rep_index"]): float(row["velocity_mps"]) for row in reps},
        }
    return out

def apply_vbt(conn, session_id: str, entries: list[dict], *, reason: str | None = None) -> dict:
    """Append set-mean and/or per-rep VBT values; missing values are allowed."""
    detail(conn, session_id)
    current = {int(item["set_id"]): item for item in current_sets(conn, session_id)}
    edit_id = uuid.uuid4().hex
    for entry in entries:
        set_id = int(entry.get("set_id"))
        if set_id not in current:
            raise ValueError(f"set {set_id} is not current in this session")
        mean = entry.get("mean")
        if mean not in (None, ""):
            mean = float(mean)
            if mean <= 0:
                raise ValueError("VBT mean must be positive")
            previous = _latest_vbt(conn, set_id, None)
            conn.execute(
                "INSERT INTO vbt_override (session_id, set_id, rep_index, velocity_mps, "
                "source, supersedes_id) VALUES (?, ?, NULL, ?, 'manual', ?)",
                (session_id, set_id, mean,
                 previous["override_id"] if previous else None),
            )
        for rep in entry.get("reps") or []:
            rep_index = int(rep.get("rep_index"))
            velocity = float(rep.get("velocity_mps"))
            if rep_index < 1 or velocity <= 0:
                raise ValueError("rep VBT values must be positive")
            previous = _latest_vbt(conn, set_id, rep_index)
            conn.execute(
                "INSERT INTO vbt_override (session_id, set_id, rep_index, velocity_mps, "
                "source, supersedes_id) VALUES (?, ?, ?, ?, 'manual', ?)",
                (session_id, set_id, rep_index, velocity,
                 previous["override_id"] if previous else None),
            )
    conn.execute("UPDATE session SET needs_review = 1 WHERE session_id = ?", (session_id,))
    after = current_vbt(conn, session_id)
    conn.execute(
        "INSERT INTO session_edit (edit_id, session_id, reason, before_json, after_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (edit_id, session_id, reason or "VBT override", "{}",
         json.dumps({str(k): v for k, v in after.items()}, separators=(",", ":"))),
    )
    return {"session": detail(conn, session_id), "edit_id": edit_id}
