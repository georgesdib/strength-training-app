"""Descriptive per-rep velocity report.

This module never feeds a prescription. It summarises the optional clean_rep detail produced by
a workout import: first/last/mean/min/max and within-set velocity loss.
"""

from __future__ import annotations

from strength_coach.store import queries


def summarize(values: list[float]) -> dict | None:
    if not values:
        return None
    first = float(values[0])
    last = float(values[-1])
    return {
        "count": len(values),
        "first": round(first, 3),
        "last": round(last, 3),
        "mean": round(sum(values) / len(values), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "loss_abs": round(first - last, 3),
        "loss_pct": round((first - last) / first * 100, 2) if first else None,
    }


def session_report(conn, session_id: str) -> dict:
    rows = conn.execute(
        """
        SELECT r.clean_set_id, r.rep_index, r.velocity_mps, r.source,
               s.exercise_id, s.session_id
        FROM clean_rep r
        JOIN clean_set s ON s.set_id = r.clean_set_id
        WHERE s.session_id = ?
        ORDER BY r.clean_set_id, r.rep_index
        """,
        (session_id,),
    ).fetchall()
    grouped: dict[int, dict] = {}
    for row in rows:
        item = grouped.setdefault(int(row["clean_set_id"]), {
            "clean_set_id": int(row["clean_set_id"]),
            "exercise_id": row["exercise_id"],
            "source": row["source"],
            "reps": [],
        })
        item["reps"].append({
            "rep_index": int(row["rep_index"]),
            "velocity_mps": float(row["velocity_mps"]),
        })
    sets = []
    for item in grouped.values():
        summary = summarize([rep["velocity_mps"] for rep in item["reps"]])
        sets.append({**item, "summary": summary})
    return {
        "session_id": session_id,
        "available": bool(sets),
        "set_count": len(sets),
        "summary": summarize([
            rep["velocity_mps"]
            for item in sets for rep in item["reps"]
        ]) if sets else None,
        "sets": sets,
        "note": "Descriptive only; not used for autoregulation or prescription.",
    }
