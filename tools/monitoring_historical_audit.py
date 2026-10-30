#!/usr/bin/env python
"""Read-only historical audit for the monitoring implementation plan.

This tool answers what the existing data can support before any monitoring UI exists:

- coverage, missingness and eligibility of raw e1RM observations;
- formula behaviour and simple next-observation baselines;
- measured-test linkage and the current e1RM calibration factors;
- comparability and provenance gaps.

It opens SQLite read-only, never writes to the database, and never fits or changes a
calibration factor. The default report path is private/docs/, because the output can contain
personal training data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strength_coach.domain import rir as rir_mod  # noqa: E402
from strength_coach.features import e1rm_calibration  # noqa: E402
from strength_coach.features import strength_observations as obs  # noqa: E402
from strength_coach.store import queries  # noqa: E402
from strength_coach.utils import exercises, paths  # noqa: E402

DEFAULT_OUT = "private/docs/MONITORING-HISTORICAL-AUDIT.md"
OBSERVATION_WINDOW_DAYS = 84
REP_BUCKETS = ((1, 5), (6, 10), (11, 15), (16, 20))


def connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"database does not exist: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def fingerprint(db_path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(db_path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 3)


def _date(value: Any) -> str:
    if value is None:
        return ""
    try:
        return pd.Timestamp(value).date().isoformat()
    except (TypeError, ValueError):
        return ""


def _days_between(later: str, earlier: str) -> int | None:
    try:
        return (pd.Timestamp(later).date() - pd.Timestamp(earlier).date()).days
    except (TypeError, ValueError):
        return None


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return float((ordered[middle - 1] + ordered[middle]) / 2.0)


def _mean(values: Sequence[float]) -> float | None:
    return None if not values else float(sum(values) / len(values))


def _aggregate_errors(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mae_kg": None, "median_abs_error_kg": None}
    return {
        "n": len(values),
        "mae_kg": _round(_mean(values)),
        "median_abs_error_kg": _round(_median(values)),
    }


def _rep_bucket(reps: int) -> str:
    for low, high in REP_BUCKETS:
        if low <= reps <= high:
            return f"{low}-{high}"
    return "outside_1_20"


def _load_frame(conn: sqlite3.Connection) -> pd.DataFrame:
    frame = queries.clean_sets(conn)
    if frame.empty:
        return frame
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    return out


def _entities() -> dict[str, dict[str, Any]]:
    return {
        str(key): dict(value)
        for key, value in exercises.taxonomy().entities.items()
    }


def _excluded_sets(conn: sqlite3.Connection) -> tuple[dict[int, str], dict[str, int], int]:
    """Set-linked high-intensity exposures, using the stored set_id link only.

    The schema forbids a test exposure from linking directly to a set; a test can still be
    reported separately. Other exposure kinds (max_attempt, competition, unplanned, other)
    can link a set and therefore make that set ineligible for the ordinary series.
    """
    rows = [
        dict(row)
        for row in conn.execute(
            "SELECT set_id, kind FROM high_intensity_exposure WHERE set_id IS NOT NULL"
        )
    ]
    mapping = {
        int(row["set_id"]): str(row["kind"])
        for row in rows
        if row.get("set_id") is not None
    }
    counts = Counter(str(row["kind"]) for row in rows)
    test_exposures = int(
        conn.execute(
            "SELECT count(*) FROM high_intensity_exposure WHERE kind = 'test'"
        ).fetchone()[0]
    )
    return mapping, dict(sorted(counts.items())), test_exposures


def _iter_estimates(
    frame: pd.DataFrame,
    entities: Mapping[str, Mapping[str, Any]],
    excluded_set_kinds: Mapping[int, str] | None = None,
) -> Iterable[tuple[dict[str, Any], obs.RawEstimate | obs.Unavailable]]:
    for row in frame.to_dict("records"):
        exercise_id = str(row.get("exercise_id", "") or "")
        props = dict(entities.get(exercise_id, {}))
        yield row, obs.raw_set_e1rm(
            row,
            props,
            excluded_set_kinds=excluded_set_kinds,
        )


def _session_bests(
    estimates: Sequence[tuple[dict[str, Any], obs.RawEstimate | obs.Unavailable]],
) -> dict[str, list[obs.SessionObservation]]:
    best: dict[tuple[str, str], obs.RawEstimate] = {}
    for _row, result in estimates:
        if not isinstance(result, obs.RawEstimate) or result.quality != obs.QUALITY_OK:
            continue
        key = (result.exercise_id, result.session_id)
        previous = best.get(key)
        if previous is None or (result.kg, result.set_id or -1) > (
            previous.kg,
            previous.set_id or -1,
        ):
            best[key] = result

    grouped: dict[str, list[obs.SessionObservation]] = defaultdict(list)
    for (exercise_id, session_id), estimate in best.items():
        grouped[exercise_id].append(
            obs.SessionObservation(
                exercise_id=exercise_id,
                session_id=session_id,
                occurred_on=estimate.occurred_on,
                estimate=estimate,
            )
        )
    for values in grouped.values():
        values.sort(key=lambda item: (item.occurred_on, item.session_id))
    return dict(grouped)


def _baseline_rows(observations: Sequence[obs.SessionObservation]) -> dict[str, Any]:
    errors: dict[str, list[float]] = {
        "last_session": [],
        "median_3": [],
        "median_5": [],
        "best_84d": [],
    }
    for index, target in enumerate(observations):
        prior = observations[:index]
        if not prior:
            continue
        target_date = pd.Timestamp(target.occurred_on)
        errors["last_session"].append(abs(target.estimate.kg - prior[-1].estimate.kg))

        if len(prior) >= 3:
            value = _median([item.estimate.kg for item in prior[-3:]])
            if value is not None:
                errors["median_3"].append(abs(target.estimate.kg - value))
        if len(prior) >= 5:
            value = _median([item.estimate.kg for item in prior[-5:]])
            if value is not None:
                errors["median_5"].append(abs(target.estimate.kg - value))

        recent = [
            item
            for item in prior
            if (target_date - pd.Timestamp(item.occurred_on)).days <= OBSERVATION_WINDOW_DAYS
        ]
        if recent:
            best = max(item.estimate.kg for item in recent)
            errors["best_84d"].append(abs(target.estimate.kg - best))

    return {
        "n_observations": len(observations),
        "first_on": observations[0].occurred_on if observations else None,
        "last_on": observations[-1].occurred_on if observations else None,
        "baselines": {
            key: _aggregate_errors(values) for key, values in errors.items()
        },
    }


def _calibration_report(conn: sqlite3.Connection, as_of: str) -> dict[str, Any]:
    config = e1rm_calibration.E1RMCalibrationConfig.load()
    rows = e1rm_calibration.build(conn, as_of=as_of, config=config)
    out: list[dict[str, Any]] = []
    for row in rows:
        if not row.points and not row.correction_applied:
            continue
        ratios = [point.ratio for point in row.points]
        factor, low, high, applied, reason = e1rm_calibration._correction(ratios, config)
        leave_one_out: list[dict[str, Any]] = []
        for index, point in enumerate(row.points):
            remaining = ratios[:index] + ratios[index + 1:]
            loo_factor, _loo_low, _loo_high, loo_applied, _loo_reason = (
                e1rm_calibration._correction(remaining, config)
            )
            leave_one_out.append(
                {
                    "removed_on": point.measured_on,
                    "factor": _round(loo_factor),
                    "applied": loo_applied,
                }
            )
        loo_factors = [item["factor"] for item in leave_one_out if item["factor"] is not None]
        loo_applied_changes = sum(
            1 for item in leave_one_out if bool(item["applied"]) != bool(applied)
        )
        out.append(
            {
                "exercise_id": row.exercise_id,
                "points": [
                    {
                        "measured_on": point.measured_on,
                        "measured_kg": _round(point.measured_kg),
                        "predicted_kg": _round(point.predicted_kg),
                        "ratio": _round(point.ratio),
                        "error_kg": _round(point.error_kg),
                    }
                    for point in row.points
                ],
                "point_count": len(row.points),
                "factor": _round(factor),
                "ci_low": _round(low),
                "ci_high": _round(high),
                "ci_width": None if low is None or high is None else _round(high - low),
                "applied": applied,
                "reason": reason,
                "leave_one_out": {
                    "factor_min": _round(min(loo_factors)) if loo_factors else None,
                    "factor_max": _round(max(loo_factors)) if loo_factors else None,
                    "applied_changes": loo_applied_changes,
                    "points": leave_one_out,
                },
                "formula_effective": _round(row.formula_effective),
                "override_effective": _round(row.override_effective),
                "active_source": row.active_source,
            }
        )
    return {
        "config": {
            "apply": bool(config.apply),
            "min_tests": int(config.min_tests),
            "confidence": float(config.confidence),
            "max_correction": float(config.max_correction),
            "bootstrap_samples": int(config.bootstrap_samples),
            "seed": int(config.seed),
        },
        "rows": out,
    }


def _measured_tests(
    conn: sqlite3.Connection,
    observations: Mapping[str, Sequence[obs.SessionObservation]],
    as_of: str,
) -> dict[str, Any]:
    overrides = [
        row
        for row in queries.e1rm_overrides(conn)
        if row.get("source") == "measured" and str(row["effective_from"]) <= as_of
    ]
    exposures = [dict(row) for row in conn.execute("SELECT * FROM high_intensity_exposure")]
    by_source = {
        str(row.get("source_id")): row
        for row in exposures
        if row.get("source_id")
    }
    rows: list[dict[str, Any]] = []
    test_types: Counter[str] = Counter()
    for override in overrides:
        exercise_id = str(override["exercise_id"])
        measured_on = str(override["effective_from"])
        linked = by_source.get(f"e1rm_override:{int(override['override_id'])}")
        test_type = None if linked is None else linked.get("test_type")
        test_types[str(test_type or "unknown")] += 1
        prior = [
            item
            for item in observations.get(exercise_id, [])
            if item.occurred_on < measured_on
            and (_days_between(measured_on, item.occurred_on) or 9999) <= OBSERVATION_WINDOW_DAYS
        ]
        best_prior = max(prior, key=lambda item: item.estimate.kg) if prior else None
        rows.append(
            {
                "override_id": int(override["override_id"]),
                "exercise_id": exercise_id,
                "measured_on": measured_on,
                "measured_kg": _round(float(override["e1rm_kg"])),
                "linked_exposure": linked is not None,
                "test_type": test_type,
                "prior_raw_kg": None if best_prior is None else _round(best_prior.estimate.kg),
                "prior_raw_on": None if best_prior is None else best_prior.occurred_on,
                "prior_gap_days": None if best_prior is None else _days_between(
                    measured_on, best_prior.occurred_on
                ),
                "protocol": "not stored",
                "equipment": "not stored",
            }
        )
    coverage: dict[str, int] = Counter(row["exercise_id"] for row in rows)
    return {
        "recorded": len(overrides),
        "linked": sum(1 for row in rows if row["linked_exposure"]),
        "with_prior_raw": sum(1 for row in rows if row["prior_raw_kg"] is not None),
        "test_types": dict(sorted(test_types.items())),
        "coverage": dict(sorted(coverage.items())),
        "rows": rows,
        "provenance_available": {
            "test_type": True,
            "protocol": False,
            "equipment": False,
            "formula_version": False,
        },
    }


def build_audit(
    conn: sqlite3.Connection,
    *,
    as_of: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build the audit payload. The caller supplies a read-only connection."""
    frame = _load_frame(conn)
    entities = _entities()
    excluded_set_kinds, exposure_counts, test_exposures = _excluded_sets(conn)
    estimates = list(_iter_estimates(frame, entities, excluded_set_kinds))
    observations = _session_bests(estimates)

    status_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    quality_counts: Counter[str] = Counter()
    load_basis: Counter[str] = Counter()
    rir_counts: Counter[str] = Counter()
    flags: Counter[str] = Counter()
    by_exercise: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "sets": 0,
            "working_sets": 0,
            "eligible_ok": 0,
            "eligible_degraded": 0,
            "rejected": 0,
            "rir_missing": 0,
            "rir_warmup": 0,
            "rir_effort": 0,
            "rir_other": 0,
            "rep_ranges": defaultdict(int),
        }
    )
    rep_ranges: dict[str, list[float]] = defaultdict(list)
    rir_estimates: dict[str, list[float]] = defaultdict(list)

    for row, result in estimates:
        exercise_id = str(row.get("exercise_id", "") or "")
        stats = by_exercise[exercise_id]
        stats["sets"] += 1
        if bool(row.get("is_working_set")):
            stats["working_sets"] += 1
        basis = str(row.get("load_basis") or "unknown")
        load_basis[basis] += 1

        rir_reading = rir_mod.classify(row.get("rir"))
        if rir_reading.klass == "missing":
            rir_counts["missing"] += 1
            stats["rir_missing"] += 1
        elif rir_reading.klass == "warmup":
            rir_counts["6_warmup"] += 1
            stats["rir_warmup"] += 1
        elif rir_reading.klass == "effort":
            rir_counts[str(int(rir_reading.value))] += 1
            stats["rir_effort"] += 1
        else:
            rir_counts["other"] += 1
            stats["rir_other"] += 1

        if isinstance(result, obs.RawEstimate):
            status_counts[result.status] += 1
            quality_counts[result.quality] += 1
            stats[f"eligible_{result.quality}"] += 1
            bucket = _rep_bucket(result.reps)
            stats["rep_ranges"][bucket] += 1
            rep_ranges[bucket].append(result.kg)
            rir_estimates[str(result.rir)].append(result.kg)
            for flag in result.flags:
                flags[flag] += 1
        else:
            status_counts[result.status] += 1
            reason_counts[result.reason] += 1
            stats["rejected"] += 1

    session_count = int(frame["session_id"].nunique()) if not frame.empty else 0
    working_count = int(frame["is_working_set"].fillna(False).astype(bool).sum()) if not frame.empty else 0
    warmup_count = int(len(frame) - working_count) if not frame.empty else 0
    warmup_share = (warmup_count / len(frame)) if len(frame) else 0.0
    date_values = frame["date"].dropna() if not frame.empty else pd.Series(dtype="datetime64[ns]")

    by_exercise_rows = []
    for exercise_id in sorted(by_exercise):
        stats = dict(by_exercise[exercise_id])
        stats["exercise_id"] = exercise_id
        stats["rep_ranges"] = dict(sorted(stats["rep_ranges"].items()))
        stats["observations"] = len(observations.get(exercise_id, []))
        by_exercise_rows.append(stats)

    baseline_rows = []
    overall_errors: dict[str, list[float]] = defaultdict(list)
    for exercise_id in sorted(observations):
        row = _baseline_rows(observations[exercise_id])
        row["exercise_id"] = exercise_id
        baseline_rows.append(row)
        for key, value in row["baselines"].items():
            if value["n"]:
                # The aggregate is rebuilt from row values only for a compact summary;
                # per-exercise MAE remains the source of truth.
                overall_errors[key].append(float(value["mae_kg"]))

    formula_values = [
        result.kg
        for _row, result in estimates
        if isinstance(result, obs.RawEstimate) and result.quality == obs.QUALITY_OK
    ]
    formula_quantiles = {}
    if formula_values:
        series = pd.Series(formula_values, dtype="float64")
        formula_quantiles = {
            str(q): _round(float(series.quantile(q)))
            for q in (0.1, 0.25, 0.5, 0.75, 0.9)
        }

    changes: list[dict[str, Any]] = []
    for exercise_id, values in observations.items():
        for previous, current in zip(values, values[1:], strict=False):
            changes.append(
                {
                    "exercise_id": exercise_id,
                    "from_on": previous.occurred_on,
                    "to_on": current.occurred_on,
                    "change_kg": _round(current.estimate.kg - previous.estimate.kg),
                }
            )
    changes.sort(key=lambda item: abs(float(item["change_kg"] or 0.0)), reverse=True)

    measured = _measured_tests(conn, observations, as_of)
    calibration = _calibration_report(conn, as_of)
    calibration["recorded_measured"] = measured["recorded"]
    calibration["eligible_points"] = sum(row["point_count"] for row in calibration["rows"])
    calibration["factors_applied"] = sum(1 for row in calibration["rows"] if row["applied"])

    aliases: dict[str, set[str]] = defaultdict(set)
    for row in frame.to_dict("records"):
        aliases[str(row.get("exercise_id") or "")].add(str(row.get("raw_exercise") or ""))
    pattern_counts: Counter[str] = Counter()
    for exercise_id in sorted(aliases):
        props = entities.get(exercise_id, {})
        pattern_counts[str(props.get("pattern") or "unknown")] += 1

    exercises_with_two = sum(
        1 for exercise_id in observations if len(observations[exercise_id]) >= 2
    )
    exercises_with_five = sum(
        1 for exercise_id in observations if len(observations[exercise_id]) >= 5
    )

    limitations = []
    if measured["recorded"] == 0:
        limitations.append(
            "No measured 1RM/3RM/5RM tests are recorded, so formula-vs-criterion error "
            "and calibration informativeness cannot be evaluated."
        )
    if measured["recorded"] and measured["with_prior_raw"] < measured["recorded"]:
        limitations.append(
            "Some measured tests have no prior raw estimate inside the 84-day window; "
            "their calibration observations are unavailable."
        )
    limitations.append(
        "Measured-test protocol and equipment are not stored, so calibration factors "
        "cannot be interpreted by test method."
    )
    limitations.append(
        "No formula/method version is stored on historical tests; the audit reports the "
        "current formula only."
    )
    if load_basis.get("added"):
        limitations.append(
            "Added-load rows do not expose resolved total body mass in queries.clean_sets; "
            "those raw estimates are treated as unavailable rather than omitting bodyweight."
        )

    return {
        "meta": {
            "as_of": as_of,
            "db_path": None if db_path is None else str(db_path),
            "db_sha256": None if db_path is None else fingerprint(db_path),
            "read_only": True,
            "formula": "Epley/Epley+RIR",
            "calibration_applied_to_raw_series": False,
            "age_decay_applied_to_raw_series": False,
            "window_days": OBSERVATION_WINDOW_DAYS,
        },
        "inventory": {
            "sets": int(len(frame)),
            "sessions": session_count,
            "exercises": int(frame["exercise_id"].nunique()) if not frame.empty else 0,
            "working_sets": working_count,
            "warmup_sets": warmup_count,
            "warmup_share": _round(warmup_share),
            "date_first": _date(date_values.min()) if not date_values.empty else None,
            "date_last": _date(date_values.max()) if not date_values.empty else None,
            "load_basis": dict(sorted(load_basis.items())),
        },
        "eligibility": {
            "status": dict(sorted(status_counts.items())),
            "quality": dict(sorted(quality_counts.items())),
            "reasons": dict(sorted(reason_counts.items())),
            "rir_raw": dict(sorted(rir_counts.items())),
            "rep_ranges": {
                key: {
                    "n": len(values),
                    "median_kg": _round(_median(values)),
                }
                for key, values in sorted(rep_ranges.items())
            },
            "rir_estimates": {
                key: {
                    "n": len(values),
                    "median_kg": _round(_median(values)),
                }
                for key, values in sorted(rir_estimates.items())
            },
            "by_exercise": by_exercise_rows,
            "exclusions": {
                "power_sets": int(reason_counts.get(obs.REASON_POWER, 0)),
                "set_linked_total": len(excluded_set_kinds),
                "set_linked_by_kind": exposure_counts,
                "test_exposures": test_exposures,
                "test_linked_sets": int(exposure_counts.get("test", 0)),
            },
        },
        "observations": {
            "exercises_with_observations": len(observations),
            "exercises_with_two_or_more": exercises_with_two,
            "exercises_with_five_or_more": exercises_with_five,
            "by_exercise": baseline_rows,
        },
        "baselines": {
            "method": "next-observation absolute error; descriptive, not criterion accuracy",
            "mean_of_exercise_mae_by_method": {
                key: _round(_mean(values)) for key, values in sorted(overall_errors.items())
            },
            "by_exercise": baseline_rows,
        },
        "formula": {
            "eligible_ok": len(formula_values),
            "kg_quantiles": formula_quantiles,
            "flags_on_eligible_sets": dict(sorted(flags.items())),
            "largest_one_step_changes": changes[:10],
        },
        "measured_tests": measured,
        "calibration": calibration,
        "comparability": {
            "exercise_identities": len(aliases),
            "pattern_counts": dict(sorted(pattern_counts.items())),
            "raw_name_aliases": {
                key: sorted(value) for key, value in sorted(aliases.items()) if len(value) > 1
            },
            "equipment_available": False,
            "protocol_available": False,
            "note": "Equipment/protocol are not stored; series breaks cannot be attributed.",
        },
        "monitoring": {
            "descriptive_series_possible": exercises_with_two > 0,
            "recommended_exercises": [
                exercise_id
                for exercise_id in sorted(observations)
                if len(observations[exercise_id]) >= 5
            ],
            "ratio_pair_assessment": "requires the Phase 3 relationship configuration",
        },
        "limitations": limitations,
    }


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join("" if value is None else str(value) for value in row) + " |")
    return lines


def render_markdown(report: Mapping[str, Any]) -> str:
    meta = report["meta"]
    inventory = report["inventory"]
    eligibility = report["eligibility"]
    measured = report["measured_tests"]
    calibration = report["calibration"]
    formula = report["formula"]
    baselines = report["baselines"]
    comparability = report["comparability"]
    monitoring = report["monitoring"]

    lines = [
        "# Monitoring historical audit",
        "",
        "Read-only Phase 0 audit. This report is generated outside the repository's tracked",
        "documentation and must not be committed when it contains personal training data.",
        "",
        "## Method",
        "",
        f"- As of: {meta['as_of']}",
        f"- Database: {meta['db_path'] or 'not recorded'}",
        f"- Database SHA-256: {meta['db_sha256'] or 'not recorded'}",
        f"- Formula: {meta['formula']}",
        f"- Calibration applied to raw series: {meta['calibration_applied_to_raw_series']}",
        f"- Age decay applied to raw series: {meta['age_decay_applied_to_raw_series']}",
        f"- Recent-reference window: {meta['window_days']} days",
        "",
        "## Gate summary",
        "",
        f"- Descriptive raw series possible: {monitoring['descriptive_series_possible']}",
        f"- Exercises with at least two eligible session observations: {report['observations']['exercises_with_two_or_more']}",
        f"- Exercises with at least five eligible session observations: {report['observations']['exercises_with_five_or_more']}",
        f"- Measured tests recorded: {measured['recorded']}",
        f"- Measured tests linked to an exposure: {measured['linked']}",
        f"- Measured tests with a prior raw estimate: {measured['with_prior_raw']}",
        f"- Calibration points eligible: {calibration['eligible_points']}",
        f"- Calibration factors applied: {calibration['factors_applied']}",
        "",
        "## 1. Data inventory",
        "",
        f"- Sets: {inventory['sets']}",
        f"- Sessions: {inventory['sessions']}",
        f"- Exercises: {inventory['exercises']}",
        f"- Working sets: {inventory['working_sets']}",
        f"- Warm-up sets: {inventory['warmup_sets']}",
        f"- Warm-up share: {inventory['warmup_share']}",
        f"- Date range: {inventory['date_first']} to {inventory['date_last']}",
        f"- Load basis: {inventory['load_basis']}",
        "",
        "## 2. Eligibility",
        "",
        "Status counts:",
        "",
        *(_table(["status", "count"], sorted(eligibility["status"].items()))),
        "",
        "Quality counts:",
        "",
        *(_table(["quality", "count"], sorted(eligibility["quality"].items()))),
        "",
        "Rejection reasons:",
        "",
        *(_table(["reason", "count"], sorted(eligibility["reasons"].items()))),
        "",
        "Explicit exclusions:",
        "",
        *(_table(
            ["exclusion", "count"],
            [
                ["power-classified sets", eligibility["exclusions"]["power_sets"]],
                ["set-linked high-intensity exposures", eligibility["exclusions"]["set_linked_total"]],
                ["set-linked test exposures", eligibility["exclusions"]["test_linked_sets"]],
                ["all test exposures", eligibility["exclusions"]["test_exposures"]],
            ],
        )),
        "",
        f"Set-linked exposures by kind: {eligibility['exclusions']['set_linked_by_kind']}",
        "",
        "Raw RIR values:",
        "",
        *(_table(["RIR", "count"], sorted(eligibility["rir_raw"].items()))),
        "",
        "Eligible estimates by rep range:",
        "",
        *(_table(
            ["rep range", "n", "median kg"],
            [
                [key, value["n"], value["median_kg"]]
                for key, value in eligibility["rep_ranges"].items()
            ],
        )),
        "",
        "Exercises with the most eligible sessions (top 20):",
        "",
        *(_table(
            ["exercise", "sets", "working", "ok", "degraded", "rejected", "observations"],
            [
                [
                    row["exercise_id"],
                    row["sets"],
                    row["working_sets"],
                    row["eligible_ok"],
                    row["eligible_degraded"],
                    row["rejected"],
                    row["observations"],
                ]
                for row in sorted(
                    eligibility["by_exercise"],
                    key=lambda item: (-item["observations"], item["exercise_id"]),
                )[:20]
            ],
        )),
        "",
        "Eligible set counts by exercise and rep range (top 20 by observations):",
        "",
        *(_table(
            ["exercise", "1-5", "6-10", "11-15", "16-20", "observations"],
            [
                [
                    row["exercise_id"],
                    row["rep_ranges"].get("1-5", 0),
                    row["rep_ranges"].get("6-10", 0),
                    row["rep_ranges"].get("11-15", 0),
                    row["rep_ranges"].get("16-20", 0),
                    row["observations"],
                ]
                for row in sorted(
                    eligibility["by_exercise"],
                    key=lambda item: (-item["observations"], item["exercise_id"]),
                )[:20]
            ],
        )),
        "",
        "RIR coverage by exercise (top 20 by observations):",
        "",
        *(_table(
            ["exercise", "missing", "warm-up (6)", "effort 0-5", "other"],
            [
                [
                    row["exercise_id"],
                    row["rir_missing"],
                    row["rir_warmup"],
                    row["rir_effort"],
                    row["rir_other"],
                ]
                for row in sorted(
                    eligibility["by_exercise"],
                    key=lambda item: (-item["observations"], item["exercise_id"]),
                )[:20]
            ],
        )),
        "",
        "## 3. Measured tests",
        "",
        f"- Recorded: {measured['recorded']}",
        f"- Linked to high-intensity exposure: {measured['linked']}",
        f"- With a prior raw estimate in the 84-day window: {measured['with_prior_raw']}",
        f"- Test types: {measured['test_types']}",
        f"- Provenance: {measured['provenance_available']}",
        "",
    ]
    if measured["rows"]:
        lines.extend(
            _table(
                ["exercise", "measured on", "measured kg", "test type", "prior kg", "prior on", "gap days"],
                [
                    [
                        row["exercise_id"],
                        row["measured_on"],
                        row["measured_kg"],
                        row["test_type"],
                        row["prior_raw_kg"],
                        row["prior_raw_on"],
                        row["prior_gap_days"],
                    ]
                    for row in measured["rows"]
                ],
            )
        )
    else:
        lines.append("No measured tests are recorded. Criterion calibration is not evaluable.")

    lines.extend(
        [
            "",
            "## 4. Existing calibration",
            "",
            f"- Configuration: {calibration['config']}",
            f"- Recorded measured tests: {calibration['recorded_measured']}",
            f"- Eligible calibration points: {calibration['eligible_points']}",
            f"- Factors applied: {calibration['factors_applied']}",
            "",
        ]
    )
    if calibration["rows"]:
        lines.extend(
            _table(
                [
                    "exercise",
                    "points",
                    "factor",
                    "applied",
                    "CI low",
                    "CI high",
                    "CI width",
                    "reason",
                    "LOO applied changes",
                ],
                [
                    [
                        row["exercise_id"],
                        row["point_count"],
                        row["factor"],
                        row["applied"],
                        row["ci_low"],
                        row["ci_high"],
                        row["ci_width"],
                        row["reason"],
                        row["leave_one_out"]["applied_changes"],
                    ]
                    for row in calibration["rows"]
                ],
            )
        )
    else:
        lines.append(
            "No lift has an eligible measured-test calibration point. No factor can be "
            "interpreted or evaluated from the current data."
        )

    lines.extend(
        [
            "",
            "## 5. Formula behaviour",
            "",
            f"- Eligible ok set-level observations: {formula['eligible_ok']}",
            f"- e1RM quantiles (kg): {formula['kg_quantiles']}",
            f"- Flags on eligible sets: {formula['flags_on_eligible_sets']}",
            "",
            "Largest one-step changes (descriptive; not an outlier threshold):",
            "",
            *(_table(
                ["exercise", "from", "to", "change kg"],
                [
                    [row["exercise_id"], row["from_on"], row["to_on"], row["change_kg"]]
                    for row in formula["largest_one_step_changes"]
                ],
            )),
            "",
            "## 6. Simple baselines",
            "",
            "Errors are next-observation absolute errors. They are descriptive stability checks,",
            "not criterion accuracy.",
            "",
            f"- Mean of per-exercise MAE by method: {baselines['mean_of_exercise_mae_by_method']}",
            "",
            *(_table(
                ["exercise", "n", "last MAE", "median3 MAE", "median5 MAE", "best84 MAE"],
                [
                    [
                        row["exercise_id"],
                        row["n_observations"],
                        row["baselines"]["last_session"]["mae_kg"],
                        row["baselines"]["median_3"]["mae_kg"],
                        row["baselines"]["median_5"]["mae_kg"],
                        row["baselines"]["best_84d"]["mae_kg"],
                    ]
                    for row in baselines["by_exercise"]
                ][:40],
            )),
            "",
            "## 7. Comparability",
            "",
            f"- Exercise identities: {comparability['exercise_identities']}",
            f"- Pattern counts: {comparability['pattern_counts']}",
            f"- Equipment available: {comparability['equipment_available']}",
            f"- Protocol available: {comparability['protocol_available']}",
            f"- Note: {comparability['note']}",
            "",
            "## 8. Limitations and recommendations",
            "",
        ]
    )
    for limitation in report["limitations"]:
        lines.append(f"- {limitation}")
    lines.extend(
        [
            "",
            f"- Ratio pairs: {monitoring['ratio_pair_assessment']}",
            "- This audit does not fit, change or apply a calibration factor.",
            "- The raw series excludes age decay and calibration by construction.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(paths.data_dir("coach.db")))
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument(
        "--as-of",
        default=pd.Timestamp.today().date().isoformat(),
        help="YYYY-MM-DD audit date; defaults to today",
    )
    args = parser.parse_args(argv)

    try:
        conn = connect_readonly(args.db)
    except (FileNotFoundError, sqlite3.DatabaseError) as exc:
        print(f"audit error: {exc}", file=sys.stderr)
        return 2

    try:
        report = build_audit(conn, as_of=args.as_of, db_path=args.db)
    except (sqlite3.DatabaseError, ValueError) as exc:
        print(f"audit error: {exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()

    if args.format == "json":
        text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    else:
        text = render_markdown(report) + "\n"

    if args.out == "-":
        sys.stdout.write(text)
        return 0

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
