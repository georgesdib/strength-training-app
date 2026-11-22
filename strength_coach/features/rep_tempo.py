"""Descriptive per-set motion report: phase durations, TUT and consistency.

This module never feeds a prescription. It reads the optional per-rep phase detail produced
by a device capture and summarises it per set. A set without usable detail abstains with a
reason instead of reporting a zero.

The import boundary is part of the contract: nothing here may be imported by a prescribe,
calibration or readiness module.
"""

from __future__ import annotations

from collections.abc import Sequence

# A median confidence below this is treated as a failed derivation rather than a measurement.
# The value matches the on-device gate; both are versioned by method_version.
LOW_CONFIDENCE = 0.6

ABSTENTIONS = {
    "no_detail": "No per-rep motion detail was captured for this set.",
    "incomplete_set": "Motion detail does not cover every rep.",
    "low_confidence": "The derived phases were below the confidence floor.",
    "feature_disabled": "Motion capture was not enabled for this set.",
}


def _median(values: Sequence[float]) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def _cv(values: Sequence[float]) -> float | None:
    """Coefficient of variation, in percent, of a non-empty sequence."""
    centre = _median(values)
    if not centre:
        return None
    spread = _median([abs(value - centre) for value in values])
    return round(100.0 * spread / centre, 1)


def summarise(rows: Sequence[dict], *, expected_reps: int | None) -> dict:
    """Summarise one set's phase rows, or explain why it cannot be summarised."""
    if not rows:
        return {"abstention": "no_detail"}
    if expected_reps is not None and len(rows) != int(expected_reps):
        return {"abstention": "incomplete_set"}

    confidences = [float(row["confidence"]) for row in rows if row.get("confidence") is not None]
    median_confidence = _median(confidences)
    if median_confidence is not None and median_confidence < LOW_CONFIDENCE:
        return {"abstention": "low_confidence", "median_confidence": round(median_confidence, 2)}

    lower = [float(row["lower_ms"]) for row in rows if row.get("lower_ms") is not None]
    lift = [float(row["lift_ms"]) for row in rows if row.get("lift_ms") is not None]
    pause = [float(row["pause_ms"]) for row in rows if row.get("pause_ms") is not None]
    durations = (
        [down + up for down, up in zip(lower, lift, strict=True)]
        if len(lower) == len(lift) and lower
        else []
    )
    tut_ms = sum(lower) + sum(lift) + sum(pause)
    return {
        "abstention": None,
        "reps": len(rows),
        "lower_median_ms": round(_median(lower)) if lower else None,
        "lift_median_ms": round(_median(lift)) if lift else None,
        "pause_median_ms": round(_median(pause)) if pause else None,
        "tut_s": round(tut_ms / 1000, 1) if tut_ms else None,
        "duration_cv_pct": _cv(durations) if durations else None,
        "median_confidence": round(median_confidence, 2) if median_confidence is not None else None,
    }


def session_report(conn, session_id: str) -> dict:
    """Per-set motion summary for one session. Read-only; writes nothing."""
    sets = conn.execute(
        """
        SELECT s.set_id, s.reps, s.exercise_id
        FROM clean_set s
        WHERE s.session_id = ? AND s.voided = 0
          AND NOT EXISTS (SELECT 1 FROM clean_set child
                          WHERE child.supersedes_id = s.set_id)
        ORDER BY s.set_id
        """,
        (session_id,),
    ).fetchall()
    rows = conn.execute(
        """
        SELECT r.clean_set_id, r.rep_index, r.lower_ms, r.lift_ms, r.pause_ms,
               r.rom_m, r.steadiness, r.confidence, r.method_version, r.source
        FROM clean_rep_phase r
        JOIN clean_set s ON s.set_id = r.clean_set_id
        WHERE s.session_id = ? AND s.voided = 0
          AND NOT EXISTS (SELECT 1 FROM clean_set child
                          WHERE child.supersedes_id = s.set_id)
        ORDER BY r.clean_set_id, r.rep_index
        """,
        (session_id,),
    ).fetchall()

    by_set: dict[int, list[dict]] = {}
    for row in rows:
        by_set.setdefault(int(row["clean_set_id"]), []).append(dict(row))

    result = []
    for item in sets:
        set_id = int(item["set_id"])
        detail = by_set.get(set_id) or []
        summary = summarise(detail, expected_reps=item["reps"])
        result.append({
            "set_id": set_id,
            "exercise_id": item["exercise_id"],
            "source": (detail[0]["source"] if detail else None),
            "method_version": (detail[0]["method_version"] if detail else None),
            **summary,
        })
    captured = sum(1 for item in result if item["abstention"] is None)
    return {
        "status": "ok" if captured else "unavailable",
        "reason": None if captured else "no_detail",
        "sets": result,
        "captured_sets": captured,
        "total_sets": len(result),
    }
