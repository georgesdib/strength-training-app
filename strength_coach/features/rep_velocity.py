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


# --- cross-session descriptive analysis ---------------------------------------


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    denom = (sum(x * x for x in dx) ** 0.5) * (sum(y * y for y in dy) ** 0.5)
    if denom == 0:
        return None
    return round(sum(x * y for x, y in zip(dx, dy)) / denom, 3)


def _latest_feedback(conn) -> dict[str, float]:
    rows = conn.execute(
        """
        SELECT f.session_id, f.srpe
        FROM session_feedback f
        WHERE f.srpe IS NOT NULL
          AND f.recorded_at = (
              SELECT MAX(g.recorded_at) FROM session_feedback g
              WHERE g.session_id = f.session_id AND g.srpe IS NOT NULL
          )
        """
    ).fetchall()
    return {str(row["session_id"]): float(row["srpe"]) for row in rows}


def _readiness_by_date(conn) -> dict[str, float]:
    rows = conn.execute(
        "SELECT on_date, sleep, energy, mood, soreness, stress, nutrition, hydration "
        "FROM readiness_day"
    ).fetchall()
    out = {}
    for row in rows:
        values = [float(row[key]) for key in (
            "sleep", "energy", "mood", "soreness", "stress", "nutrition", "hydration"
        ) if row[key] is not None]
        if values:
            out[str(row["on_date"])] = round(sum(values) / len(values), 2)
    return out


def _symptom_by_date(conn) -> dict[str, int]:
    rows = conn.execute(
        "SELECT logged_on, level FROM symptom_log ORDER BY logged_on, log_id"
    ).fetchall()
    return {str(row["logged_on"]): int(row["level"]) for row in rows}


def _e1rm(load, reps, rir) -> float | None:
    from strength_coach.domain import e1rm
    estimate = e1rm.estimate_e1rm(
        None if load is None else float(load),
        None if reps is None else int(reps),
        None if rir is None else int(rir),
    )
    return float(estimate.value_kg) if estimate is not None and estimate.is_usable else None


def analysis_report(conn, *, on_date: str | None = None, weeks: int = 12,
                    min_pairs: int = 10) -> dict:
    """Stratified, descriptive report; no rule and no causal claim."""
    import datetime as dt
    end = on_date or dt.date.today().isoformat()
    cutoff = (dt.date.fromisoformat(end) - dt.timedelta(days=weeks * 7)).isoformat()
    rows = conn.execute(
        """
        SELECT r.clean_set_id, r.rep_index, r.velocity_mps, r.source,
               s.session_id, s.occurred_on, s.exercise_id, s.rir, s.load_kg,
               s.reps, s.is_working_set
        FROM clean_rep r
        JOIN clean_set s ON s.set_id = r.clean_set_id
        WHERE s.occurred_on >= ? AND s.occurred_on <= ?
        ORDER BY s.session_id, s.exercise_id, r.clean_set_id, r.rep_index
        """,
        (cutoff, end),
    ).fetchall()
    grouped: dict[int, dict] = {}
    for row in rows:
        item = grouped.setdefault(int(row["clean_set_id"]), {
            "clean_set_id": int(row["clean_set_id"]),
            "session_id": str(row["session_id"]),
            "date": str(row["occurred_on"]),
            "exercise_id": str(row["exercise_id"]),
            "rir": None if row["rir"] is None else int(row["rir"]),
            "rpe": None if row["rir"] is None else round(10 - int(row["rir"]), 1),
            "load_kg": None if row["load_kg"] is None else float(row["load_kg"]),
            "reps": None if row["reps"] is None else int(row["reps"]),
            "is_working_set": bool(row["is_working_set"]),
            "source": str(row["source"]),
            "reps_detail": [],
        })
        item["reps_detail"].append({
            "rep_index": int(row["rep_index"]),
            "velocity_mps": float(row["velocity_mps"]),
        })
    sets = []
    for item in grouped.values():
        summary = summarize([rep["velocity_mps"] for rep in item["reps_detail"]])
        sets.append({**item, "summary": summary})
    sets.sort(key=lambda item: (item["date"], item["session_id"],
                                item["exercise_id"], item["clean_set_id"]))

    # Session/exercise aggregates, used for RPE, readiness and next-session links.
    by_session_exercise: dict[tuple[str, str], list[dict]] = {}
    for item in sets:
        by_session_exercise.setdefault((item["session_id"], item["exercise_id"]), []).append(item)
    aggregate = {}
    for key, items in by_session_exercise.items():
        losses = [item["summary"]["loss_pct"] for item in items
                  if item["is_working_set"] and item["summary"]
                  and item["summary"]["loss_pct"] is not None]
        aggregate[key] = {
            "session_id": key[0],
            "exercise_id": key[1],
            "date": min(item["date"] for item in items),
            "mean_loss_pct": round(sum(losses) / len(losses), 2) if losses else None,
            "set_count": len(items),
        }

    # Best estimated e1RM per session/exercise, used only for the next-session delta.
    all_sets = conn.execute(
        "SELECT session_id, occurred_on, exercise_id, load_kg, reps, rir "
        "FROM clean_set WHERE occurred_on >= ? AND occurred_on <= ? AND is_working_set = 1 "
        "ORDER BY occurred_on",
        (cutoff, end),
    ).fetchall()
    e1rm_by_key: dict[tuple[str, str], float] = {}
    for row in all_sets:
        value = _e1rm(row["load_kg"], row["reps"], row["rir"])
        if value is None:
            continue
        key = (str(row["session_id"]), str(row["exercise_id"]))
        e1rm_by_key[key] = max(value, e1rm_by_key.get(key, 0.0))
    date_by_key = {
        (item["session_id"], item["exercise_id"]): item["date"]
        for item in aggregate.values()
    }
    next_delta = {}
    for (session_id, exercise_id), current in e1rm_by_key.items():
        if (session_id, exercise_id) not in date_by_key:
            continue
        date = date_by_key[(session_id, exercise_id)]
        candidates = [
            (key, value) for key, value in e1rm_by_key.items()
            if key[1] == exercise_id and key[0] != session_id
            and key in date_by_key and date_by_key[key] > date
        ]
        if not candidates:
            continue
        next_key, next_value = min(candidates, key=lambda pair: date_by_key[pair[0]])
        next_date = date_by_key[next_key]
        days = (dt.date.fromisoformat(next_date) - dt.date.fromisoformat(date)).days
        if days <= 14:
            next_delta[(session_id, exercise_id)] = {
                "days": days,
                "next_e1rm_kg": round(next_value, 1),
                "delta_pct": round((next_value - current) / current * 100, 2) if current else None,
            }

    feedback = _latest_feedback(conn)
    readiness = _readiness_by_date(conn)
    symptoms = _symptom_by_date(conn)
    for item in aggregate.values():
        item["srpe"] = feedback.get(item["session_id"])
        item["readiness"] = readiness.get(item["date"])
        item["symptom_level"] = symptoms.get(item["date"])
        item["next"] = next_delta.get((item["session_id"], item["exercise_id"]))
    aggregates = sorted(aggregate.values(), key=lambda item: (item["date"], item["session_id"],
                                                              item["exercise_id"]))

    def corr(x_key: str, y_key: str, rows_in: list[dict], label: str) -> dict:
        pairs = [(row[x_key], row[y_key]) for row in rows_in
                 if row.get(x_key) is not None and row.get(y_key) is not None]
        n = len(pairs)
        r = _pearson([p[0] for p in pairs], [p[1] for p in pairs]) if n >= min_pairs else None
        return {
            "x": x_key, "y": y_key, "n": n, "r": r, "label": label,
            "status": "descriptive" if n >= min_pairs and r is not None
            else "insufficient" if n < min_pairs else "no variance",
        }

    set_rows = [item for item in sets if item["is_working_set"] and item["summary"]]
    correlations = [
        corr("loss_pct", "rir", [
            {"loss_pct": item["summary"]["loss_pct"], "rir": item["rir"]}
            for item in set_rows
        ], "within-set loss vs RIR"),
        corr("loss_pct", "rpe", [
            {"loss_pct": item["summary"]["loss_pct"], "rpe": item["rpe"]}
            for item in set_rows
        ], "within-set loss vs RPE"),
        corr("mean_loss_pct", "srpe", aggregates, "session mean loss vs sRPE"),
        corr("mean_loss_pct", "readiness", aggregates, "session mean loss vs readiness"),
        corr("mean_loss_pct", "symptom_level", aggregates, "session mean loss vs pre-session symptom"),
        corr("mean_loss_pct", "next_delta", [
            {"mean_loss_pct": item["mean_loss_pct"],
             "next_delta": (item["next"] or {}).get("delta_pct")}
            for item in aggregates
        ], "session mean loss vs next same-exercise e1RM change"),
    ]
    return {
        "from": cutoff,
        "to": end,
        "weeks": weeks,
        "min_pairs": min_pairs,
        "available": bool(sets),
        "set_count": len(sets),
        "session_count": len({item["session_id"] for item in sets}),
        "exercise_count": len({item["exercise_id"] for item in sets}),
        "sets": [
            {
                "date": item["date"],
                "session_id": item["session_id"],
                "exercise_id": item["exercise_id"],
                "set_id": item["clean_set_id"],
                "rir": item["rir"],
                "rpe": item["rpe"],
                "load_kg": item["load_kg"],
                "reps": item["reps"],
                "summary": item["summary"],
            }
            for item in sets
        ],
        "sessions": aggregates,
        "correlations": correlations,
        "missing": {
            "srpe": sum(1 for item in aggregates if item["srpe"] is None),
            "readiness": sum(1 for item in aggregates if item["readiness"] is None),
            "symptom": sum(1 for item in aggregates if item["symptom_level"] is None),
            "next_session": sum(1 for item in aggregates if item["next"] is None),
        },
        "note": (
            "Descriptive only; associations are stratified by exercise, require at least "
            f"{min_pairs} pairs, and never change a prescription. No causal or injury claim."
        ),
    }
