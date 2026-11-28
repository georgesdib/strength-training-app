#!/usr/bin/env python
"""Continuous persistence follow-up: does a session's deviation carry to the next?

Implements docs/archive/PERFORMANCE-PERSISTENCE-PLAN.md. It is a NEW question on the same record,
not a re-analysis of Phase 0: Phase 0 closed with verdict stop and that verdict stands.

The question is continuous:

    u(t+1) = a + b*u(t) + days + log1p(n_sets) + time + lift fixed effects

b is the estimand. A positive b means a session's deviation predicts the next session's
deviation on the same lift. The model cannot say WHY; a shared hard week produces the same
persistence as genuine fatigue. Nothing here tests whether cutting volume helps.

Read-only: SQLite mode=ro and PRAGMA query_only=ON; writes only under private/. One look at
the approved gates; no threshold is changed afterwards.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strength_coach.utils import exercises, paths  # noqa: E402
from tools.performance_carryover import (  # noqa: E402
    add_expected_velocity,
    assert_writable,
    connect_readonly,
    fingerprint,
    load_sets,
    prepare,
)

NEXT_DAYS = 14
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261124
DEFAULT_OUT = "private/docs/PERFORMANCE-PERSISTENCE.md"
DEFAULT_JSON = "private/docs/PERFORMANCE-PERSISTENCE.json"

THRESHOLDS: dict[str, Any] = {
    "beta_min": 0.3,
    "min_pairs": 50,
    "min_sessions": 20,
    "min_exercises_with_pairs": 4,
    "min_pairs_per_exercise": 3,
    "min_triplets_p2": 20,
    "next_exposure_days": NEXT_DAYS,
    "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
    "bootstrap_seed": BOOTSTRAP_SEED,
    "model": "u(t+1) ~ u(t) + days + log1p(n_sets) + time + lift FE",
    "decision": "P1 beta >= 0.3 with 95% cluster interval lower bound > 0",
}

LIMITATIONS = (
    "Observational and single-athlete; a shared hard week, poor sleep or a deload produce the "
    "same persistence as genuine fatigue, so causation is not identified.",
    "The expectation is reconstructed leave-one-session-out, not the stored prescription target; "
    "no app workout contributed a stored target in Phase 0 and the same limitation applies.",
    "The record is imported history; safety-modified sessions are only identifiable for "
    "app-generated workouts, so that exclusion is partial.",
    "Lift and time enter as fixed effects and a linear term; a non-linear trend or a change in "
    "training phase is not modelled.",
    "Equipment, technique and device placement are not stored, so a measurement shift cannot be "
    "distinguished from a performance shift.",
    "One look at the approved gates; a null is not retried with a different model.",
)


def _date(value: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _days(first: str, second: str) -> int | None:
    one, two = _date(first), _date(second)
    if one is None or two is None:
        return None
    return (two - one).days


def _time_span_years(origin: dt.date | None, dates: list[str]) -> float | None:
    """Years from the first session to the last, or None when either is missing."""
    if origin is None or not dates:
        return None
    parsed = [day for day in (_date(value) for value in dates) if day is not None]
    if not parsed:
        return None
    return round((max(parsed) - origin).days / 365.25, 2)


def build_session_lifts(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """One row per (session, exercise) with a usable mean residual."""
    subset = frame[frame["u"].notna()]
    lifts: list[dict[str, Any]] = []
    for (session, exercise), group in subset.groupby(["session_id", "exercise_id"], sort=False):
        values = group["u"].to_numpy(dtype="float64")
        lifts.append({
            "session_id": str(session),
            "exercise_id": str(exercise),
            "date": str(group["occurred_on"].iloc[0])[:10],
            "mean_u": float(np.mean(values)),
            "n_sets": int(len(values)),
            "modified": any(value is True for value in group["modified"]),
        })
    lifts.sort(key=lambda row: (row["exercise_id"], row["date"], row["session_id"]))
    return lifts


def build_pairs(lifts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Earliest later exposure on the same exercise within NEXT_DAYS."""
    by_exercise: dict[str, list[dict[str, Any]]] = {}
    for lift in lifts:
        by_exercise.setdefault(lift["exercise_id"], []).append(lift)
    pairs: list[dict[str, Any]] = []
    for exercise, rows in by_exercise.items():
        for index, current in enumerate(rows):
            for following in rows[index + 1:]:
                if following["session_id"] == current["session_id"]:
                    continue
                days = _days(current["date"], following["date"])
                if days is None or days <= 0 or days > NEXT_DAYS:
                    continue
                pairs.append({
                    "exercise_id": exercise,
                    "session_id": current["session_id"],
                    "date": current["date"],
                    "next_date": following["date"],
                    "u_t": current["mean_u"],
                    "u_next": following["mean_u"],
                    "days": days,
                    "n_sets": current["n_sets"],
                    "modified": bool(current["modified"] or following["modified"]),
                })
                break
    return pairs


def build_triplets(lifts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Three consecutive exposures, each gap within NEXT_DAYS, for the P2 model."""
    by_exercise: dict[str, list[dict[str, Any]]] = {}
    for lift in lifts:
        by_exercise.setdefault(lift["exercise_id"], []).append(lift)
    triplets: list[dict[str, Any]] = []
    for exercise, rows in by_exercise.items():
        for index in range(len(rows) - 2):
            first, current, following = rows[index], rows[index + 1], rows[index + 2]
            gap_one = _days(first["date"], current["date"])
            gap_two = _days(current["date"], following["date"])
            if gap_one is None or gap_two is None:
                continue
            if not (0 < gap_one <= NEXT_DAYS and 0 < gap_two <= NEXT_DAYS):
                continue
            triplets.append({
                "exercise_id": exercise,
                "session_id": current["session_id"],
                "date": current["date"],
                "u_prev": first["mean_u"],
                "u_t": current["mean_u"],
                "u_next": following["mean_u"],
                "days": gap_two,
                "n_sets": current["n_sets"],
                "modified": bool(first["modified"] or current["modified"] or following["modified"]),
            })
    return triplets


def assign_lift_levels(
    rows: list[dict[str, Any]], family_of: dict[str, str | None],
) -> list[str]:
    """Exercise at >= 3 pairs, else its vbt_family at >= 3, else 'other'."""
    exercise_counts = Counter(row["exercise_id"] for row in rows)
    family_counts: Counter[str] = Counter()
    for row in rows:
        family = family_of.get(row["exercise_id"])
        if family:
            family_counts[family] += 1
    levels: list[str] = []
    for row in rows:
        exercise = row["exercise_id"]
        if exercise_counts[exercise] >= THRESHOLDS["min_pairs_per_exercise"]:
            levels.append(exercise)
            continue
        family = family_of.get(exercise)
        if family and family_counts[family] >= THRESHOLDS["min_pairs_per_exercise"]:
            levels.append(family)
        else:
            levels.append("other")
    return levels


def _design(
    rows: list[dict[str, Any]],
    *,
    triplets: bool = False,
    log_days: bool = False,
    include_time: bool = True,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    count = len(rows)
    u_t = np.array([row["u_t"] for row in rows], dtype="float64")
    days = np.array([row["days"] for row in rows], dtype="float64")
    day_feature = np.log1p(days) if log_days else days
    n_sets = np.log1p(np.array([row["n_sets"] for row in rows], dtype="float64"))
    columns = [np.ones(count, dtype="float64"), u_t, day_feature, n_sets]
    names = ["intercept", "u_t", "days", "log1p_n_sets"]
    if triplets:
        columns.append(np.array([row["u_prev"] for row in rows], dtype="float64"))
        names.append("u_prev")
    if include_time:
        columns.append(np.array([row["time"] for row in rows], dtype="float64"))
        names.append("time")
    levels = sorted({row["lift_level"] for row in rows})
    for level in levels[1:]:
        columns.append(np.array(
            [1.0 if row["lift_level"] == level else 0.0 for row in rows], dtype="float64"
        ))
        names.append(f"lift_{level}")
    return np.column_stack(columns), np.array(
        [row["u_next"] for row in rows], dtype="float64"
    ), names


def _fit(design: np.ndarray, outcome: np.ndarray) -> np.ndarray | None:
    if len(outcome) < 3:
        return None
    try:
        beta, *_ = np.linalg.lstsq(design, outcome, rcond=None)
    except np.linalg.LinAlgError:
        return None
    return beta


def _iid_interval(design: np.ndarray, outcome: np.ndarray, beta: np.ndarray,
                  index: int) -> tuple[float | None, float | None]:
    residual = outcome - design @ beta
    rank = int(np.linalg.matrix_rank(design))
    dof = len(outcome) - rank
    if dof <= 0:
        return None, None
    variance = float(residual @ residual) / dof
    try:
        covariance = variance * np.linalg.pinv(design.T @ design)
    except np.linalg.LinAlgError:
        return None, None
    standard_error = float(np.sqrt(max(covariance[index, index], 0.0)))
    if not np.isfinite(standard_error):
        return None, None
    delta = 1.959963984540054 * standard_error
    return float(beta[index] - delta), float(beta[index] + delta)


def _cluster_interval(
    rows: list[dict[str, Any]],
    name: str,
    *,
    triplets: bool = False,
    log_days: bool = False,
    include_time: bool = True,
) -> tuple[float | None, float | None]:
    by_session: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_session.setdefault(row["session_id"], []).append(row)
    units = sorted(by_session)
    if not units:
        return None, None
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws: list[float] = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        sample = rng.choice(units, size=len(units), replace=True).tolist()
        resampled = [row for session in sample for row in by_session[session]]
        design, outcome, names = _design(
            resampled, triplets=triplets, log_days=log_days, include_time=include_time
        )
        if name not in names:
            continue
        beta = _fit(design, outcome)
        if beta is None:
            continue
        value = float(beta[names.index(name)])
        if np.isfinite(value):
            draws.append(value)
    if len(draws) < 50:
        return None, None
    array = np.asarray(draws)
    return float(np.percentile(array, 2.5)), float(np.percentile(array, 97.5))


def _model(
    rows: list[dict[str, Any]],
    *,
    triplets: bool = False,
    log_days: bool = False,
    include_time: bool = True,
) -> dict[str, Any] | None:
    if len(rows) < 3:
        return None
    design, outcome, names = _design(
        rows, triplets=triplets, log_days=log_days, include_time=include_time
    )
    beta = _fit(design, outcome)
    if beta is None:
        return None
    index = names.index("u_t")
    low, high = _cluster_interval(
        rows, "u_t", triplets=triplets, log_days=log_days, include_time=include_time
    )
    iid_low, iid_high = _iid_interval(design, outcome, beta, index)
    result: dict[str, Any] = {
        "n": len(rows),
        "beta_u_t": round(float(beta[index]), 4),
        "cluster_ci": {
            "low": None if low is None else round(low, 4),
            "high": None if high is None else round(high, 4),
        },
        "iid_ci": {
            "low": None if iid_low is None else round(iid_low, 4),
            "high": None if iid_high is None else round(iid_high, 4),
        },
        "rank": int(np.linalg.matrix_rank(design)),
        "terms": names,
    }
    if triplets:
        previous = names.index("u_prev")
        result["beta_u_prev"] = round(float(beta[previous]), 4)
    return result


def _gate(report: dict[str, Any]) -> dict[str, Any]:
    coverage = report["coverage"]
    p1 = report["p1"]
    thresholds = THRESHOLDS
    yield_ok = (
        coverage["pairs"] >= thresholds["min_pairs"]
        and coverage["sessions"] >= thresholds["min_sessions"]
        and coverage["exercises_with_pairs"] >= thresholds["min_exercises_with_pairs"]
    )
    beta = None if p1 is None else p1["beta_u_t"]
    low = None if p1 is None else p1["cluster_ci"]["low"]
    p1_ok = beta is not None and beta >= thresholds["beta_min"] and low is not None and low > 0
    met = {"yield": yield_ok, "p1": p1_ok}
    reasons: list[str] = []
    if not yield_ok:
        reasons.append(
            f"yield not met ({coverage['pairs']} pairs, {coverage['sessions']} sessions, "
            f"{coverage['exercises_with_pairs']} exercises with >= 3 pairs)"
        )
        code = "inconclusive"
    elif not p1_ok:
        reasons.append(
            f"P1 not met (beta {beta}, cluster interval lower bound {low})"
        )
        code = "not-confirmed"
    else:
        p2 = report.get("p2")
        if p2 is None:
            code = "carry-over"
            reasons.append("P1 met; P2 not estimable, so carry-over is the label")
        else:
            beta_u_t = p2["beta_u_t"]
            beta_u_prev = p2.get("beta_u_prev")
            if beta_u_t >= 0.1 and beta_u_t > 0:
                code = "carry-over"
                reasons.append("P1 met; the latest deviation survives controlling for the previous level")
            elif beta_u_prev is not None and beta_u_t < 0.1 and beta_u_prev >= 0.3:
                code = "stable-level"
                reasons.append(
                    "P1 met but the latest deviation adds nothing once the previous level is "
                    "controlled: performance persists as a level, not as carry-over"
                )
            else:
                code = "not-confirmed"
                reasons.append(
                    "P1 met but P2 supports neither carry-over of the latest deviation nor a "
                    "stable level; the association is not interpretable"
                )
    return {"code": code, "met": met, "reasons": reasons}


def analyse(db_path: str | Path) -> dict[str, Any]:
    conn = connect_readonly(db_path)
    try:
        raw = load_sets(conn)
    finally:
        conn.close()

    prepared, excluded = prepare(raw)
    expected = add_expected_velocity(prepared)

    lifts = build_session_lifts(expected)
    pairs = build_pairs(lifts)
    triplets = build_triplets(lifts)

    taxonomy = exercises.taxonomy()
    family_of = {
        exercise: (entity.get("vbt_family") or None)
        for exercise, entity in taxonomy.entities.items()
    }
    levels = assign_lift_levels(pairs, family_of) if pairs else []
    for row, level in zip(pairs, levels, strict=True):
        row["lift_level"] = level
    levels = assign_lift_levels(triplets, family_of) if triplets else []
    for row, level in zip(triplets, levels, strict=True):
        row["lift_level"] = level

    origin = min((_date(lift["date"]) for lift in lifts if _date(lift["date"]) is not None),
                 default=None)
    mean_time = 0.0
    if origin is not None:
        times = []
        for row in pairs:
            day = _date(row["date"])
            row["time"] = (day - origin).days / 365.25 if day else 0.0
            times.append(row["time"])
        mean_time = float(np.mean(times)) if times else 0.0
        for row in pairs:
            row["time"] -= mean_time
        for row in triplets:
            day = _date(row["date"])
            row["time"] = ((day - origin).days / 365.25 if day else 0.0) - mean_time

    eligible_pairs = [row for row in pairs if not row["modified"]]
    eligible_triplets = [row for row in triplets if not row["modified"]]

    counts = Counter(row["exercise_id"] for row in eligible_pairs)
    coverage = {
        "sets_read": int(len(raw)),
        "session_lifts": len(lifts),
        "pairs": len(eligible_pairs),
        "excluded_modified_pairs": len(pairs) - len(eligible_pairs),
        "sessions": len({row["session_id"] for row in eligible_pairs}),
        "exercises": len({row["exercise_id"] for row in eligible_pairs}),
        "exercises_with_pairs": sum(
            1 for count in counts.values() if count >= THRESHOLDS["min_pairs_per_exercise"]
        ),
        "triplets": len(eligible_triplets),
        "lift_levels": len({row["lift_level"] for row in eligible_pairs}),
        "time_span_years": _time_span_years(
            origin, [row["date"] for row in eligible_pairs]
        ),
        "exclusions": excluded,
    }

    primary = _model(eligible_pairs)
    second = _model(eligible_triplets, triplets=True) if len(eligible_triplets) >= THRESHOLDS["min_triplets_p2"] else None

    sensitivities: dict[str, Any] = {}
    if eligible_pairs:
        sensitivities["log_days"] = _model(eligible_pairs, log_days=True)
        sensitivities["no_time"] = _model(eligible_pairs, include_time=False)
        short = [row for row in eligible_pairs if row["days"] <= 7]
        sensitivities["within_7_days"] = _model(short) if len(short) >= 10 else None
        ordered = sorted(eligible_pairs, key=lambda row: (row["date"], row["session_id"]))
        midpoint = len(ordered) // 2
        sensitivities["first_half"] = _model(ordered[:midpoint]) if midpoint >= 10 else None
        sensitivities["second_half"] = _model(ordered[midpoint:]) if len(ordered) - midpoint >= 10 else None

    report: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "database": {"path": str(Path(db_path).resolve()), "fingerprint": fingerprint(db_path)},
        "thresholds": THRESHOLDS,
        "coverage": coverage,
        "p1": primary,
        "p2": second,
        "sensitivities": sensitivities,
        "limitations": list(LIMITATIONS),
    }
    report["label"] = _gate(report)
    return report


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join("" if value is None else str(value) for value in row) + " |")
    return "\n".join(lines)


def _ci(interval: dict[str, Any] | None) -> str:
    if not interval or interval.get("low") is None or interval.get("high") is None:
        return "not estimable"
    return f"{interval['low']} to {interval['high']}"


def render_markdown(report: dict[str, Any]) -> str:
    coverage = report["coverage"]
    p1 = report["p1"] or {}
    p2 = report["p2"]
    label = report["label"]
    lines: list[str] = [
        "# PERFORMANCE PERSISTENCE — CONTINUOUS FOLLOW-UP RESULT",
        "",
        f"**Generated:** {report['generated_at']}  ",
        f"**Database:** {report['database']['path']}  ",
        f"**Fingerprint:** {report['database']['fingerprint'][:16]}  ",
        "**Specification:** docs/archive/PERFORMANCE-PERSISTENCE-PLAN.md  ",
        f"**Label:** **{label['code']}**",
        "",
        "> Private analysis output. Contains personal training data. Do not commit.",
        "",
        "## Label",
        "",
        _table(["criterion", "met"], [[name, "yes" if value else "no"] for name, value in label["met"].items()]),
        "",
        *[f"- {reason}" for reason in label["reasons"]],
        "",
        "## Coverage",
        "",
        _table(
            ["item", "value"],
            [
                ["clean sets read", coverage["sets_read"]],
                ["session-lifts", coverage["session_lifts"]],
                ["pairs", coverage["pairs"]],
                ["excluded (known-modified)", coverage["excluded_modified_pairs"]],
                ["distinct current sessions", coverage["sessions"]],
                ["exercises", coverage["exercises"]],
                ["exercises with >= 3 pairs", coverage["exercises_with_pairs"]],
                ["triplets", coverage["triplets"]],
                ["lift levels", coverage["lift_levels"]],
                ["time span (years)", coverage["time_span_years"]],
            ],
        ),
        "",
        "## P1 — continuous persistence",
        "",
        f"beta on u(t): **{p1.get('beta_u_t')}** (cluster 95% CI {_ci(p1.get('cluster_ci'))}; "
        f"iid CI {_ci(p1.get('iid_ci'))}); n = {p1.get('n')}.",
        "",
        "## P2 — controlling for the previous level",
        "",
        (
            "Not estimable (fewer than the minimum triplets)."
            if p2 is None
            else f"beta on u(t): **{p2.get('beta_u_t')}**; beta on u(t-1): "
                 f"**{p2.get('beta_u_prev')}**; n = {p2.get('n')}."
        ),
        "",
        "## Sensitivities",
        "",
        _table(
            ["model", "n", "beta on u(t)", "cluster 95% CI"],
            [
                [name, (value or {}).get("n"), (value or {}).get("beta_u_t"),
                 _ci((value or {}).get("cluster_ci"))]
                for name, value in report["sensitivities"].items()
            ],
        ),
        "",
        "## Thresholds used",
        "",
        _table(["name", "value"], [[name, value] for name, value in report["thresholds"].items()]),
        "",
        "## Limitations",
        "",
        *[f"- {item}" for item in report["limitations"]],
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Continuous performance-persistence follow-up.")
    parser.add_argument("--db", default=str(paths.data_dir("coach.db")))
    parser.add_argument("--out", default=str(paths.repo_root() / DEFAULT_OUT))
    parser.add_argument("--json", default=str(paths.repo_root() / DEFAULT_JSON))
    parser.add_argument("--print-only", action="store_true", help="print the JSON and write nothing")
    parser.add_argument("--force", action="store_true", help="allow an output path outside private/")
    args = parser.parse_args(argv)

    report = analyse(args.db)
    payload = json.dumps(report, indent=2, sort_keys=True)
    print(payload)
    if args.print_only:
        return 0

    for path in (args.out, args.json):
        assert_writable(path, force=args.force)
        Path(path).resolve().parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(render_markdown(report), encoding="utf-8")
    Path(args.json).write_text(payload + "\n", encoding="utf-8")
    print(f"\nwrote {args.out}\nwrote {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
