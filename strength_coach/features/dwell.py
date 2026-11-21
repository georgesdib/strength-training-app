"""Exercise dwell model: done-exposure counters, the dwell factor and the exploration draw.

The model and its worked examples live in docs/DWELL-AND-ROTATION.md; the policy decision is
DEC-RESOLVER-15 (which supersedes the deterministic dwell of DEC-RESOLVER-02).

In short:

* One mutable counter per exercise (exercise_dwell_state), incremented once per completed
  training day that contains at least one working set of that lift -- so an accessory use of
  the same exercise counts too. When the counter reaches the dwell target it resets to 0.
* The selection factor is f(c) = 1 - exp(-c / tau). f(0) = 0 (a lift that has never been done
  is unattractive) and f is close to 1 for any lift in the current cycle, so the model keeps
  an incumbent sticky without making the counter a hard pin. f(c >= target) is never scored:
  the lift is excluded from automatic selection (reachable only after the target is lowered or
  a counter is edited) and the next completion resets it.
* Exploration is probabilistic: each slot draws a deterministic pseudo-random number keyed on
  (date, session type, slot id) and changes to the best-ranked alternative when the draw is
  below the configured probability. The seed makes the draw reproducible for a preview and the
  prescription built from it, without making the generator random.
"""

from __future__ import annotations

import hashlib
import math
import sqlite3


def factor(count: int, tau: float) -> float:
    """Dwell factor for a done-exposure count: 0 at 0, saturating to 1.

    tau is the exposure scale in the exponent. A missing or non-positive tau is read as
    "saturate immediately" rather than dividing by zero; the settings registry keeps it positive.
    """
    if count <= 0:
        return 0.0
    if tau <= 0:
        return 1.0
    return max(0.0, min(1.0, 1.0 - math.exp(-float(count) / float(tau))))


def rotation_value(*, for_date: str, session_type: str, slot_id: str) -> float:
    """Deterministic draw in [0, 1) for one slot of one session date.

    The value is a pure function of its inputs, so a preview and the prescription saved from it
    make the same decision. It is not a source of true randomness; it is a reproducible draw.
    """
    key = "\x1f".join((str(for_date), str(session_type), str(slot_id)))
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:16], 16) / float(1 << 64)


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    """The current cycle counter for every exercise that has one."""
    return {
        str(row["exercise_id"]): int(row["done_count"])
        for row in conn.execute(
            "SELECT exercise_id, done_count FROM exercise_dwell_state"
        )
    }


def _upsert(conn: sqlite3.Connection, exercise_id: str, count: int) -> None:
    conn.execute(
        """
        INSERT INTO exercise_dwell_state (exercise_id, done_count, updated_at)
        VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        ON CONFLICT(exercise_id) DO UPDATE
           SET done_count = excluded.done_count, updated_at = excluded.updated_at
        """,
        (str(exercise_id), int(count)),
    )


def done_exercises(
    conn: sqlite3.Connection, *, session_id: str, for_date: str
) -> set[str]:
    """Exercises with a working set in this session that had none earlier the same day.

    clean_set is written by the completion path in the same transaction, so this is the
    authoritative "done" record. The same-day check keeps the counter a count of training
    days, not of sessions: a second workout on one date does not advance an exercise twice.
    """
    rows = conn.execute(
        "SELECT DISTINCT exercise_id FROM clean_set"
        " WHERE session_id = ? AND is_working_set = 1",
        (str(session_id),),
    ).fetchall()
    done: set[str] = set()
    for row in rows:
        exercise_id = str(row["exercise_id"])
        prior = conn.execute(
            "SELECT 1 FROM clean_set"
            " WHERE occurred_on = ? AND exercise_id = ? AND is_working_set = 1"
            "   AND session_id <> ? LIMIT 1",
            (str(for_date), exercise_id, str(session_id)),
        ).fetchone()
        if prior is None:
            done.add(exercise_id)
    return done


def record_completion(
    conn: sqlite3.Connection, *, session_id: str, for_date: str, target: int
) -> int:
    """Advance the counters for one completed workout; return how many advanced.

    A completion that reaches the target wraps to 0, so the lift re-enters the pool at the
    least attractive end of the factor rather than staying at the cap. Idempotency is owned by
    the caller: workout completion runs this once, inside the completion transaction.
    """
    target = max(1, int(target))
    advanced = 0
    for exercise_id in sorted(done_exercises(conn, session_id=session_id, for_date=for_date)):
        row = conn.execute(
            "SELECT done_count FROM exercise_dwell_state WHERE exercise_id = ?",
            (exercise_id,),
        ).fetchone()
        count = (int(row["done_count"]) if row is not None else 0) + 1
        if count >= target:
            count = 0
        _upsert(conn, exercise_id, count)
        advanced += 1
    return advanced


def set_count(conn: sqlite3.Connection, exercise_id: str, count: int) -> None:
    """Set one counter directly (the Settings -> Resolver dwell panel)."""
    _upsert(conn, str(exercise_id), max(0, int(count)))


def reconcile(conn: sqlite3.Connection, target: int) -> int:
    """Zero counters that the new target has left at or above the cap; return how many.

    Called when the dwell target changes (and available for a manual repair). Without it a
    lowered target would strand every over-cap lift outside automatic selection until its next
    completion.
    """
    target = max(1, int(target))
    rows = conn.execute(
        "SELECT exercise_id FROM exercise_dwell_state WHERE done_count >= ?",
        (target,),
    ).fetchall()
    for row in rows:
        _upsert(conn, str(row["exercise_id"]), 0)
    return len(rows)
