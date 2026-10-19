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
from strength_coach.utils import readiness as readiness_utils

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


def e1rm_override(conn, exercise_id: str, on_date: str) -> dict | None:
    """The override in force for this lift on this date, if any.

    The latest row wins; an expired or future-dated row never applies. A NULL `expires_on`
    means "until replaced".
    """
    row = conn.execute(
        """
        SELECT * FROM e1rm_override
         WHERE exercise_id = ?
           AND effective_from <= ?
           AND (expires_on IS NULL OR expires_on >= ?)
         ORDER BY effective_from DESC, override_id DESC
         LIMIT 1
        """,
        (str(exercise_id), str(on_date), str(on_date)),
    ).fetchone()
    return dict(row) if row is not None else None


def last_measured_override(conn, exercise_id: str) -> dict | None:
    """The most recent *test-derived* override, regardless of its effective window.

    Used to enforce the testing interval: an expired override still proves the test happened.
    """
    row = conn.execute(
        """
        SELECT * FROM e1rm_override
         WHERE exercise_id = ? AND source = 'measured'
         ORDER BY effective_from DESC, override_id DESC
         LIMIT 1
        """,
        (str(exercise_id),),
    ).fetchone()
    return dict(row) if row is not None else None


def e1rm_overrides(conn) -> list[dict]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM e1rm_override ORDER BY exercise_id, effective_from DESC, override_id DESC"
        )
    ]


def e1rm_override_by_id(conn, override_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM e1rm_override WHERE override_id = ?", (int(override_id),)
    ).fetchone()
    return dict(row) if row is not None else None


def athlete_profile(conn) -> dict | None:
    """The current profile: the latest version by effective date."""
    row = conn.execute(
        "SELECT * FROM athlete_profile ORDER BY effective_from DESC, profile_id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row is not None else None


def athlete_constraints(conn) -> list[dict]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM athlete_constraint ORDER BY constraint_id"
        )
    ]


def exercise_suitability(conn) -> dict[str, dict]:
    """The latest rating per exercise; earlier ratings stay in the table as history."""
    rows = conn.execute(
        """
        SELECT s.* FROM exercise_suitability s
          JOIN (SELECT exercise_id, MAX(rated_on) AS latest
                  FROM exercise_suitability GROUP BY exercise_id) l
            ON l.exercise_id = s.exercise_id AND l.latest = s.rated_on
        """
    ).fetchall()
    return {str(row["exercise_id"]): dict(row) for row in rows}


def symptom_for_date(conn, on_date: str, *, timing: str = "pre_session") -> dict | None:
    """The latest pre-session entry for a date, or None when none was logged."""
    row = conn.execute(
        """
        SELECT * FROM symptom_log
         WHERE logged_on = ? AND timing = ?
         ORDER BY log_id DESC LIMIT 1
        """,
        (str(on_date), timing),
    ).fetchone()
    return dict(row) if row is not None else None


def latest_symptom(conn, on_or_before: str, *, timing: str = "pre_session") -> dict | None:
    """The most recent entry at or before a date: the symptom state in force that day."""
    row = conn.execute(
        """
        SELECT * FROM symptom_log
         WHERE logged_on <= ? AND timing = ?
         ORDER BY logged_on DESC, log_id DESC LIMIT 1
        """,
        (str(on_or_before), timing),
    ).fetchone()
    return dict(row) if row is not None else None


def symptom_entries(conn, *, since: str | None = None) -> list[dict]:
    sql = "SELECT * FROM symptom_log"
    params: list[object] = []
    if since is not None:
        sql += " WHERE logged_on >= ?"
        params.append(since)
    sql += " ORDER BY logged_on, log_id"
    return [dict(row) for row in conn.execute(sql, params)]


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
    """One merged readiness row, or None when the date has no usable data.

    Imported values come from `readiness_day`; manual values are append-only entries and win
    **per field** (DEC-READINESS-03). This is why a partial manual reading does not erase the
    imported fields around it. Sources are returned so the caller can say which value won.
    """
    row = conn.execute(
        "SELECT * FROM readiness_day WHERE on_date = ?", (str(on_date),)
    ).fetchone()
    base = dict(row) if row is not None else None

    entries = conn.execute(
        """
        SELECT field, value, source, recorded_at, entry_id
          FROM readiness_entry
         WHERE on_date = ?
         ORDER BY recorded_at, rowid
        """,
        (str(on_date),),
    ).fetchall()

    merged: dict = dict(base) if base is not None else {"on_date": str(on_date)}
    sources: dict[str, str] = {}
    manual_note: dict[str, dict] = {}
    if base is not None:
        for field in readiness_utils.READINESS_FIELDS:
            if base.get(field) is not None:
                sources[field] = "import"
    for entry in entries:
        field = str(entry["field"])
        if str(entry["source"]) == "manual" and base is not None:
            manual_note[field] = {
                "imported": base.get(field),
                "manual": entry["value"],
                "winner": "manual",
            }
        merged[field] = entry["value"]
        sources[field] = str(entry["source"])

    if not any(merged.get(field) is not None for field in readiness_utils.READINESS_FIELDS):
        return None
    merged["sources"] = sources
    merged["manual_merge_note"] = json.dumps(manual_note, sort_keys=True)
    merged["manual_fields"] = sorted(
        field for field, source in sources.items() if source == "manual"
    )
    return merged


def unreviewed_sessions(conn, *, limit: int = 50) -> list[str]:
    """Sessions with no marks *after the latest reviewed session*, oldest first.

    The athlete does not need to reconstruct the distant past: catch-up stops at the last
    reviewed workout. If nothing has ever been reviewed, fall back to the most recent `limit`
    sessions rather than the whole history.
    """
    last = conn.execute(
        """
        SELECT MAX(s.occurred_on) AS last
          FROM session s
          JOIN rubric_mark m ON m.session_id = s.session_id
        """
    ).fetchone()["last"]

    if last is None:
        rows = conn.execute(
            """
            SELECT s.session_id FROM session s
             WHERE NOT EXISTS (
                   SELECT 1 FROM rubric_mark m WHERE m.session_id = s.session_id
             )
             ORDER BY s.occurred_on DESC LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [str(row["session_id"]) for row in reversed(rows)]

    rows = conn.execute(
        """
        SELECT s.session_id FROM session s
         WHERE NOT EXISTS (
               SELECT 1 FROM rubric_mark m WHERE m.session_id = s.session_id
         )
           AND s.occurred_on > ?
         ORDER BY s.occurred_on ASC
         LIMIT ?
        """,
        (last, int(limit)),
    ).fetchall()
    return [str(row["session_id"]) for row in rows]


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
