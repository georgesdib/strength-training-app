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
