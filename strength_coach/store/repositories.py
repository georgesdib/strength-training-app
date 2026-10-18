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

import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from strength_coach.ingest.sessions import Session
from strength_coach.utils import numeric

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
    """Persist every source line verbatim; return ({source_row: raw_id}, rows inserted).

    The payload is the row exactly as read (`io_utils` keeps cells as text), so a cleaning
    bug can always be re-run against the original bytes rather than against its own output.
    """
    if table_name not in {"training", "readiness"}:
        raise ValueError(f"unknown table_name: {table_name}")

    rows = [
        (
            table_name,
            index,
            file_sha256,
            _json({str(k): (None if _opt(v) is None else str(v)) for k, v in record.items()}),
        )
        for index, record in enumerate(frame.to_dict(orient="records"), start=1)
    ]
    existing = {
        int(row["source_row"])
        for row in conn.execute(
            "SELECT source_row FROM raw_row WHERE table_name = ? AND file_sha256 = ?",
            (table_name, file_sha256),
        )
    }
    fresh = [row for row in rows if row[1] not in existing]
    # A plain INSERT, not INSERT OR IGNORE: a duplicate is skipped deliberately above, so any
    # IntegrityError that still fires is a real schema violation and must not be swallowed.
    inserted = _changes(
        conn,
        "INSERT INTO raw_row (table_name, source_row, file_sha256, payload) VALUES (?, ?, ?, ?)",
        fresh,
    )
    mapping = {
        int(row["source_row"]): int(row["raw_id"])
        for row in conn.execute(
            "SELECT source_row, raw_id FROM raw_row WHERE table_name = ? AND file_sha256 = ?",
            (table_name, file_sha256),
        )
    }
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
            session.day,
            session.day_confidence,
            session.day_reason,
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
            exercise_count, main_lifts, day_guess, day_confidence, day_reason,
            tonnage_kg, flags, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        ON CONFLICT(session_id) DO UPDATE SET
            occurred_on       = excluded.occurred_on,
            workout_label     = excluded.workout_label,
            set_count         = excluded.set_count,
            working_set_count = excluded.working_set_count,
            exercise_count    = excluded.exercise_count,
            main_lifts        = excluded.main_lifts,
            day_guess         = excluded.day_guess,
            day_confidence    = excluded.day_confidence,
            day_reason        = excluded.day_reason,
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
        "bodyweight_kg", "fat_pct",
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
) -> None:
    """Append a profile version. A reset or a goal change is a new row (DEC-RAMP-01)."""
    conn.execute(
        """
        INSERT INTO athlete_profile (effective_from, primary_goal, goal_rank, focus_lifts,
                                     competition_date, sessions_per_week_target,
                                     max_session_minutes, block_start_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
    session_day: str,
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
        INSERT INTO prescription (prescription_id, run_id, for_date, session_day,
                                  fallback_level, rule_document_version, calibration_ids,
                                  approved_by, supersedes_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            prescription_id,
            run_id,
            for_date,
            session_day,
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
                vbt_basis, rest_s, time_cap_s, essential, rationale_refs, substitution_for
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                item.get("rest_s"),
                item.get("time_cap_s"),
                1 if item["essential"] else 0,
                _json(list(item.get("rationale_refs") or [])),
                item.get("substitution_for"),
            ),
        )
    return prescription_id


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
