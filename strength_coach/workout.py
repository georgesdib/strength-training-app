"""Live workout session: the link between a prescription snapshot and actual sets.

The prescription is immutable. A workout copies its plan so a later regeneration cannot rewrite
what the athlete saw when they started. Actual sets are append-only; removal is an event, not a
delete, so the audit trail survives an in-session correction.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import math
import uuid
from typing import Any, Mapping

from strength_coach import __version__
from strength_coach.domain import load as load_mod
from strength_coach.critique import build_facts, score_session
from strength_coach.critique.rubric import persist as persist_critique
from strength_coach.prescribe import minimum_session as minimum_session_mod
from strength_coach.store import repositories
from strength_coach.utils import exercises

REQUIRED_READINESS = (
    "sleep", "energy", "mood", "soreness", "stress", "nutrition", "hydration",
)
OPTIONAL_READINESS = ("hrv_ms", "rhr_bpm", "bodyweight_kg", "fat_pct", "wearable_score")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _parse(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def validate_readiness(values: Mapping[str, Any], *,
                       allow_partial: bool = False) -> dict[str, float]:
    """Validate supplied readiness fields; the seven are required only by default.

    ``allow_partial`` is the explicit "start without a complete score" path. Missing fields
    stay absent, never invented, and the caller must have acknowledged that no readiness
    score will be applied.
    """
    clean: dict[str, float] = {}
    for key in REQUIRED_READINESS:
        value = values.get(key)
        if value in (None, ""):
            if allow_partial:
                continue
            raise ValueError(f"readiness.{key} is required")
        number = float(value)
        if not 1 <= number <= 5:
            raise ValueError(f"readiness.{key} must be between 1 and 5")
        clean[key] = number
    for key in OPTIONAL_READINESS:
        value = values.get(key)
        if value not in (None, ""):
            clean[key] = float(value)
    return clean


def _plan(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ValueError("plan must be an object")
    items = value.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("plan.items must be a non-empty list")
    return value


def start(
    conn,
    *,
    for_date: str,
    plan: Mapping[str, Any],
    readiness: Mapping[str, Any],
    session_type: str | None = None,
    prescription_id: str | None = None,
    note: str | None = None,
    allow_partial_readiness: bool = False,
) -> dict:
    active = active_workout(conn)
    if active is not None:
        raise ValueError("a workout is already in progress; end or abandon it first")
    plan_data = _plan(plan)
    readiness_data = validate_readiness(
        readiness, allow_partial=allow_partial_readiness
    )
    resolved_type = str(session_type or plan_data.get("session_type") or "")
    if resolved_type not in {"squat", "hinge", "bench_squat", "bench_hinge"}:
        raise ValueError("plan.session_type must be squat, hinge, bench_squat or bench_hinge")
    workout_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO workout_session
            (workout_id, prescription_id, for_date, session_type, status,
             plan_json, readiness_json, started_at, notes)
        VALUES (?, ?, ?, ?, 'in_progress', ?, ?, ?, ?)
        """,
        (
            workout_id, prescription_id, for_date, resolved_type,
            json.dumps(plan_data, separators=(",", ":")),
            json.dumps(readiness_data, separators=(",", ":")),
            _now(), note,
        ),
    )
    _event(conn, workout_id, "start", {"readiness": readiness_data})
    return get(conn, workout_id)


def active_workout(conn) -> dict | None:
    row = conn.execute(
        "SELECT workout_id FROM workout_session WHERE status = 'in_progress' "
        "ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return get(conn, row["workout_id"]) if row else None


def get(conn, workout_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM workout_session WHERE workout_id = ?", (workout_id,)
    ).fetchone()
    if row is None:
        return None
    data = dict(row)
    original = json.loads(data.pop("plan_json"))
    modified_raw = data.pop("plan_modified_json", None)
    modified = json.loads(modified_raw) if modified_raw else original
    data["original_plan"] = original
    data["plan"] = modified
    data["plan_modified"] = bool(modified_raw)
    data["readiness"] = json.loads(data.pop("readiness_json"))
    data["sets"] = _sets(conn, workout_id)
    data["forms"] = _form_ratings(conn, workout_id)
    rep_state = _current_reps(conn, workout_id)
    for row in data["sets"]:
        detail = rep_state.get(int(row["set_id"]))
        detail = detail if detail and detail.get("reps") else None
        row["reps_detail"] = detail
        row["rep_summary"] = _rep_summary(detail["reps"]) if detail else None
    data["elapsed_seconds"] = _elapsed(data)
    data["comparison"] = _comparison(data)
    data["original_comparison"] = _comparison({**data, "plan": original})
    data["minimum_session"] = _minimum_session_summary(data)
    return data


def _minimum_session_summary(workout: Mapping[str, Any]) -> dict[str, Any] | None:
    """Target, planning estimate and measured length side by side.

    The estimate is a planning aid, not a measurement (LIM-47), so the ended screen shows all
    three numbers rather than letting the estimate stand in for the clock. The estimate is
    recomputed from the plan as it stands, because in-session edits change the work.
    """
    notes = (workout.get("plan") or {}).get("notes") or {}
    if not notes:
        notes = (workout.get("original_plan") or {}).get("notes") or {}
    note = notes.get("minimum_session") or {}
    if not note.get("requested"):
        return None
    measured = workout.get("duration_min")
    return {
        "requested": True,
        "target_minutes": note.get("target_minutes"),
        "estimated_minutes": minimum_session_mod.estimate_minutes(
            (workout.get("plan") or {}).get("items") or ()
        ),
        "measured_minutes": None if measured is None else round(float(measured), 1),
        "duration_source": workout.get("duration_source"),
        "status": note.get("status"),
    }


def _form_ratings(conn, workout_id: str) -> list[dict]:
    """Latest optional post-lift rating per exercise, in first-rated order."""
    rows = conn.execute(
        "SELECT form_id, exercise_id, rating, note FROM workout_form_rating "
        "WHERE workout_id = ? ORDER BY form_id",
        (str(workout_id),),
    ).fetchall()
    out: dict[str, dict] = {}
    for row in rows:
        out[str(row["exercise_id"])] = {
            "form_id": int(row["form_id"]),
            "exercise_id": str(row["exercise_id"]),
            "rating": int(row["rating"]),
            "note": row["note"],
        }
    return list(out.values())


def set_form_rating(conn, workout_id: str, *, exercise_id: str, rating: int,
                    note: str | None = None) -> dict:
    """Record/amend one optional 1-5 post-lift form rating while the workout is open."""
    workout = get(conn, workout_id)
    if workout is None:
        raise ValueError("workout not found")
    if workout["status"] != "in_progress":
        raise ValueError("workout is not in progress; edit it from History")
    exercise_id = _validate_exercise(exercise_id)
    value = int(rating)
    if not 1 <= value <= 5:
        raise ValueError("form rating must be between 1 and 5")
    plan_ids = {str(item.get("exercise_id")) for item in (workout.get("plan") or {}).get("items") or []}
    set_ids = {str(item.get("exercise_id")) for item in _sets(conn, workout_id)}
    if exercise_id not in plan_ids and exercise_id not in set_ids:
        raise ValueError(f"{exercise_id} is not part of this workout")
    conn.execute(
        "INSERT INTO workout_form_rating (workout_id, exercise_id, rating, note) "
        "VALUES (?, ?, ?, ?)",
        (str(workout_id), exercise_id, value, note or None),
    )
    _event(conn, workout_id, "form_rating", {"exercise_id": exercise_id, "rating": value})
    return get(conn, workout_id)


def _sets(conn, workout_id: str) -> list[dict]:
    """Replay append-only set events so an import can correct a set without mutating it."""
    rows = conn.execute(
        "SELECT * FROM workout_set WHERE workout_id = ? ORDER BY set_id", (workout_id,)
    ).fetchall()
    state = {int(row["set_id"]): dict(row) for row in rows}
    removed: set[int] = set()
    events = conn.execute(
        "SELECT event_type, target_set_id, payload_json FROM workout_event "
        "WHERE workout_id = ? ORDER BY event_id",
        (workout_id,),
    ).fetchall()
    for event in events:
        target = event["target_set_id"]
        if target is None or int(target) not in state:
            continue
        if event["event_type"] == "remove_set":
            removed.add(int(target))
        elif event["event_type"] == "restore_set":
            removed.discard(int(target))
        elif event["event_type"] == "update_set":
            payload = json.loads(event["payload_json"] or "{}")
            state[int(target)].update({
                key: payload.get(key)
                for key in ("load_kg", "reps", "rir", "velocity", "source")
            })
    return [row for key, row in sorted(state.items()) if key not in removed]


def _current_reps(conn, workout_id: str) -> dict[int, dict]:
    """Return the latest per-rep snapshot for each set; empty means no detail."""
    rows = conn.execute(
        "SELECT * FROM workout_rep_event WHERE workout_id = ? ORDER BY event_id",
        (workout_id,),
    ).fetchall()
    state: dict[int, dict] = {}
    for row in rows:
        try:
            reps = json.loads(row["reps_json"] or "[]")
        except (TypeError, ValueError):
            reps = []
        state[int(row["set_id"])] = {
            "reps": reps,
            "source": row["source"],
            "batch_id": row["batch_id"],
        }
    return state


def _append_reps(conn, workout_id: str, set_id: int, reps: list[dict], *,
                 source: str, batch_id: str | None = None) -> dict | None:
    """Append a rep snapshot and return the prior one, for undo."""
    prior = _current_reps(conn, workout_id).get(int(set_id))
    clean = [
        {"rep_index": int(item["rep_index"]),
         "velocity_mps": float(item["velocity_mps"])}
        for item in sorted(reps, key=lambda item: int(item["rep_index"]))
    ]
    conn.execute(
        "INSERT INTO workout_rep_event (workout_id, set_id, reps_json, source, batch_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (workout_id, int(set_id), json.dumps(clean, separators=(",", ":")), source, batch_id),
    )
    return prior


def _rep_summary(reps: list[dict]) -> dict | None:
    if not reps:
        return None
    ordered = sorted(reps, key=lambda item: int(item["rep_index"]))
    first = float(ordered[0]["velocity_mps"])
    last = float(ordered[-1]["velocity_mps"])
    values = [float(item["velocity_mps"]) for item in ordered]
    return {
        "count": len(ordered),
        "first": round(first, 3),
        "last": round(last, 3),
        "mean": round(sum(values) / len(values), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "loss_abs": round(first - last, 3),
        "loss_pct": round((first - last) / first * 100, 2) if first else None,
    }


def _elapsed(data: Mapping[str, Any]) -> int:
    start = _parse(data.get("started_at"))
    if start is None:
        return 0
    end = _parse(data.get("ended_at")) or dt.datetime.now(dt.timezone.utc)
    return max(0, int((end - start).total_seconds()))


def _event(conn, workout_id: str, event_type: str, payload: dict,
           target_set_id: int | None = None) -> None:
    conn.execute(
        "INSERT INTO workout_event (workout_id, event_type, target_set_id, payload_json) "
        "VALUES (?, ?, ?, ?)",
        (workout_id, event_type, target_set_id,
         json.dumps(payload, separators=(",", ":"))),
    )


def add_set(
    conn,
    workout_id: str,
    *,
    exercise_id: str,
    load_kg: float | None = None,
    reps: int | None = None,
    rir: int | None = None,
    velocity: float | None = None,
    source: str = "manual",
    set_index: int | None = None,
) -> dict:
    workout = get(conn, workout_id)
    if workout is None:
        raise ValueError("workout not found")
    if workout["status"] != "in_progress":
        raise ValueError("workout is not in progress")
    if not exercise_id:
        raise ValueError("exercise_id is required")
    if source not in {"manual", "import", "device"}:
        raise ValueError("source must be manual, import or device")
    if set_index is None:
        row = conn.execute(
            "SELECT COALESCE(MAX(set_index), 0) AS n FROM workout_set WHERE workout_id = ? "
            "AND exercise_id = ?",
            (workout_id, exercise_id),
        ).fetchone()
        set_index = int(row["n"]) + 1
    set_index = int(set_index)
    if set_index < 1:
        raise ValueError("set_index must be positive")
    item_index = next(
        (index for index, item in enumerate(workout["plan"]["items"])
         if item.get("exercise_id") == exercise_id),
        None,
    )
    cursor = conn.execute(
        """
        INSERT INTO workout_set
            (workout_id, exercise_id, set_index, load_kg, reps, rir, velocity, source,
             prescription_item_index)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (workout_id, exercise_id, set_index, load_kg, reps, rir, velocity, source,
         item_index),
    )
    _event(conn, workout_id, "add_set", {"exercise_id": exercise_id,
                                          "set_index": set_index},
           target_set_id=int(cursor.lastrowid))
    return get(conn, workout_id)


def update_set(
    conn,
    workout_id: str,
    set_id: int,
    *,
    load_kg: float | None = None,
    reps: int | None = None,
    rir: int | None = None,
    velocity: float | None = None,
) -> dict:
    """Append a correction event for an actual set; the base row is never mutated."""
    workout = get(conn, workout_id)
    if workout is None:
        raise ValueError("workout not found")
    if workout["status"] != "in_progress":
        raise ValueError("workout is not in progress")
    if not any(int(item["set_id"]) == int(set_id) for item in _sets(conn, workout_id)):
        raise ValueError("set not found")
    _event(
        conn, workout_id, "update_set",
        {"load_kg": load_kg, "reps": reps, "rir": rir, "velocity": velocity},
        target_set_id=int(set_id),
    )
    return get(conn, workout_id)


def remove_set(conn, workout_id: str, set_id: int) -> dict:
    workout = get(conn, workout_id)
    if workout is None:
        raise ValueError("workout not found")
    if workout["status"] != "in_progress":
        raise ValueError("workout is not in progress")
    row = conn.execute(
        "SELECT set_id FROM workout_set WHERE workout_id = ? AND set_id = ?",
        (workout_id, set_id),
    ).fetchone()
    if row is None:
        raise ValueError("set not found")
    _event(conn, workout_id, "remove_set", {"set_id": int(set_id)},
           target_set_id=int(set_id))
    return get(conn, workout_id)


def score(conn, workout_id: str) -> str:
    """Run and persist the deterministic rubric for a materialised workout.

    The critique is append-only and linked to a synthetic run so the end-workout review has
    the same audit trail as a CLI prescription run. Re-running is a no-op.
    """
    workout = get(conn, workout_id)
    if workout is None:
        raise ValueError("workout not found")
    if workout.get("critique_id"):
        return str(workout["critique_id"])
    fact = build_facts(conn, workout_id)
    run = repositories.start_run(
        conn,
        input_hash="workout:" + workout_id,
        code_version=__version__,
        window_start=workout["for_date"],
        window_end=workout["for_date"],
    )
    critique = score_session(conn, workout_id, facts=fact)
    critique_id = persist_critique(conn, critique, run_id=run.run_id)
    repositories.finish_run(conn, run.run_id)
    conn.execute(
        "UPDATE workout_session SET critique_id = ? WHERE workout_id = ?",
        (critique_id, workout_id),
    )
    return critique_id


def mark_reviewed(conn, session_id: str) -> bool:
    """Mark the workout reviewed once human marks exist; idempotent."""
    row = conn.execute(
        "SELECT workout_id, reviewed_at FROM workout_session WHERE workout_id = ?",
        (session_id,),
    ).fetchone()
    if row is None or row["reviewed_at"]:
        return False
    conn.execute(
        "UPDATE workout_session SET reviewed_at = ? WHERE workout_id = ?",
        (_now(), session_id),
    )
    _event(conn, session_id, "reviewed", {})
    return True


def _validate_exercise(exercise_id: str) -> str:
    exercise_id = str(exercise_id or "").strip()
    if not exercise_id:
        raise ValueError("exercise_id is required")
    if exercise_id not in exercises.taxonomy().entities:
        raise ValueError(f"unknown exercise: {exercise_id}")
    return exercise_id


def _write_plan(conn, workout_id: str, plan: dict, event_type: str,
                payload: dict) -> dict:
    conn.execute(
        "UPDATE workout_session SET plan_modified_json = ? WHERE workout_id = ?",
        (json.dumps(plan, separators=(",", ":")), workout_id),
    )
    _event(conn, workout_id, event_type, payload)
    return get(conn, workout_id)


def _editable(workout: dict) -> list[dict]:
    if workout.get("status") != "in_progress":
        raise ValueError("workout is not in progress")
    return [dict(item) for item in (workout.get("plan") or {}).get("items") or []]


def swap_exercise(conn, workout_id: str, item_index: int, exercise_id: str) -> dict:
    workout = get(conn, workout_id)
    if workout is None:
        raise ValueError("workout not found")
    items = _editable(workout)
    if not 0 <= int(item_index) < len(items):
        raise ValueError("item_index out of range")
    new_id = _validate_exercise(exercise_id)
    old = items[int(item_index)].get("exercise_id")
    items[int(item_index)] = {
        **items[int(item_index)],
        "exercise_id": new_id,
        "substitution_for": old,
        # The old load belongs to the old lift; do not silently carry it across.
        "load_kg": None,
        "unknown_load_reason": "swapped during workout; load not re-solved",
    }
    plan = {**(workout.get("plan") or {}), "items": items}
    return _write_plan(conn, workout_id, plan, "swap_exercise",
                       {"item_index": int(item_index), "from": old, "to": new_id})


def add_exercise(
    conn,
    workout_id: str,
    *,
    exercise_id: str,
    sets: int = 3,
    reps_low: int = 8,
    reps_high: int = 12,
    load_kg: float | None = None,
    rir_target: int | None = 2,
) -> dict:
    workout = get(conn, workout_id)
    if workout is None:
        raise ValueError("workout not found")
    items = _editable(workout)
    new_id = _validate_exercise(exercise_id)
    if any(item.get("exercise_id") == new_id for item in items):
        raise ValueError(f"{new_id} is already in the plan")
    sets = max(1, min(20, int(sets)))
    low = max(1, min(50, int(reps_low)))
    high = max(low, min(50, int(reps_high)))
    item = {
        "exercise_id": new_id,
        "sets": sets,
        "reps_low": low,
        "reps_high": high,
        "load_kg": load_kg,
        "rir_target": rir_target,
        "essential": False,
        "added_during_workout": True,
    }
    plan = {**(workout.get("plan") or {}), "items": items + [item]}
    return _write_plan(conn, workout_id, plan, "add_exercise", item)


def remove_exercise(conn, workout_id: str, item_index: int) -> dict:
    workout = get(conn, workout_id)
    if workout is None:
        raise ValueError("workout not found")
    items = _editable(workout)
    index = int(item_index)
    if not 0 <= index < len(items):
        raise ValueError("item_index out of range")
    removed = items.pop(index)
    plan = {**(workout.get("plan") or {}), "items": items}
    return _write_plan(conn, workout_id, plan, "remove_exercise",
                       {"item_index": index, "removed": removed})


def change_sets(conn, workout_id: str, item_index: int, delta: int) -> dict:
    workout = get(conn, workout_id)
    if workout is None:
        raise ValueError("workout not found")
    items = _editable(workout)
    index = int(item_index)
    if not 0 <= index < len(items):
        raise ValueError("item_index out of range")
    before = int(items[index].get("sets") or 1)
    after = max(1, min(20, before + int(delta)))
    if after == before:
        return workout
    items[index]["sets"] = after
    plan = {**(workout.get("plan") or {}), "items": items}
    return _write_plan(conn, workout_id, plan, "change_sets",
                       {"item_index": index, "before": before, "after": after})


IMPORT_HEADER = ["exercise", "set", "rpe", "value", "weight", "reps"]
REP_HEADER = ["exercise name", "set number", "metric name", "rep number", "velocity"]
REP_METRIC = "mean concentric velocity"


def _unit_float(value: str, unit: str) -> float | None:
    text = str(value or "").strip().lower().replace(" ", "")
    if text in {"", "???", "?", "nan", "none"}:
        return None
    if text.endswith(unit):
        text = text[:-len(unit)]
    return float(text)


def _rpe_to_rir(value: str) -> tuple[int | None, bool]:
    """Convert per-set RPE to the app's integer RIR.

    rir = 10 - rpe; floor fractions; cap anything above 6 at 6 and mark it as a warm-up.
    The cap is deliberate: RIR 6 is the app's warm-up marker (DEC-RIR-01), not a hard set.
    """
    text = str(value or "").strip()
    if text in {"", "???", "?"}:
        return None, False
    rpe = float(text)
    if not 0 <= rpe <= 10:
        raise ValueError(f"RPE out of range: {value}")
    raw = 10.0 - rpe
    capped = raw > 6
    rir = min(6, int(math.floor(raw)))
    if rir < 0:
        raise ValueError(f"RPE out of range: {value}")
    return rir, capped or rir == 6


def parse_import(text: str) -> dict:
    """Parse the pasted/uploaded CSV into actual-workout rows.

    No date is present: this parser is for an active workout, not historical backfill.
    Unknown exercises are returned with exercise_id None so the caller can map or add them.
    """
    cleaned = text.lstrip("\ufeff").strip()
    if not cleaned:
        raise ValueError("CSV is empty")
    reader = csv.DictReader(io.StringIO(cleaned))
    fields = [str(name or "").strip().lower() for name in (reader.fieldnames or [])]
    missing = [name for name in IMPORT_HEADER if name not in fields]
    if missing:
        raise ValueError("missing CSV column(s): " + ", ".join(missing))
    # DictReader keys keep the original spelling; make access case-insensitive.
    key_map = {str(name).strip().lower(): name for name in (reader.fieldnames or [])}
    rows = []
    errors = []
    for line_no, raw in enumerate(reader, start=2):
        try:
            exercise_name = str(raw.get(key_map["exercise"]) or "").strip()
            exercise_id = exercises.canonical_id(exercise_name)
            set_index = int(str(raw.get(key_map["set"])).strip())
            reps = int(str(raw.get(key_map["reps"])).strip())
            rpe = raw.get(key_map["rpe"])
            rir, warmup = _rpe_to_rir(str(rpe))
            value = raw.get(key_map["value"])
            velocity = _unit_float(value, "m/s")
            weight = raw.get(key_map["weight"])
            load = _unit_float(weight, "kg")
            row = {
                "line": line_no,
                "exercise": exercise_name,
                "exercise_id": exercise_id,
                "set_index": set_index,
                "rpe": None if str(rpe).strip() in {"", "???", "?"} else float(rpe),
                "rir": rir,
                "warmup": bool(warmup),
                "velocity_mps": velocity,
                "load_kg": load,
                "reps": reps,
            }
            if exercise_id is None:
                errors.append({"line": line_no, "error": f"unknown exercise: {exercise_name}"})
            if set_index < 1 or reps < 0:
                errors.append({"line": line_no, "error": "set must be positive and reps non-negative"})
            rows.append(row)
        except (TypeError, ValueError) as exc:
            errors.append({"line": line_no, "error": str(exc)})
    seen = set()
    for row in rows:
        key = (row.get("exercise_id"), row.get("set_index"))
        if key in seen:
            errors.append({"line": row["line"], "error": f"duplicate exercise/set: {row['exercise']} set {row['set_index']}"})
        seen.add(key)
    return {"rows": rows, "errors": errors}


def parse_rep_import(text: str) -> dict:
    """Parse the optional per-rep CSV without requiring it.

    One blank Rep Number row is the set mean; numbered rows are rep samples. The table is
    joined to the main CSV by canonical exercise + set index; it never creates a set on its own.
    """
    cleaned = (text or "").lstrip("﻿").strip()
    if not cleaned:
        return {"sets": [], "errors": []}
    reader = csv.DictReader(io.StringIO(cleaned))
    fields = [str(name or "").strip().lower() for name in (reader.fieldnames or [])]
    missing = [name for name in REP_HEADER if name not in fields]
    if missing:
        raise ValueError("missing per-rep column(s): " + ", ".join(missing))
    key_map = {str(name).strip().lower(): name for name in (reader.fieldnames or [])}
    grouped: dict[tuple[str, int], dict] = {}
    errors: list[dict] = []
    for line_no, raw in enumerate(reader, start=2):
        try:
            exercise_name = str(raw.get(key_map["exercise name"]) or "").strip()
            exercise_id = exercises.canonical_id(exercise_name)
            set_index = int(str(raw.get(key_map["set number"])).strip())
            metric = str(raw.get(key_map["metric name"]) or "").strip().lower()
            rep_text = str(raw.get(key_map["rep number"]) or "").strip()
            velocity = _unit_float(raw.get(key_map["velocity"]), "m/s")
            if exercise_id is None:
                errors.append({"line": line_no, "error": f"unknown exercise: {exercise_name}"})
                continue
            if set_index < 1:
                errors.append({"line": line_no, "error": "set number must be positive"})
                continue
            if metric != REP_METRIC:
                errors.append({
                    "line": line_no,
                    "error": f"unsupported metric: {metric or '(blank)'}; expected {REP_METRIC}",
                })
                continue
            if velocity is None:
                errors.append({"line": line_no, "error": "velocity is required"})
                continue
            key = (str(exercise_id), set_index)
            group = grouped.setdefault(key, {
                "line": line_no,
                "exercise": exercise_name,
                "exercise_id": str(exercise_id),
                "set_index": set_index,
                "mean": None,
                "reps": {},
                "metrics": set(),
            })
            group["metrics"].add(metric)
            if rep_text in {"", "???", "?"}:
                if group["mean"] is not None:
                    errors.append({"line": line_no, "error": "duplicate set-mean row"})
                else:
                    group["mean"] = velocity
                continue
            rep_index = int(rep_text)
            if rep_index < 1:
                errors.append({"line": line_no, "error": "rep number must be positive"})
                continue
            if rep_index in group["reps"]:
                errors.append({
                    "line": line_no,
                    "error": f"duplicate rep {rep_index} for {exercise_name} set {set_index}",
                })
                continue
            group["reps"][rep_index] = velocity
        except (TypeError, ValueError) as exc:
            errors.append({"line": line_no, "error": str(exc)})
    sets = []
    for group in grouped.values():
        if len(group["metrics"]) > 1:
            errors.append({
                "line": group["line"],
                "error": f"mixed metrics for {group['exercise']} set {group['set_index']}",
            })
        sets.append({
            "line": group["line"],
            "exercise": group["exercise"],
            "exercise_id": group["exercise_id"],
            "set_index": group["set_index"],
            "mean": group["mean"],
            "reps": [
                {"rep_index": index, "velocity_mps": velocity}
                for index, velocity in sorted(group["reps"].items())
            ],
        })
    sets.sort(key=lambda item: (item["exercise_id"], item["set_index"]))
    return {"sets": sets, "errors": errors}


def import_csv(conn, workout_id: str, text: str, *, apply: bool = False,
               rep_text: str | None = None) -> dict:
    """Preview or apply the workout CSV. Apply replaces same exercise/set, never appends a duplicate."""
    workout = get(conn, workout_id)
    if workout is None:
        raise ValueError("workout not found")
    if workout["status"] != "in_progress" and apply:
        raise ValueError("workout is not in progress")
    parsed = parse_import(text)
    rep_parsed = parse_rep_import(rep_text or "")
    parsed["rep"] = rep_parsed
    parsed["errors"].extend(rep_parsed["errors"])
    active_sets = _sets(conn, workout_id)
    plan_ids = {
        str(item.get("exercise_id"))
        for item in (workout.get("plan") or {}).get("items") or []
    }
    main_by_key = {
        (str(row["exercise_id"]), int(row["set_index"])): row
        for row in parsed["rows"]
        if row.get("exercise_id")
    }
    for rep_set in rep_parsed["sets"]:
        match = main_by_key.get((rep_set["exercise_id"], int(rep_set["set_index"])))
        label = f"{rep_set['exercise']} set {rep_set['set_index']}"
        if match is None:
            parsed["errors"].append({
                "line": rep_set["line"],
                "error": f"per-rep set has no matching set row: {label}",
            })
            continue
        if len(rep_set["reps"]) > int(match["reps"]):
            parsed["errors"].append({
                "line": rep_set["line"],
                "error": f"per-rep count exceeds Reps for {label}",
            })
            continue
        too_high = [
            item["rep_index"] for item in rep_set["reps"]
            if int(item["rep_index"]) > int(match["reps"])
        ]
        if too_high:
            parsed["errors"].append({
                "line": rep_set["line"],
                "error": f"rep number {max(too_high)} exceeds Reps for {label}",
            })
            continue
        reps = list(rep_set["reps"])
        mean = rep_set["mean"]
        if reps and mean is None:
            mean = sum(item["velocity_mps"] for item in reps) / len(reps)
            mean_source = "derived"
        else:
            mean_source = "logged_mean"
        if match.get("velocity_mps") is None and mean is not None:
            match["velocity_mps"] = round(float(mean), 3)
            match["velocity_source"] = mean_source
        elif (match.get("velocity_mps") is not None and mean is not None
              and abs(float(match["velocity_mps"]) - float(mean)) > 0.01):
            match.setdefault("warnings", []).append(
                f"set mean {match['velocity_mps']:.3f} differs from per-rep mean {mean:.3f}"
            )
        if reps:
            match["rep_velocities"] = reps
            match["rep_mean"] = round(float(mean), 3) if mean is not None else None
            match["rep_mean_source"] = mean_source
    for row in parsed["rows"]:
        row["plan_new"] = bool(row["exercise_id"] and row["exercise_id"] not in plan_ids)
        existing = next(
            (item for item in active_sets
             if item.get("exercise_id") == row["exercise_id"]
             and int(item.get("set_index") or 0) == int(row["set_index"])),
            None,
        )
        if existing is not None:
            row["existing"] = {
                "load_kg": existing.get("load_kg"),
                "reps": existing.get("reps"),
                "rir": existing.get("rir"),
                "velocity": existing.get("velocity"),
            }
            row["conflicts"] = {
                key: [row[key], existing.get(key)]
                for key in ("load_kg", "reps", "rir")
                if row.get(key) != existing.get(key)
            }
    if not apply:
        return {"preview": parsed, "workout": workout}
    if parsed["errors"]:
        raise ValueError("import has errors; preview and fix them first")
    # The prescription can be extended by the file; the original snapshot stays frozen.
    for exercise_id in sorted({row["exercise_id"] for row in parsed["rows"]
                               if row.get("plan_new") and row["exercise_id"]}):
        rows = [row for row in parsed["rows"] if row["exercise_id"] == exercise_id]
        add_exercise(
            conn, workout_id,
            exercise_id=exercise_id,
            sets=max(int(row["set_index"]) for row in rows),
            reps_low=min(int(row["reps"]) for row in rows),
            reps_high=max(int(row["reps"]) for row in rows),
            load_kg=None,
            rir_target=None,
        )
    batch_id = uuid.uuid4().hex
    undo: list[dict] = []
    for row in parsed["rows"]:
        base = conn.execute(
            "SELECT set_id FROM workout_set WHERE workout_id = ? AND exercise_id = ? "
            "AND set_index = ?",
            (workout_id, row["exercise_id"], row["set_index"]),
        ).fetchone()
        payload = {
            "load_kg": row["load_kg"], "reps": row["reps"], "rir": row["rir"],
            "velocity": row["velocity_mps"], "source": "import",
        }
        target_set_id: int
        if base is None:
            after = add_set(
                conn, workout_id,
                exercise_id=row["exercise_id"],
                load_kg=row["load_kg"],
                reps=row["reps"],
                rir=row["rir"],
                velocity=row["velocity_mps"],
                source="import",
                set_index=row["set_index"],
            )
            created = next(
                item for item in after["sets"]
                if item.get("exercise_id") == row["exercise_id"]
                and int(item.get("set_index") or 0) == int(row["set_index"])
            )
            target_set_id = int(created["set_id"])
            undo.append({"action": "remove", "set_id": target_set_id})
        else:
            # The base row is immutable; restore if removed, then append the corrected values.
            current = next(
                (item for item in _sets(conn, workout_id)
                 if int(item["set_id"]) == int(base["set_id"])),
                None,
            )
            if current is None:
                _event(conn, workout_id, "restore_set", {},
                       target_set_id=int(base["set_id"]))
            before = {
                key: (current or {}).get(key)
                for key in ("load_kg", "reps", "rir", "velocity", "source")
            }
            target_set_id = int(base["set_id"])
            undo.append({"action": "update", "set_id": target_set_id,
                         "before": before})
            _event(conn, workout_id, "update_set", payload,
                   target_set_id=target_set_id)
        if row.get("rep_velocities"):
            prior = _append_reps(
                conn, workout_id, target_set_id, row["rep_velocities"],
                source="import", batch_id=batch_id,
            )
            undo.append({
                "action": "reps", "set_id": target_set_id,
                "before": (prior or {}).get("reps") or [],
            })
    _event(conn, workout_id, "import_applied",
           {"batch_id": batch_id, "undo": undo})
    return {"preview": parsed, "workout": get(conn, workout_id)}


def undo_import(conn, workout_id: str) -> dict:
    """Undo the latest import batch, without deleting its audit events."""
    row = conn.execute(
        "SELECT event_id, payload_json FROM workout_event WHERE workout_id = ? "
        "AND event_type = 'import_applied' ORDER BY event_id DESC LIMIT 1",
        (workout_id,),
    ).fetchone()
    if row is None:
        raise ValueError("no import to undo")
    payload = json.loads(row["payload_json"] or "{}")
    undone = conn.execute(
        "SELECT 1 FROM workout_event WHERE workout_id = ? AND event_type = 'import_undone' "
        "AND json_extract(payload_json, '$.batch_id') = ? LIMIT 1",
        (workout_id, payload.get("batch_id")),
    ).fetchone()
    if undone is not None:
        raise ValueError("latest import is already undone")
    for item in reversed(payload.get("undo", [])):
        if item.get("action") == "remove":
            _event(conn, workout_id, "remove_set", {"set_id": item["set_id"]},
                   target_set_id=int(item["set_id"]))
        elif item.get("action") == "update":
            _event(conn, workout_id, "update_set", item.get("before") or {},
                   target_set_id=int(item["set_id"]))
        elif item.get("action") == "reps":
            _append_reps(
                conn, workout_id, int(item["set_id"]), item.get("before") or [],
                source="import", batch_id=payload.get("batch_id"),
            )
    _event(conn, workout_id, "import_undone", {"batch_id": payload.get("batch_id")})
    return get(conn, workout_id)


def _comparison(workout: Mapping[str, Any]) -> dict:
    """Compare actual sets with the frozen plan; extra work is explicit."""
    items = list((workout.get("plan") or {}).get("items") or [])
    actual = list(workout.get("sets") or [])
    rows = []
    for index, item in enumerate(items):
        matching = [
            row for row in actual
            if row.get("exercise_id") == item.get("exercise_id")
        ]
        planned_sets = int(item.get("sets") or 0)
        count = len(matching)
        if count == 0:
            status = "missing"
        elif count < planned_sets:
            status = "under"
        elif count == planned_sets:
            status = "complete"
        else:
            status = "over"
        rows.append({
            "index": index,
            "exercise_id": item.get("exercise_id"),
            "status": status,
            "planned_sets": planned_sets,
            "actual_sets": count,
            "planned_reps": [item.get("reps_low"), item.get("reps_high")],
            "actual_reps": [row.get("reps") for row in matching],
            "planned_load_kg": item.get("load_kg"),
            "actual_load_kg": [row.get("load_kg") for row in matching],
            "planned_rir": item.get("rir_target"),
            "actual_rir": [row.get("rir") for row in matching],
        })
    planned_ids = {str(item.get("exercise_id")) for item in items}
    extra = [
        row for row in actual
        if row.get("exercise_id") not in planned_ids
    ]
    return {"items": rows, "extra": extra}


def _materialise(conn, workout: Mapping[str, Any], *, ended: str, duration: float,
                 duration_source: str, session_rpe: float | None,
                 session_rpe_recorded: bool, notes: str | None) -> None:
    """Write the completed workout into session/clean_set once.

    The workout is the draft; the normal session is the durable record that reports and
    review already understand. Refuses to duplicate if completion is retried.
    """
    workout_id = str(workout["workout_id"])
    existing = conn.execute(
        "SELECT session_id FROM session WHERE session_id = ?", (workout_id,)
    ).fetchone()
    if existing is not None:
        return
    sets = _sets(conn, workout_id)
    plan = workout.get("plan") or {}
    entities = exercises.taxonomy().entities
    # Main lifts are what was performed, not every item that appeared in the plan.
    main_lifts = []
    for row in sets:
        exercise_id = str(row["exercise_id"])
        if exercise_id not in main_lifts and entities.get(exercise_id, {}).get("main_lift"):
            main_lifts.append(exercise_id)
    comparison = workout.get("comparison") or {}
    incomplete = any(
        item.get("status") in {"missing", "under"}
        for item in (comparison.get("items") or [])
    )
    flags = ["incomplete"] if incomplete else []
    working = [row for row in sets if row.get("rir") != 6]
    bodyweight_kg = (workout.get("readiness") or {}).get("bodyweight_kg")
    tonnage = 0.0
    tonnage_present = False
    for row in working:
        load = row.get("load_kg")
        reps = row.get("reps")
        props = entities.get(str(row["exercise_id"]), {})
        resolved = load_mod.resolve_load_basis(
            None if load is None else float(load),
            bodyweight_kg=(None if bodyweight_kg in (None, "") else float(bodyweight_kg)),
            is_bodyweight_type=bool(props.get("bodyweight_type", False)),
            is_time_based=bool(props.get("time_based", False)),
        )
        if resolved.external_load_kg is not None and reps is not None:
            tonnage += float(resolved.external_load_kg) * int(reps)
            tonnage_present = True
    conn.execute(
        """
        INSERT INTO session
            (session_id, occurred_on, workout_label, set_count, working_set_count,
             exercise_count, main_lifts, session_type,
             tonnage_kg, duration_min, duration_basis, flags, prescription_id, source,
             workout_id, session_rpe, session_rpe_recorded)
        VALUES (?, ?, 'workout mode', ?, ?, ?, ?, ?,
                ?, ?, 'measured', ?, ?, 'workout', ?, ?, ?)
        """,
        (
            workout_id, workout["for_date"], len(sets), len(working),
            len({row["exercise_id"] for row in sets}), json.dumps(main_lifts),
            workout["session_type"], tonnage if tonnage_present else None, duration,
            json.dumps(flags), workout.get("prescription_id"), workout_id, session_rpe,
            1 if session_rpe_recorded else 0,
        ),
    )
    for form in _form_ratings(conn, workout_id):
        conn.execute(
            "INSERT INTO session_form_rating (session_id, exercise_id, rating, note) "
            "VALUES (?, ?, ?, ?)",
            (workout_id, str(form["exercise_id"]), int(form["rating"]), form.get("note")),
        )
    import hashlib
    file_sha = "workout:" + hashlib.sha256(workout_id.encode("utf-8")).hexdigest()
    rep_state = _current_reps(conn, workout_id)
    for row in sets:
        exercise_id = str(row["exercise_id"])
        props = entities.get(exercise_id, {})
        bodyweight = bool(props.get("bodyweight_type"))
        load = row.get("load_kg")
        resolved = load_mod.resolve_load_basis(
            None if load is None else float(load),
            bodyweight_kg=(None if bodyweight_kg in (None, "") else float(bodyweight_kg)),
            is_bodyweight_type=bodyweight,
            is_time_based=bool(props.get("time_based", False)),
        )
        load_basis = resolved.basis
        external = resolved.external_load_kg
        reps_unit = "seconds" if props.get("time_based") else "reps"
        is_working = 0 if row.get("rir") == 6 else 1
        row_flags = [] if load_basis != "unknown" else ["LOAD_BASIS_UNKNOWN"]
        payload = json.dumps(dict(row), separators=(",", ":"))
        cursor = conn.execute(
            "INSERT INTO raw_row (table_name, source_row, file_sha256, payload) "
            "VALUES ('training', ?, ?, ?)",
            (int(row["set_id"]), file_sha, payload),
        )
        raw_id = int(cursor.lastrowid)
        clean_cursor = conn.execute(
            """
            INSERT INTO clean_set
                (raw_id, session_id, occurred_on, exercise_id, raw_exercise, load_kg,
                 load_basis, external_load_kg, reps, reps_unit, rir, rir_source,
                 velocity_mps, velocity_present, tonnage_kg, is_working_set, flags,
                 prescription_item_index)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                raw_id, workout_id, workout["for_date"], exercise_id, exercise_id,
                load, load_basis, external, row.get("reps"), reps_unit, row.get("rir"),
                ("logged_warmup" if row.get("rir") == 6 else "logged")
                if row.get("rir") is not None else "missing", row.get("velocity"),
                1 if row.get("velocity") is not None else 0,
                (float(external) * int(row["reps"]))
                if external is not None and row.get("reps") is not None else None,
                is_working, json.dumps(row_flags), row.get("prescription_item_index"),
            ),
        )
        detail = rep_state.get(int(row["set_id"]))
        for rep in (detail or {}).get("reps") or []:
            conn.execute(
                "INSERT INTO clean_rep (clean_set_id, rep_index, velocity_mps, source) "
                "VALUES (?, ?, ?, ?)",
                (int(clean_cursor.lastrowid), int(rep["rep_index"]),
                 float(rep["velocity_mps"]), str((detail or {}).get("source") or "import")),
            )
    if session_rpe is not None or notes:
        repositories.append_session_feedback(
            conn, session_id=workout_id, srpe=session_rpe,
            duration_min=duration if duration > 0 else None, note=notes,
        )


def end(
    conn,
    workout_id: str,
    *,
    session_rpe: float | None,
    not_recorded: bool = False,
    duration_min: float | None = None,
    notes: str | None = None,
) -> dict:
    workout = get(conn, workout_id)
    if workout is None:
        raise ValueError("workout not found")
    if workout["status"] != "in_progress":
        raise ValueError("workout is not in progress")
    if duration_min is not None:
        duration = float(duration_min)
        if duration <= 0:
            raise ValueError("duration_min must be positive")
        source = "manual"
    else:
        duration = _elapsed(workout) / 60.0
        source = "measured"
    if session_rpe is not None:
        rpe = float(session_rpe)
        if not 1 <= rpe <= 10:
            raise ValueError("session_rpe must be between 1 and 10")
    elif not_recorded:
        rpe = None
    else:
        raise ValueError("session_rpe is required, or mark it not recorded")
    ended = _now()
    _materialise(
        conn, workout, ended=ended, duration=duration, duration_source=source,
        session_rpe=rpe, session_rpe_recorded=not not_recorded, notes=notes,
    )
    critique_id = score(conn, workout_id)
    conn.execute(
        """
        UPDATE workout_session
        SET status = 'completed', ended_at = ?, duration_measured_s = ?,
            duration_min = ?, duration_source = ?, session_rpe = ?,
            session_rpe_recorded = ?, notes = COALESCE(?, notes), critique_id = ?
        WHERE workout_id = ?
        """,
        (ended, _elapsed(workout), duration, source, rpe, 0 if not_recorded else 1,
         notes, critique_id, workout_id),
    )
    _event(conn, workout_id, "end", {"duration_min": duration,
                                      "session_rpe": rpe,
                                      "not_recorded": bool(not_recorded)})
    return get(conn, workout_id)


def abandon(conn, workout_id: str) -> dict:
    workout = get(conn, workout_id)
    if workout is None:
        raise ValueError("workout not found")
    if workout["status"] != "in_progress":
        raise ValueError("workout is not in progress")
    conn.execute(
        "UPDATE workout_session SET status = 'abandoned', ended_at = ?, "
        "duration_measured_s = ? WHERE workout_id = ?",
        (_now(), _elapsed(workout), workout_id),
    )
    _event(conn, workout_id, "abandon", {})
    return get(conn, workout_id)
