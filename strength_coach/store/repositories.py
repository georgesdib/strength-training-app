"""Append-only writers for the store.

Every function takes an open connection and does one thing. Nothing here computes a domain
value: cleaning happens in `ingest.clean`, session reconstruction in `ingest.sessions`, and
this module only persists the results with their traceability intact.

Idempotency is a property of the *identity key*, not of the content:

* a `raw_row` is identified by (table_name, source_row, file_sha256) -- which file, which line;
* a `clean_set` is identified by its `raw_id` -- one canonical set per source line.

That is why importing the same export twice writes nothing the second time, while two
genuinely identical sets (different `source_row`) both survive: DQ-DUP-01 forbids
content-based deduplication, and content is deliberately absent from every key here.
"""

from __future__ import annotations

import datetime
import json
import math
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from strength_coach.ingest.sessions import Session
from strength_coach.utils import numeric, readiness as readiness_utils

# --- small helpers ---------------------------------------------------------


def _opt(value: Any) -> Any:
    """pandas NaN/NA -> SQL NULL, everything else unchanged."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return value
    return value


def _iso_date(value: Any) -> str:
    return pd.Timestamp(value).date().isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def flag_list(raw: Any) -> list[str]:
    """`";".join` flags from the cleaner -> a JSON list for the column."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    return [part for part in str(raw).split(";") if part]


def _changes(conn: sqlite3.Connection, sql: str, params: Iterable[Sequence[Any]]) -> int:
    before = conn.total_changes
    conn.executemany(sql, params)
    return conn.total_changes - before


# --- raw intake ------------------------------------------------------------


def store_raw_rows(
    conn: sqlite3.Connection,
    frame: pd.DataFrame,
    *,
    table_name: str,
    file_sha256: str,
) -> tuple[dict[int, int], int]:
    """Persist source lines, reusing an existing raw row when the content is identical.

    Identity is normally (file, source line). A new cumulative export has a different file
    hash, so that identity alone would duplicate every historical row. Instead, before
    inserting, each incoming row is matched against the stored payloads by canonical content:

    * an identical row already stored is mapped to its existing raw_id, so clean_set's
      UNIQUE(raw_id) skips it;
    * duplicates *inside the new file* still get separate raw rows, because each incoming line
      is matched at most once against the existing pool (DQ-DUP-01 preserved within a file);
    * a genuinely new row is inserted with the new file hash.

    This is overlap detection across exports, not content deduplication within one export.
    """
    if table_name not in {"training", "readiness"}:
        raise ValueError(f"unknown table_name: {table_name}")

    def payload_of(record: Mapping[str, Any]) -> str:
        return _json({str(k): (None if _opt(v) is None else str(v)) for k, v in record.items()})

    def fingerprint(payload: str) -> str:
        return json.dumps(json.loads(payload), sort_keys=True, separators=(",", ":"))

    same_file = {
        int(row["source_row"]): int(row["raw_id"])
        for row in conn.execute(
            "SELECT source_row, raw_id FROM raw_row WHERE table_name = ? AND file_sha256 = ?",
            (table_name, file_sha256),
        )
    }
    pool: dict[str, list[int]] = {}
    for row in conn.execute(
        "SELECT raw_id, payload FROM raw_row WHERE table_name = ? ORDER BY raw_id",
        (table_name,),
    ):
        pool.setdefault(fingerprint(str(row["payload"])), []).append(int(row["raw_id"]))

    mapping: dict[int, int] = {}
    inserted = 0
    for index, record in enumerate(frame.to_dict(orient="records"), start=1):
        payload = payload_of(record)
        if index in same_file:
            mapping[index] = same_file[index]
            continue
        matches = pool.get(fingerprint(payload))
        if matches:
            mapping[index] = matches.pop(0)
            continue
        cursor = conn.execute(
            "INSERT INTO raw_row (table_name, source_row, file_sha256, payload) "
            "VALUES (?, ?, ?, ?)",
            (table_name, index, file_sha256, payload),
        )
        mapping[index] = int(cursor.lastrowid)
        inserted += 1
    return mapping, inserted


def store_quarantine(
    conn: sqlite3.Connection,
    quarantined: pd.DataFrame,
    *,
    raw_ids: Mapping[int, int],
) -> int:
    """Record why a line could not be placed. Nothing is ever dropped silently."""
    if quarantined.empty:
        return 0
    rows = [
        (raw_ids[int(record["source_row"])], str(record["quarantine_reason"]))
        for record in quarantined.to_dict(orient="records")
        if int(record["source_row"]) in raw_ids
    ]
    known = {
        int(row["raw_id"]) for row in conn.execute("SELECT raw_id FROM quarantine")
    }
    fresh = [row for row in rows if row[0] not in known]
    return _changes(conn, "INSERT INTO quarantine (raw_id, reason) VALUES (?, ?)", fresh)


# --- sessions + sets -------------------------------------------------------


def upsert_sessions(conn: sqlite3.Connection, sessions: Sequence[Session]) -> int:
    """Write reconstructed sessions.

    `session` is derived state, not an artifact: adding yesterday's sets changes the
    previous session's counts, so this row is recomputed rather than superseded.
    """
    rows = [
        (
            session.session_id,
            session.date,
            session.workout_label,
            session.set_count,
            session.working_set_count,
            session.exercise_count,
            _json(list(session.main_lifts)),
            session.session_type,
            _opt(session.tonnage_kg),
            _json(list(session.flags)),
        )
        for session in sessions
    ]
    return _changes(
        conn,
        """
        INSERT INTO session (
            session_id, occurred_on, workout_label, set_count, working_set_count,
            exercise_count, main_lifts, session_type,
            tonnage_kg, flags, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        ON CONFLICT(session_id) DO UPDATE SET
            occurred_on       = excluded.occurred_on,
            workout_label     = excluded.workout_label,
            set_count         = excluded.set_count,
            working_set_count = excluded.working_set_count,
            exercise_count    = excluded.exercise_count,
            main_lifts        = excluded.main_lifts,
            session_type      = excluded.session_type,
            tonnage_kg        = excluded.tonnage_kg,
            flags             = excluded.flags,
            updated_at        = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        rows,
    )


def store_clean_sets(
    conn: sqlite3.Connection,
    sets: pd.DataFrame,
    *,
    raw_ids: Mapping[int, int],
) -> tuple[int, int]:
    """Persist canonical sets; return (inserted, already_present).

    `INSERT OR IGNORE` on `UNIQUE(raw_id)` makes a re-import idempotent. It cannot merge two
    real sets, because each source line has its own `raw_id`.
    """
    if sets.empty:
        return 0, 0

    rows: list[tuple[Any, ...]] = []
    skipped = 0
    for record in sets.to_dict(orient="records"):
        source_row = int(record["source_row"])
        raw_id = raw_ids.get(source_row)
        if raw_id is None:
            # Cannot happen for a clean set that came from this training frame; refusing to
            # invent a raw_id keeps the trace honest.
            raise KeyError(f"no raw_row for source_row {source_row}")
        occurred_on = _iso_date(record["date"])
        velocity = _opt(record.get("velocity_mps"))
        # DQ-SENT-01: the cleaner already decided presence; fall back to the shared rule only
        # when an older frame arrives without the column.
        present_raw = _opt(record.get("velocity_present"))
        present = numeric.measurement_present(velocity) if present_raw is None else bool(present_raw)
        rows.append(
            (
                raw_id,
                occurred_on,  # session_id is date-based (DQ-SESSION-01)
                occurred_on,
                str(record["exercise_id"]),
                _opt(record.get("raw_exercise")),
                _opt(record.get("load_kg")),
                str(record.get("load_basis") or "unknown"),
                _opt(record.get("external_load_kg")),
                _opt(record.get("reps")),
                str(record.get("reps_unit") or "reps"),
                _opt(record.get("rir")),
                _opt(record.get("rir_source")),
                velocity,
                1 if present else 0,
                _opt(record.get("power_w")),
                _opt(record.get("rom_mm")),
                _opt(record.get("tut_s")),
                _opt(record.get("form_score")),
                _opt(record.get("tonnage_kg")),
                1 if bool(record.get("is_working_set")) else 0,
                _json(flag_list(record.get("flags"))),
            )
        )

    existing = {
        int(row["raw_id"]) for row in conn.execute("SELECT raw_id FROM clean_set")
    }
    fresh = [row for row in rows if row[0] not in existing]
    # Plain INSERT: the duplicate check is explicit, so a constraint violation surfaces
    # instead of being silently ignored (which is how an invalid rir_source once vanished).
    inserted = _changes(
        conn,
        """
        INSERT INTO clean_set (
            raw_id, session_id, occurred_on, exercise_id, raw_exercise, load_kg, load_basis,
            external_load_kg, reps, reps_unit, rir, rir_source, velocity_mps,
            velocity_present, power_w, rom_mm, tut_s, form_score, tonnage_kg,
            is_working_set, flags
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        fresh,
    )
    return inserted, len(rows) - inserted


def upsert_readiness_days(conn: sqlite3.Connection, days: pd.DataFrame) -> int:
    """Write merged readiness rows.

    `readiness_day` is derived state like `session`: adding a later export changes the merge
    for a date, so the row is recomputed. The raw rows it came from stay immutable in
    `raw_row`, and `merge_note` records why one candidate won.
    """
    if days.empty:
        return 0

    columns = [
        "sleep", "energy", "mood", "soreness", "stress", "nutrition", "hydration",
        "squat_readiness", "bench_readiness", "deadlift_readiness", "hrv_ms", "rhr_bpm",
        "bodyweight_kg", "fat_pct", "grip_strength_kg", "wearable_score",
    ]
    rows = []
    for record in days.to_dict(orient="records"):
        rows.append(
            (
                str(record["on_date"]),
                *[_opt(record.get(name)) for name in columns],
                _opt(record.get("composite")),
                _opt(record.get("composite_basis")),
                _opt(record.get("merge_note")),
            )
        )
    assignments = ", ".join(f"{name} = excluded.{name}" for name in columns)
    return _changes(
        conn,
        f"""
        INSERT INTO readiness_day (
            on_date, {", ".join(columns)}, composite, composite_basis, merge_note
        ) VALUES (?, {", ".join("?" * len(columns))}, ?, ?, ?)
        ON CONFLICT(on_date) DO UPDATE SET
            {assignments},
            composite = excluded.composite,
            composite_basis = excluded.composite_basis,
            merge_note = excluded.merge_note
        """,
        rows,
    )


# --- run trace -------------------------------------------------------------


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    started_at: str


def start_run(
    conn: sqlite3.Connection,
    *,
    input_hash: str,
    code_version: str,
    config_hash: str | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    llm_model: str | None = None,
    llm_tokens: int | None = None,
    run_id: str | None = None,
) -> RunRecord:
    """Open a trace. One row per attempt, so two runs are distinguishable after the fact."""
    identifier = run_id or uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO run (run_id, started_at, input_hash, code_version, config_hash,
                         window_start, window_end, llm_model, llm_tokens, status)
        VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), ?, ?, ?, ?, ?, ?, ?, 'ok')
        """,
        (
            identifier,
            input_hash,
            code_version,
            config_hash,
            window_start,
            window_end,
            llm_model,
            llm_tokens,
        ),
    )
    started_at = conn.execute(
        "SELECT started_at FROM run WHERE run_id = ?", (identifier,)
    ).fetchone()["started_at"]
    return RunRecord(run_id=identifier, started_at=started_at)


def finish_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    status: str = "ok",
    llm_tokens: int | None = None,
) -> None:
    if status not in {"ok", "llm_failed", "llm_downgraded", "error"}:
        raise ValueError(f"unknown run status: {status}")
    conn.execute(
        """
        UPDATE run
           SET finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
               status = ?,
               llm_tokens = COALESCE(?, llm_tokens)
         WHERE run_id = ?
        """,
        (status, llm_tokens, run_id),
    )


def log_event(
    conn: sqlite3.Connection,
    run_id: str,
    kind: str,
    payload: Mapping[str, Any] | str | None = None,
) -> int:
    """Append one ordered event; returns its `seq`."""
    allowed = {"input", "feature", "tool_call", "llm_output", "policy_verdict", "artifact"}
    if kind not in allowed:
        raise ValueError(f"unknown run_event kind: {kind}")
    body = payload if isinstance(payload, str) else _json(dict(payload or {}))
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM run_event WHERE run_id = ?", (run_id,)
    ).fetchone()
    seq = int(row["next"])
    conn.execute(
        "INSERT INTO run_event (run_id, seq, kind, payload) VALUES (?, ?, ?, ?)",
        (run_id, seq, kind, body),
    )
    return seq


def run_events(conn: sqlite3.Connection, run_id: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT seq, kind, payload FROM run_event WHERE run_id = ? ORDER BY seq", (run_id,)
        )
    )


# --- other append-only artifacts ------------------------------------------


def append_calibration(
    conn: sqlite3.Connection,
    *,
    exercise_id: str | None,
    vbt_family: str | None,
    scope: str,
    rep_count: int,
    rir_band: tuple[int, int],
    velocity_median: float | None,
    velocity_low: float | None,
    velocity_high: float | None,
    n_sets: int,
    n_sessions: int,
    method_version: str,
    params: Mapping[str, Any],
    calibration_id: str | None = None,
    velocity_mad: float | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    source: str = "computed",
    override_reason: str | None = None,
    valid_from: str | None = None,
    valid_until: str | None = None,
    supersedes_id: str | None = None,
) -> str:
    """Record a calibration target so a later prescription can cite it by id."""
    identifier = calibration_id or uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO vbt_calibration (
            calibration_id, exercise_id, vbt_family, scope, rep_count, rir_low, rir_high,
            velocity_median, velocity_mad, velocity_low, velocity_high, n_sets, n_sessions,
            window_start, window_end, method_version, params_json, source, override_reason,
            valid_from, valid_until, supersedes_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            identifier,
            exercise_id,
            vbt_family,
            scope,
            rep_count,
            rir_band[0],
            rir_band[1],
            velocity_median,
            velocity_mad,
            velocity_low,
            velocity_high,
            n_sets,
            n_sessions,
            window_start,
            window_end,
            method_version,
            _json(dict(params)),
            source,
            override_reason,
            valid_from,
            valid_until,
            supersedes_id,
        ),
    )
    return identifier


def append_rule(
    conn: sqlite3.Connection,
    *,
    rule_id: str,
    document_id: str,
    document_version: str,
    severity: str,
    scope: Mapping[str, Any] | None,
    check_fn: str,
    citations: Sequence[str],
    depends_on_data_decisions: Sequence[str],
    body: Mapping[str, Any],
) -> None:
    """Store one rule row; part of an immutable document version, never edited."""
    conn.execute(
        """
        INSERT INTO rule (rule_id, document_id, document_version, severity, scope, check_fn,
                          citations, depends_on_data_decisions, body_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rule_id,
            document_id,
            document_version,
            severity,
            _json(dict(scope or {})),
            check_fn,
            _json(list(citations)),
            _json(list(depends_on_data_decisions)),
            _json(dict(body)),
        ),
    )


def append_e1rm_override(
    conn: sqlite3.Connection,
    *,
    exercise_id: str,
    e1rm_kg: float,
    effective_from: str,
    expires_on: str | None = None,
    reason: str | None = None,
    source: str = "user",
) -> int:
    """Record a manual e1RM. A correction appends; the latest applicable row wins.

    Returns the new override id so the caller can tell the athlete what the prescription will
    cite (`e1rm_override:<id>`).
    """
    cursor = conn.execute(
        """
        INSERT INTO e1rm_override (exercise_id, e1rm_kg, effective_from, expires_on, reason,
                                   source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (exercise_id, float(e1rm_kg), effective_from, expires_on, reason, source),
    )
    return int(cursor.lastrowid)


def append_athlete_profile(
    conn: sqlite3.Connection,
    *,
    effective_from: str,
    primary_goal: str,
    goal_rank: Sequence[str],
    focus_lifts: Sequence[str],
    competition_date: str | None = None,
    sessions_per_week_target: int | None = None,
    max_session_minutes: int | None = None,
    block_start_date: str | None = None,
    volume_budget_enabled: bool = False,
    main_lift_policy: str = "preserve",
) -> None:
    """Append a profile version. A reset or a goal change is a new row (DEC-RAMP-01)."""
    if main_lift_policy not in ("preserve", "reduce", "drop"):
        raise ValueError("main_lift_policy must be preserve, reduce or drop")
    conn.execute(
        """
        INSERT INTO athlete_profile (effective_from, primary_goal, goal_rank, focus_lifts,
                                     competition_date, sessions_per_week_target,
                                     max_session_minutes, block_start_date,
                                     volume_budget_enabled, main_lift_policy)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            effective_from,
            primary_goal,
            _json(list(goal_rank)),
            _json(list(focus_lifts)),
            competition_date,
            sessions_per_week_target,
            max_session_minutes,
            block_start_date,
            1 if volume_budget_enabled else 0,
            main_lift_policy,
        ),
    )


def append_athlete_constraint(
    conn: sqlite3.Connection,
    *,
    kind: str,
    region: str,
    severity: str,
    forbidden_patterns: Sequence[str] = (),
    forbidden_exercises: Sequence[str] = (),
    rom_limit: str | None = None,
    since: str | None = None,
    settled_on: str | None = None,
    evidence: str | None = None,
    source: str = "user",
) -> None:
    conn.execute(
        """
        INSERT INTO athlete_constraint (kind, region, severity, forbidden_patterns,
                                        forbidden_exercises, rom_limit, since, settled_on,
                                        evidence, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            kind,
            region,
            severity,
            _json(list(forbidden_patterns)),
            _json(list(forbidden_exercises)),
            rom_limit,
            since,
            settled_on,
            evidence,
            source,
        ),
    )


def append_exercise_suitability(
    conn: sqlite3.Connection,
    *,
    exercise_id: str,
    rated_on: str,
    can_do: bool,
    will_do: bool,
    feels_bad: bool,
    note: str | None = None,
    source: str = "user",
) -> None:
    conn.execute(
        """
        INSERT INTO exercise_suitability (exercise_id, rated_on, can_do, will_do, feels_bad,
                                          note, source)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            exercise_id,
            rated_on,
            1 if can_do else 0,
            1 if will_do else 0,
            1 if feels_bad else 0,
            note,
            source,
        ),
    )


def append_metric_definition(
    conn: sqlite3.Connection,
    *,
    metric_key: str,
    label: str,
    higher_is_better: bool,
    aggregation: str,
    scale_min: float | None = None,
    scale_max: float | None = None,
    unit: str | None = None,
    source: str | None = None,
    active_from: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO metric_definition (metric_key, label, scale_min, scale_max,
                                       higher_is_better, aggregation, unit, source, active_from)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            metric_key,
            label,
            scale_min,
            scale_max,
            1 if higher_is_better else 0,
            aggregation,
            unit,
            source,
            active_from,
        ),
    )


def append_readiness_entry(
    conn: sqlite3.Connection,
    *,
    on_date: str,
    field: str,
    value: float,
    source: str = "manual",
    note: str | None = None,
) -> str:
    """Append one field reading; the latest entry for (date, field) wins at read time.

    This is the manual counterpart to the imported `readiness_day` row. Append-only is the
    point: re-logging a date is a correction, not an edit (DEC-READINESS-03).
    """
    if source not in {"manual", "import", "preset"}:
        raise ValueError(f"unknown readiness source {source!r}")
    readiness_utils.validate(field, value)
    entry_id = uuid.uuid4().hex
    recorded_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    conn.execute(
        """
        INSERT INTO readiness_entry (entry_id, on_date, field, value, source, recorded_at, note)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (entry_id, on_date, field, float(value), source, recorded_at, note),
    )
    return entry_id


def append_readiness_setting(
    conn: sqlite3.Connection,
    *,
    effective_from: str,
    baseline_days: int,
    baseline_min_readings: int,
    hrv_slope: float,
    rhr_slope: float,
    hrv_weight: float,
    rhr_weight: float,
    wearable_weight: float,
    note: str | None = None,
    source: str = "user",
) -> None:
    """Append a per-athlete score setting. Latest effective row wins; nothing is edited."""
    datetime.date.fromisoformat(str(effective_from))
    if not 1 <= int(baseline_days) <= 365:
        raise ValueError("baseline_days must be 1-365")
    if not 1 <= int(baseline_min_readings) <= int(baseline_days):
        raise ValueError("baseline_min_readings must be 1..baseline_days")
    for name, value in (("hrv_slope", hrv_slope), ("rhr_slope", rhr_slope)):
        if not 0 < float(value) <= 1:
            raise ValueError(f"{name} must be in (0, 1]")
    for name, value in (("hrv_weight", hrv_weight), ("rhr_weight", rhr_weight),
                        ("wearable_weight", wearable_weight)):
        if not 0 <= float(value) <= 1:
            raise ValueError(f"{name} must be from 0 to 1")
    uuid_value = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO readiness_setting (
            setting_id, effective_from, baseline_days, baseline_min_readings,
            hrv_slope, rhr_slope, hrv_weight, rhr_weight, wearable_weight,
            note, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid_value, str(effective_from), int(baseline_days), int(baseline_min_readings),
            float(hrv_slope), float(rhr_slope), float(hrv_weight), float(rhr_weight),
            float(wearable_weight), note, source,
        ),
    )


def append_readiness_override(
    conn: sqlite3.Connection,
    *,
    effective_on: str,
    scope: str,
    value: float,
    reason: str,
    source: str = "user",
) -> str:
    """Append a manual correction of a computed readiness score."""
    if scope != "global" and not scope.startswith("category:"):
        raise ValueError("scope must be 'global' or 'category:<name>'")
    if scope != "global":
        # A misspelt category used to be stored and then silently ignored by the score, so the
        # athlete saw "override saved" and an unchanged load. Refuse it at the write path.
        category = scope.split(":", 1)[1]
        if category not in readiness_utils.CATEGORY_PATTERNS:
            known = ", ".join(sorted(readiness_utils.CATEGORY_PATTERNS))
            raise ValueError(
                f"unknown readiness category {category!r}; known: {known}"
            )
    if not 0.0 <= float(value) <= 1.0:
        raise ValueError("readiness override must be between 0 and 1")
    if not reason.strip():
        raise ValueError("a readiness override needs a reason")
    override_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO readiness_override (override_id, effective_on, scope, value, reason, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (override_id, effective_on, scope, float(value), reason, source),
    )
    return override_id


def append_declared_break(
    conn: sqlite3.Connection,
    *,
    starts_on: str,
    ends_on: str,
    reason: str,
    note: str | None = None,
    cancels_break_id: int | None = None,
) -> int:
    """Append one break row. A cancellation is the same call with `cancels_break_id` set."""
    cursor = conn.execute(
        """
        INSERT INTO declared_break (starts_on, ends_on, reason, note, cancels_break_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (starts_on, ends_on, reason, note, cancels_break_id),
    )
    return int(cursor.lastrowid)


def append_symptom(
    conn: sqlite3.Connection,
    *,
    logged_on: str,
    timing: str,
    region: str,
    level: int,
    settled_within_48h: bool | None = None,
    note: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO symptom_log (logged_on, timing, region, level, settled_within_48h, note)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            logged_on,
            timing,
            region,
            int(level),
            None if settled_within_48h is None else (1 if settled_within_48h else 0),
            note,
        ),
    )


def append_prescription(
    conn: sqlite3.Connection,
    *,
    prescription_id: str,
    run_id: str,
    for_date: str,
    session_type: str,
    fallback_level: str,
    rule_document_version: str,
    calibration_ids: Sequence[str],
    approved_by: str,
    items: Sequence[Mapping[str, Any]],
    supersedes_id: str | None = None,
) -> str:
    """Store a prescription and its items in one transaction-like sequence."""
    conn.execute(
        """
        INSERT INTO prescription (prescription_id, run_id, for_date, session_type,
                                  fallback_level, rule_document_version, calibration_ids,
                                  approved_by, supersedes_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            prescription_id,
            run_id,
            for_date,
            session_type,
            fallback_level,
            rule_document_version,
            _json(list(calibration_ids)),
            approved_by,
            supersedes_id,
        ),
    )
    for item in items:
        conn.execute(
            """
            INSERT INTO prescription_item (
                prescription_id, order_index, exercise_id, sets, reps_low, reps_high,
                load_kg, load_basis, rounding_increment, rir_target, velocity_target,
                vbt_basis, e1rm_source_sets, rest_s, time_cap_s, essential, rationale_refs,
                substitution_for, warmup_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prescription_id,
                int(item["order_index"]),
                str(item["exercise_id"]),
                int(item["sets"]),
                item["reps_low"],
                item["reps_high"],
                item["load_kg"],
                str(item["load_basis"]),
                item["rounding_increment"],
                item["rir_target"],
                item.get("velocity_target"),
                item.get("vbt_basis"),
                item.get("e1rm_source_sets"),
                item.get("rest_s"),
                item.get("time_cap_s"),
                1 if item["essential"] else 0,
                _json(list(item.get("rationale_refs") or [])),
                item.get("substitution_for"),
                _json(list(item.get("warmup") or [])),
            ),
        )
    return prescription_id


def append_volume_exemption(
    conn: sqlite3.Connection,
    *,
    prescription_id: str,
    effective_on: str,
    pattern: str,
    sets: int,
    source: str,
) -> None:
    """Record sets a safety/recovery rule removed from a week (DEC-VOLUME-06).

    The weekly budget must not re-add a readiness, deload, spinal or constraint cut. The
    prescription has no notes column, so this append-only row is the record; `source` names
    the modifier (for example MOD-FAT-001) or CONSTRAINT.
    """
    if not str(prescription_id).strip():
        raise ValueError("a volume exemption needs a prescription")
    if not str(pattern).strip():
        raise ValueError("a volume exemption needs a pattern")
    if int(sets) <= 0:
        raise ValueError("a volume exemption must remove at least one set")
    if not str(source).strip():
        raise ValueError("a volume exemption needs a source")
    conn.execute(
        """
        INSERT INTO volume_exemption
            (prescription_id, effective_on, pattern, sets, source)
        VALUES (?, ?, ?, ?, ?)
        """,
        (str(prescription_id), str(effective_on), str(pattern), int(sets), str(source)),
    )


def append_rubric_mark(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    item: str,
    score: float | None,
    confidence: str,
    rubric_version: str,
    note: str | None = None,
) -> None:
    """Record one human mark. Corrections append; they never edit (DEC-EVAL-04)."""
    conn.execute(
        """
        INSERT INTO rubric_mark (session_id, item, score, confidence, rubric_version, note)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (session_id, item, score, confidence, rubric_version, note),
    )


def append_critique(
    conn: sqlite3.Connection,
    *,
    critique_id: str,
    run_id: str,
    session_id: str,
    narrative: str | None,
    facts_hash: str,
    supersedes_id: str | None = None,
) -> str:
    """Store one critique. `facts_hash` ties it to the exact facts it scored."""
    conn.execute(
        """
        INSERT INTO critique (critique_id, run_id, session_id, narrative, facts_hash,
                              supersedes_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (critique_id, run_id, session_id, narrative, facts_hash, supersedes_id),
    )
    return critique_id


def append_rubric_score(
    conn: sqlite3.Connection,
    *,
    critique_id: str,
    item: str,
    score: float | None,
    weight: float,
    evidence_refs: Sequence[str],
    rule_ids: Sequence[str],
    measurable: bool,
) -> None:
    """Store one rubric line.

    `measurable = 0` rows must carry no score: the schema refuses a guessed number for a
    metric the data cannot support (DATA-MODEL §9).
    """
    conn.execute(
        """
        INSERT INTO rubric_score (critique_id, item, score, weight, evidence_refs, rule_ids,
                                  measurable)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            critique_id,
            item,
            score,
            weight,
            _json(list(evidence_refs)),
            _json(list(rule_ids)),
            1 if measurable else 0,
        ),
    )


def append_rule_document(
    conn: sqlite3.Connection,
    *,
    document_id: str,
    version: str,
    effective_from: str,
    source_hash: str,
    body_yaml: str,
) -> None:
    """Store one immutable constitution version; a change is a new version, never an edit."""
    conn.execute(
        """
        INSERT INTO rule_document (document_id, version, effective_from, source_hash, body_yaml)
        VALUES (?, ?, ?, ?, ?)
        """,
        (document_id, version, effective_from, source_hash, body_yaml),
    )


def append_cardio(
    conn: sqlite3.Connection,
    *,
    performed_on: str,
    modality: str,
    duration_s: int,
    avg_hr: int | None = None,
    max_hr: int | None = None,
    distance_m: float | None = None,
    srpe: int | None = None,
    note: str | None = None,
) -> str:
    """Append one cardio session.

    Validation lives here so the CLI and the web form cannot diverge. A missing optional
    field stays null; a zero is not a sentinel here, so `avg_hr=0` is rejected rather than
    treated as "not recorded" (AGENTS.md §5).
    """
    try:
        datetime.date.fromisoformat(str(performed_on))
    except ValueError as exc:
        raise ValueError(f"date must be YYYY-MM-DD: {performed_on!r}") from exc

    label = str(modality).strip().lower()
    if not label:
        raise ValueError("modality cannot be empty")
    seconds = int(duration_s)
    if seconds <= 0:
        raise ValueError("duration must be positive")

    def bounded(value: int | None, name: str, low: int, high: int) -> int | None:
        if value is None:
            return None
        number = int(value)
        if not low <= number <= high:
            raise ValueError(f"{name} must be {low}-{high}, got {number}")
        return number

    avg = bounded(avg_hr, "avg_hr", 30, 230)
    peak = bounded(max_hr, "max_hr", 30, 250)
    if avg is not None and peak is not None and avg > peak:
        raise ValueError("avg_hr cannot exceed max_hr")
    effort = bounded(srpe, "srpe", 1, 10)
    distance = None if distance_m is None else float(distance_m)
    if distance is not None and distance < 0:
        raise ValueError("distance_m cannot be negative")

    entry_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO cardio_log (
            entry_id, performed_on, modality, duration_s, avg_hr, max_hr, distance_m,
            srpe, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (entry_id, str(performed_on), label, seconds, avg, peak, distance, effort, note),
    )
    return entry_id


def append_measurement(
    conn: sqlite3.Connection,
    *,
    metric_key: str,
    measured_on: str,
    value: float,
    method: str | None = None,
    source: str = "user",
    note: str | None = None,
) -> str:
    """Append one periodic measurement; the metric definition must already exist.

    Direction and aggregation live in `metric_definition`, not here, so the same number can
    never be read as "higher is better" in one place and "lower is better" in another.
    """
    try:
        datetime.date.fromisoformat(str(measured_on))
    except ValueError as exc:
        raise ValueError(f"date must be YYYY-MM-DD: {measured_on!r}") from exc
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("value must be a finite number")
    if source not in {"user", "clinician", "device"}:
        raise ValueError(f"unknown measurement source {source!r}")

    measurement_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO measurement (measurement_id, metric_key, measured_on, value, method,
                                 source, note)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            measurement_id,
            str(metric_key),
            str(measured_on),
            number,
            method or None,
            source,
            note or None,
        ),
    )
    return measurement_id


def append_session_feedback(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    srpe: float | None = None,
    duration_min: float | None = None,
    note: str | None = None,
) -> str:
    """Append optional post-session feedback; latest row per session wins at read time."""
    if srpe is None and duration_min is None and not (note or "").strip():
        raise ValueError("at least one of srpe, duration_min or note is required")
    if srpe is not None:
        srpe = float(srpe)
        if not 1 <= srpe <= 10:
            raise ValueError("session RPE must be between 1 and 10")
    if duration_min is not None:
        duration_min = float(duration_min)
        if not 0 < duration_min <= 600:
            raise ValueError("session length must be between 0 and 600 minutes")
    feedback_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO session_feedback (feedback_id, session_id, srpe, duration_min, note)
        VALUES (?, ?, ?, ?, ?)
        """,
        (feedback_id, str(session_id), srpe, duration_min, (note or "").strip() or None),
    )
    return feedback_id


def append_maintenance_review(
    conn: sqlite3.Connection,
    *,
    task_key: str,
    action: str,
    reviewed_on: str,
    decision: str | None = None,
    note: str | None = None,
    snoozed_until: str | None = None,
) -> str:
    """Append a human acknowledgement of a periodic review.

    A completed review must carry a decision; a snooze must carry an until-date. This keeps
    "reviewed" from becoming a no-op and keeps snoozing distinct from completion.
    """
    task_key = str(task_key).strip()
    action = str(action).strip().lower()
    if action not in {"completed", "snoozed"}:
        raise ValueError("review action must be completed or snoozed")
    if action == "completed":
        if decision not in {"kept", "changed", "insufficient", "not_applicable"}:
            raise ValueError("completed review needs a valid decision")
        snoozed_until = None
    else:
        decision = None
        if not snoozed_until:
            raise ValueError("snoozed review needs snoozed_until")
    review_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO maintenance_review (
            review_id, task_key, action, decision, note, reviewed_on, snoozed_until
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            review_id, task_key, action, decision,
            (note or "").strip() or None, str(reviewed_on), snoozed_until,
        ),
    )
    return review_id


def append_high_intensity_exposure(
    conn: sqlite3.Connection,
    *,
    performed_on: str,
    kind: str,
    region_load: str,
    intensity_class: str = "near_max",
    exercise_id: str | None = None,
    session_id: str | None = None,
    set_id: int | None = None,
    axial_cost: int | None = None,
    novelty: str = "unknown",
    test_type: str | None = None,
    source: str = "manual",
    source_id: str | None = None,
    supersedes_id: str | None = None,
    note: str | None = None,
) -> str:
    """Append a high-intensity exposure without touching the volume ledger."""
    if not str(performed_on).strip():
        raise ValueError("performed_on is required")
    if kind not in {"test", "max_attempt", "competition", "unplanned", "other"}:
        raise ValueError(f"unknown exposure kind {kind!r}")
    if region_load not in {"upper", "lower", "axial", "mixed", "unknown"}:
        raise ValueError(f"unknown region_load {region_load!r}")
    if intensity_class not in {"near_max", "high", "moderate", "unknown"}:
        raise ValueError(f"unknown intensity_class {intensity_class!r}")
    if source not in {"test_record", "set_link", "manual"}:
        raise ValueError(f"unknown exposure source {source!r}")
    if set_id is not None and not session_id:
        raise ValueError("a set-linked exposure needs session_id")
    if kind == "test" and set_id is not None:
        raise ValueError("a test exposure cannot link to a set")
    if test_type is not None and test_type not in {"1RM", "3RM", "5RM", "other"}:
        raise ValueError(f"unknown test_type {test_type!r}")

    if source_id is not None:
        existing = conn.execute(
            "SELECT exposure_id FROM high_intensity_exposure "
            " WHERE source = ? AND source_id = ?",
            (source, str(source_id)),
        ).fetchone()
        if existing is not None:
            return str(existing["exposure_id"])

    exposure_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO high_intensity_exposure (
            exposure_id, performed_on, kind, exercise_id, session_id, set_id,
            region_load, intensity_class, axial_cost, novelty, test_type,
            source, source_id, supersedes_id, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            exposure_id, str(performed_on), kind, exercise_id, session_id, set_id,
            region_load, intensity_class, axial_cost, novelty, test_type,
            source, source_id, supersedes_id, (note or "").strip() or None,
        ),
    )
    return exposure_id


def append_prescription_modifier(
    conn: sqlite3.Connection,
    *,
    prescription_id: str,
    modifier_key: str,
    applied_on: str,
    detail: Mapping[str, object] | None = None,
) -> str:
    """Record that a modifier changed a stored prescription. Provenance only."""
    modifier_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO prescription_modifier (
            modifier_id, prescription_id, modifier_key, applied_on, detail_json
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            modifier_id, str(prescription_id), str(modifier_key), str(applied_on),
            _json(dict(detail or {})),
        ),
    )
    return modifier_id


def append_readiness_context(
    conn: sqlite3.Connection,
    *,
    on_date: str,
    flag: str,
    note: str | None = None,
) -> str:
    """Append a context flag. It is displayed, not scored by default."""
    from strength_coach.features.readiness import CONTEXT_FLAGS

    if flag not in CONTEXT_FLAGS:
        raise ValueError(f"unknown readiness context flag {flag!r}")
    context_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO readiness_context (context_id, on_date, flag, note) VALUES (?, ?, ?, ?)",
        (context_id, str(on_date), flag, (note or "").strip() or None),
    )
    return context_id