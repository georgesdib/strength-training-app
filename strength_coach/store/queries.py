"""Read helpers for the rules layer.

`repositories` is deliberately write-only; this module is the read side, so an accidental
UPDATE cannot slip in among the queries.

`clean_sets` returns a frame shaped like the cleaner's output, not like the table: callers
above the store expect the domain vocabulary (`date`, `rir_class`, `flags` joined by ";").
Reconstructing those from the stored columns is safe because:

* `rir_class` is a pure function of `rir` (`domain.rir.classify` is the single definition);
* `total_load_kg` equals `load_kg` for every row where an e1RM is applicable, because
  `features.derived.e1rm_applicable` rejects bodyweight-typed entities, whose "added" basis
  is the only case where total mass differs.
"""

from __future__ import annotations

import json

import pandas as pd

from strength_coach.domain import rir as rir_mod

_SET_COLUMNS = {
    "set_id": "set_id",
    "session_id": "session_id",
    "occurred_on": "date",
    "exercise_id": "exercise_id",
    "raw_exercise": "raw_exercise",
    "load_kg": "load_kg",
    "load_basis": "load_basis",
    "external_load_kg": "external_load_kg",
    "reps": "reps",
    "reps_unit": "reps_unit",
    "rir": "rir",
    "rir_source": "rir_source",
    "velocity_mps": "velocity_mps",
    "velocity_present": "velocity_present",
    "rom_mm": "rom_mm",
    "tut_s": "tut_s",
    "form_score": "form_score",
    "tonnage_kg": "tonnage_kg",
    "is_working_set": "is_working_set",
    "flags": "flags",
    "source_row": "source_row",
}


def clean_sets(
    conn,
    *,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Every clean set in [start, end], in the cleaner's domain shape."""
    sql = (
        "SELECT s.set_id, s.session_id, s.occurred_on, s.exercise_id, s.raw_exercise,"
        " s.load_kg, s.load_basis, s.external_load_kg, s.reps, s.reps_unit, s.rir,"
        " s.rir_source, s.velocity_mps, s.velocity_present, s.rom_mm, s.tut_s,"
        " s.form_score, s.tonnage_kg, s.is_working_set, s.flags, r.source_row"
        " FROM clean_set s JOIN raw_row r ON r.raw_id = s.raw_id"
    )
    params: list[object] = []
    if start is not None:
        sql += " WHERE s.occurred_on >= ?"
        params.append(start)
    if end is not None:
        sql += (" WHERE s.occurred_on <= ?" if start is None else " AND s.occurred_on <= ?")
        params.append(end)
    sql += " ORDER BY s.occurred_on, s.set_id"

    rows = [dict(row) for row in conn.execute(sql, params)]
    if not rows:
        return pd.DataFrame(columns=list(_SET_COLUMNS.values()) + ["rir_class", "total_load_kg"])

    frame = pd.DataFrame(rows).rename(columns=_SET_COLUMNS)
    frame["date"] = pd.to_datetime(frame["date"])
    frame["set_id"] = frame["set_id"].astype(int)
    frame["is_working_set"] = frame["is_working_set"].astype(bool)
    frame["velocity_present"] = frame["velocity_present"].astype(bool)
    frame["rir_class"] = frame["rir"].map(lambda value: rir_mod.classify(value).klass)
    frame["total_load_kg"] = frame["load_kg"]
    frame["flags"] = frame["flags"].map(_flags_to_ingest_form)
    frame["source_row"] = frame["source_row"].astype(int)
    return frame


def latest_rubric_marks(conn) -> list[dict]:
    """The most recent mark per (session, item), newest session first.

    `rubric_mark` is append-only, so the latest row wins; an earlier mark stays in the table
    as history but no longer participates in calibration.
    """
    rows = conn.execute(
        """
        SELECT m.session_id, m.item, m.score, m.confidence, m.rubric_version, m.marked_at
          FROM rubric_mark m
          JOIN (
                SELECT session_id, item, MAX(mark_id) AS keep_id
                  FROM rubric_mark
              GROUP BY session_id, item
               ) latest
            ON latest.keep_id = m.mark_id
      ORDER BY m.session_id DESC, m.item
        """
    ).fetchall()
    return [dict(row) for row in rows]


def readiness_day(conn, on_date: str) -> dict | None:
    """One merged readiness row, or None when the date has no readiness data."""
    row = conn.execute(
        "SELECT * FROM readiness_day WHERE on_date = ?", (str(on_date),)
    ).fetchone()
    return dict(row) if row is not None else None


def sessions(conn, *, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """Reconstructed sessions, one row per date."""
    sql = "SELECT * FROM session"
    params: list[object] = []
    if start is not None:
        sql += " WHERE occurred_on >= ?"
        params.append(start)
    if end is not None:
        sql += (" WHERE occurred_on <= ?" if start is None else " AND occurred_on <= ?")
        params.append(end)
    sql += " ORDER BY occurred_on"
    rows = [dict(row) for row in conn.execute(sql, params)]
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["occurred_on"] = pd.to_datetime(frame["occurred_on"])
    return frame


def _flags_to_ingest_form(raw: str) -> str:
    """JSON list in the column -> the ";"-joined form the ingest layer emits."""
    try:
        values = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return str(raw or "")
    return ";".join(str(v) for v in values)
