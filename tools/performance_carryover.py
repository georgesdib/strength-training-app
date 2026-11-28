#!/usr/bin/env python
"""Phase 0 pre-registered analysis: does under-performance carry over?

Implements docs/archive/PERFORMANCE-CARRYOVER-PHASE0.md. It answers one question before any
volume rule is specified:

    does a set below its expected velocity predict a further below-expectation next set
    (H1), and does a poor session predict a poor next session (H2)?

It cannot show that reducing volume helps. The log has one training path and no
counterfactual; the same limitation closed the readiness audit (READINESS-AUDIT F1).
A pass authorises a shadow-rule specification, nothing else.

The tool is read-only. It opens SQLite with mode=ro and PRAGMA query_only=ON, never
writes to the database, and writes its report under private/ by default because the
output can contain personal training data.

Thresholds are echoed into the JSON so a verdict is reproducible and cannot be re-read
against a different rule.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strength_coach.domain import rir as rir_mod  # noqa: E402
from strength_coach.utils import paths, stats  # noqa: E402

K_BAND = 2.0
MIN_RELATIVE_SPREAD = 0.05
MIN_SETS = 12
MIN_SESSIONS = 3
MIN_LOAD_FRACTION = 0.60
MAX_REPS = 8
NEXT_EXPOSURE_DAYS = 14
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261124
DEFAULT_OUT = "private/docs/PERFORMANCE-CARRYOVER-PHASE0.md"
DEFAULT_JSON = "private/docs/PERFORMANCE-CARRYOVER-PHASE0.json"

SET_COLUMNS = (
    "set_id", "raw_id", "session_id", "occurred_on", "exercise_id", "load_kg", "load_basis",
    "reps", "rir", "velocity", "is_working_set", "flags", "plan_json", "plan_modified_json",
)
TARGET_COLUMNS = (
    "set_id", "raw_id", "session_id", "occurred_on", "exercise_id", "load_kg", "load_basis",
    "reps", "rir", "velocity", "is_working_set", "flags", "set_index", "velocity_target",
    "plan_json", "plan_modified_json",
)

# Signed-off thresholds. min_h2_pairs is an implementation guard added so a handful of
# pairs cannot pass H2 on a wide-but-positive interval; it is reported, not hidden.
THRESHOLDS: dict[str, Any] = {
    "band_k": K_BAND,
    "min_session_lifts": 20,
    "min_trigger_sets": 15,
    "min_risk_difference": 0.10,
    "min_next_shift_mad": 0.5,
    "min_agreement": 0.40,
    "min_kappa": 0.10,
    "trigger_rate_low": 0.05,
    "trigger_rate_high": 0.40,
    "min_h2_pairs": 8,
    "next_exposure_days": NEXT_EXPOSURE_DAYS,
    "min_sets": MIN_SETS,
    "min_sessions": MIN_SESSIONS,
    "min_load_fraction": MIN_LOAD_FRACTION,
    "min_relative_spread": MIN_RELATIVE_SPREAD,
    "max_reps": MAX_REPS,
    "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
    "bootstrap_seed": BOOTSTRAP_SEED,
}

LIMITATIONS = (
    "Retrospective and single-athlete; the counterfactual is unobserved, so this cannot "
    "show that cutting volume improves anything.",
    "Expected velocity is reconstructed leave-one-session-out, not the target the "
    "prescription carried at the time; the production stratum uses the stored target.",
    "Set order is insertion order (raw_id/set_id); imported rows carry no set_index.",
    "Safety-modified sessions are only identifiable for app-generated workouts, so the "
    "H2 exclusion is partial.",
    "Velocity coverage is concentrated in the lifts that use a VBT device; H1/H2 do not "
    "generalise to lifts without velocity.",
    "The H1 slope is unadjusted for position or lift and is a descriptive companion, not a "
    "decision criterion.",
    "No app workout contributed a stored velocity target, so the production-target stratum "
    "was empty; H1 and H2 rest on reconstructed expectations from imported history.",
    "Rep-level velocities are not used and remain descriptive only (DEC-VBT-04, DEC-VBT-05).",
)


# --- input -------------------------------------------------------------------


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


def load_sets(conn: sqlite3.Connection) -> pd.DataFrame:
    """Current leaf performed sets with a known session status."""
    rows = conn.execute(
        """
        SELECT cs.set_id, cs.raw_id, cs.session_id, cs.occurred_on, cs.exercise_id, cs.load_kg,
               cs.load_basis, cs.reps, cs.rir, cs.velocity_mps AS velocity,
               cs.is_working_set, cs.flags,
               w.plan_json, w.plan_modified_json
        FROM clean_set cs
        LEFT JOIN workout_session w ON w.workout_id = cs.session_id
        LEFT JOIN session s ON s.session_id = cs.session_id
        WHERE cs.voided = 0
          AND COALESCE(s.voided, 0) = 0
          AND NOT EXISTS (SELECT 1 FROM clean_set child WHERE child.supersedes_id = cs.set_id)
        ORDER BY cs.session_id, cs.exercise_id, cs.raw_id, cs.set_id
        """
    ).fetchall()
    return pd.DataFrame([dict(row) for row in rows], columns=SET_COLUMNS)


def load_stored_targets(conn: sqlite3.Connection) -> pd.DataFrame:
    """App workouts with the velocity target the prescription actually carried."""
    rows = conn.execute(
        """
        SELECT ws.set_id AS set_id, ws.set_id AS raw_id,
               ws.workout_id AS session_id, w.for_date AS occurred_on,
               ws.exercise_id, ws.load_kg, ws.reps, ws.rir, ws.velocity,
               1 AS is_working_set, '[]' AS flags,
               ws.set_index AS set_index, pi.velocity_target,
               pi.load_basis AS load_basis,
               w.plan_json, w.plan_modified_json
        FROM workout_set ws
        JOIN workout_session w ON w.workout_id = ws.workout_id
        JOIN prescription_item pi
          ON pi.prescription_id = w.prescription_id
         AND pi.order_index = ws.prescription_item_index
        WHERE w.status = 'completed'
          AND ws.velocity IS NOT NULL AND ws.velocity > 0
          AND pi.velocity_target IS NOT NULL
        ORDER BY ws.workout_id, ws.exercise_id, ws.set_index
        """
    ).fetchall()
    return pd.DataFrame([dict(row) for row in rows], columns=TARGET_COLUMNS)


# --- preparation -------------------------------------------------------------


def _flags(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    if value is None:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return [str(value)]
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _absent(value: Any) -> bool:
    """SQL NULL arrives as None or NaN; both mean 'not recorded'."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return str(value).strip() in {"", "null", "None"}


def _modified(plan_json: Any, plan_modified_json: Any) -> bool | None:
    """True/False when the session is identifiable, None for imported history."""
    if not _absent(plan_modified_json):
        return True
    if _absent(plan_json):
        return None
    try:
        data = json.loads(plan_json)
    except (TypeError, ValueError):
        return None
    level = str(data.get("fallback_level") or "full")
    return level != "full"


def _constant_load(loads: Any) -> bool:
    """A (session, exercise) group whose working-set loads are effectively identical."""
    values = pd.to_numeric(pd.Series(loads), errors="coerce").to_numpy(dtype="float64")
    values = values[np.isfinite(values)]
    if values.size <= 1:
        return True
    tolerance = max(0.5, 0.01 * float(np.median(values)))
    return bool(np.max(values) - np.min(values) <= tolerance)


def _e1rm(load: float | None, reps: int | None, rir: int | None) -> float | None:
    if load is None or reps is None or rir is None:
        return None
    if not np.isfinite(load) or load <= 0:
        return None
    return float(load) * (1.0 + (int(reps) + int(rir)) / 30.0)


def prepare(frame: pd.DataFrame, *, require_stored_target: bool = False) -> tuple[pd.DataFrame, dict[str, int]]:
    """Apply the eligibility rules and add position, e1RM and the RIR window.

    Returns the surviving rows and an ordered exclusion count, each relative to the rows
    still present at that step (mirroring the calibration's own reporting).
    """
    excluded: dict[str, int] = {}
    if frame.empty:
        empty = frame.copy()
        for name, dtype in (
            ("position", "int64"), ("rir_value", "int64"), ("rir_class", "object"),
            ("rir_low", "int64"), ("rir_high", "int64"), ("in_window", "bool"),
            ("e1rm", "float64"), ("modified", "object"), ("constant_load", "bool"),
        ):
            empty[name] = pd.Series(dtype=dtype)
        return empty, excluded

    out = frame.copy()
    out["load_kg"] = pd.to_numeric(out["load_kg"], errors="coerce")

    def drop(mask: pd.Series, reason: str) -> None:
        nonlocal out
        excluded[reason] = int(mask.sum())
        out = out[~mask].copy()

    drop(~out["is_working_set"].fillna(0).astype(int).eq(1), "not_working_set")

    # Position and the constant-load group are fixed on ALL working sets, before any
    # velocity or effort filter: a gap must not compress the sequence, and a back-off set
    # that happens to lack velocity still marks the group as mixed-load.
    if "set_index" in out.columns and out["set_index"].notna().all():
        out = out.sort_values(["session_id", "exercise_id", "set_index"], kind="mergesort")
    else:
        out = out.sort_values(
            ["session_id", "exercise_id", "raw_id", "set_id"], kind="mergesort"
        )
    out["position"] = out.groupby(["session_id", "exercise_id"]).cumcount() + 1
    out["constant_load"] = False
    for _key, group in out.groupby(["session_id", "exercise_id"], sort=False):
        out.loc[group.index, "constant_load"] = _constant_load(group["load_kg"])

    drop(
        out["velocity"].isna()
        | (pd.to_numeric(out["velocity"], errors="coerce") <= 0),
        "no_velocity",
    )

    readings = [rir_mod.classify(value) for value in out["rir"]]
    out["rir_value"] = [reading.value for reading in readings]
    out["rir_class"] = [reading.klass for reading in readings]
    drop(out["rir_class"].ne("effort"), "no_effort_rating")

    out["reps"] = pd.to_numeric(out["reps"], errors="coerce")
    drop(~out["reps"].between(1, MAX_REPS), "reps_out_of_range")
    drop(out["load_basis"].eq("unknown") | out["load_basis"].isna(), "load_basis_unknown")
    drop(out["flags"].map(lambda value: "REPS_TYPO" in _flags(value)), "reps_typo")

    out["load_kg"] = pd.to_numeric(out["load_kg"], errors="coerce")
    out["e1rm"] = [
        _e1rm(load, reps, rir)
        for load, reps, rir in zip(out["load_kg"], out["reps"], out["rir_value"], strict=True)
    ]
    out["e1rm"] = pd.to_numeric(out["e1rm"], errors="coerce")
    if out["e1rm"].notna().any():
        best = out.groupby("exercise_id")["e1rm"].transform("max")
        too_light = out["e1rm"].notna() & (out["e1rm"] < best * MIN_LOAD_FRACTION)
    else:
        too_light = pd.Series(False, index=out.index)
    drop(too_light, "load_too_light")

    if require_stored_target:
        drop(out["velocity_target"].isna(), "no_stored_target")

    out["reps"] = out["reps"].astype(int)
    out["rir_value"] = out["rir_value"].astype(int)

    windows = [rir_mod.target_for(str(exercise)) for exercise in out["exercise_id"]]
    out["rir_low"] = [window[0] for window in windows]
    out["rir_high"] = [window[1] for window in windows]
    out["in_window"] = [
        low <= value <= high
        for value, low, high in zip(out["rir_value"], out["rir_low"], out["rir_high"], strict=True)
    ]

    out["modified"] = [
        _modified(plan, modified)
        for plan, modified in zip(
            out.get("plan_json", pd.Series([None] * len(out), index=out.index)),
            out.get("plan_modified_json", pd.Series([None] * len(out), index=out.index)),
            strict=True,
        )
    ]
    return out.reset_index(drop=True), excluded


def add_expected_velocity(frame: pd.DataFrame) -> pd.DataFrame:
    """Leave-one-session-out lift-scoped expectation, mirroring the calibration ladder."""
    out = frame.copy()
    out["centre"] = np.nan
    out["spread"] = np.nan
    if out.empty:
        out["u"] = np.nan
        return out
    calibration = out[out["in_window"]]
    for (exercise, reps), group in calibration.groupby(["exercise_id", "reps"], sort=False):
        sessions = group["session_id"].unique()
        if len(group) < MIN_SETS or len(sessions) < MIN_SESSIONS:
            continue
        for session in sessions:
            complement = group[group["session_id"] != session]
            if len(complement) < MIN_SETS or complement["session_id"].nunique() < MIN_SESSIONS:
                continue
            centre = stats.median(complement["velocity"])
            spread = stats.mad(complement["velocity"])
            if not np.isfinite(centre):
                continue
            spread = max(float(spread) if np.isfinite(spread) else 0.0,
                         abs(centre) * MIN_RELATIVE_SPREAD)
            if spread <= 0:
                continue
            mask = (
                (out["exercise_id"] == exercise)
                & (out["reps"] == reps)
                & (out["session_id"] == session)
            )
            out.loc[mask, "centre"] = centre
            out.loc[mask, "spread"] = spread
    out["u"] = (pd.to_numeric(out["velocity"], errors="coerce") - out["centre"]) / out["spread"]
    return out


def add_stored_target_u(frame: pd.DataFrame, expected: pd.DataFrame) -> pd.DataFrame:
    """Production-like comparison: stored target as centre, reconstructed spread for scale."""
    out = frame.copy()
    spread_map = (
        expected.dropna(subset=["spread"])
        .groupby(["exercise_id", "reps"])["spread"]
        .median()
        .to_dict()
    )
    out["spread"] = [
        spread_map.get((exercise, reps))
        for exercise, reps in zip(out["exercise_id"], out["reps"], strict=True)
    ]
    out["u"] = (
        pd.to_numeric(out["velocity"], errors="coerce")
        - pd.to_numeric(out["velocity_target"], errors="coerce")
    ) / out["spread"]
    return out


def mark_constant_load(frame: pd.DataFrame) -> pd.DataFrame:
    """Flag (session, exercise) groups whose working-set loads are effectively identical."""
    out = frame.copy()
    out["constant_load"] = False
    if out.empty:
        return out
    for _key, group in out.groupby(["session_id", "exercise_id"], sort=False):
        out.loc[group.index, "constant_load"] = _constant_load(group["load_kg"])
    return out


def verdict_of(value: float | None) -> str:
    if value is None or not np.isfinite(value):
        return "missing"
    if value < -K_BAND:
        return "below"
    if value > K_BAND:
        return "above"
    return "expected"


# --- analysis ----------------------------------------------------------------


def make_pairs(frame: pd.DataFrame, *, constant_load_only: bool = True,
               in_window_only: bool = True) -> list[dict[str, Any]]:
    subset = frame[frame["u"].notna()]
    if in_window_only:
        subset = subset[subset["in_window"]]
    if constant_load_only:
        subset = subset[subset["constant_load"]]
    pairs: list[dict[str, Any]] = []
    for (session, exercise), group in subset.groupby(["session_id", "exercise_id"], sort=False):
        items = group.sort_values("position").to_dict("records")
        for previous, following in zip(items, items[1:], strict=False):
            pairs.append({
                "session_id": str(session),
                "exercise_id": str(exercise),
                "u_previous": float(previous["u"]),
                "u_next": float(following["u"]),
                "position_previous": int(previous["position"]),
                "position_next": int(following["position"]),
                "gap": int(following["position"]) - int(previous["position"]),
                "trigger": bool(previous["u"] < -K_BAND),
                "next_below": bool(following["u"] < -K_BAND),
                "previous_verdict": verdict_of(float(previous["u"])),
                "next_verdict": verdict_of(float(following["u"])),
            })
    return pairs


def _stratum(position: int) -> str:
    return "2-3" if position <= 3 else "4+"


def _weighted_risk_difference(rows: list[dict[str, Any]]) -> float | None:
    total = 0
    weighted = 0.0
    for stratum in ("2-3", "4+"):
        cells = [row for row in rows if row["stratum"] == stratum]
        triggers = [row for row in cells if row["trigger"]]
        controls = [row for row in cells if not row["trigger"]]
        if not triggers or not controls:
            continue
        difference = (
            sum(1 for row in triggers if row["next_below"]) / len(triggers)
            - sum(1 for row in controls if row["next_below"]) / len(controls)
        )
        weighted += difference * len(cells)
        total += len(cells)
    return weighted / total if total else None


def _mh_odds_ratio(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Position-stratified Mantel-Haenszel OR with the Robins-Breslow-Greenland variance."""
    numerator = 0.0
    denominator = 0.0
    variance = 0.0
    corrected = False
    for stratum in ("2-3", "4+"):
        cells = [row for row in rows if row["stratum"] == stratum]
        if not cells:
            continue
        a = sum(1 for row in cells if row["trigger"] and row["next_below"])
        b = sum(1 for row in cells if row["trigger"] and not row["next_below"])
        c = sum(1 for row in cells if not row["trigger"] and row["next_below"])
        d = sum(1 for row in cells if not row["trigger"] and not row["next_below"])
        if min(a, b, c, d) == 0:
            a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
            corrected = True
        n = a + b + c + d
        if n <= 1:
            continue
        numerator += a * d / n
        denominator += b * c / n
        variance += (a + b) * (c + d) * (a + c) * (b + d) / (n * n * (n - 1))
    if denominator <= 0 or numerator <= 0:
        return None
    estimate = numerator / denominator
    log_variance = variance / (numerator * numerator)
    if not np.isfinite(log_variance) or log_variance <= 0:
        low = high = None
    else:
        delta = 1.959963984540054 * math.sqrt(log_variance)
        low, high = math.exp(math.log(estimate) - delta), math.exp(math.log(estimate) + delta)
    return {
        "estimate": round(estimate, 3),
        "low": None if low is None else round(low, 3),
        "high": None if high is None else round(high, 3),
        "continuity_corrected": corrected,
    }


def _bootstrap(
    units: list[str],
    statistic: Callable[[list[str]], float | None],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
) -> dict[str, Any] | None:
    if not units:
        return None
    unique = sorted(set(units))
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws: list[float] = []
    for _ in range(resamples):
        sample = rng.choice(unique, size=len(unique), replace=True).tolist()
        value = statistic(sample)
        if value is not None and np.isfinite(value):
            draws.append(float(value))
    if len(draws) < max(50, resamples // 10):
        return None
    array = np.asarray(draws)
    return {
        "low": round(float(np.percentile(array, 2.5)), 4),
        "high": round(float(np.percentile(array, 97.5)), 4),
        "resamples": len(draws),
    }


def _ols(x: np.ndarray, y: np.ndarray) -> np.ndarray | None:
    if len(y) < 3:
        return None
    design = np.column_stack([np.ones(len(x)), x])
    try:
        beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    except np.linalg.LinAlgError:
        return None
    return beta


def analyse_h1(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    for row in pairs:
        row["stratum"] = _stratum(row["position_next"])
    table = Counter((row["previous_verdict"], row["next_verdict"]) for row in pairs)
    per_stratum: list[dict[str, Any]] = []
    for stratum in ("2-3", "4+"):
        cells = [row for row in pairs if row["stratum"] == stratum]
        triggers = [row for row in cells if row["trigger"]]
        controls = [row for row in cells if not row["trigger"]]
        per_stratum.append({
            "stratum": stratum,
            "pairs": len(cells),
            "triggers": len(triggers),
            "controls": len(controls),
            "p_next_below_trigger": (
                round(sum(1 for row in triggers if row["next_below"]) / len(triggers), 4)
                if triggers else None
            ),
            "p_next_below_control": (
                round(sum(1 for row in controls if row["next_below"]) / len(controls), 4)
                if controls else None
            ),
        })

    point = _weighted_risk_difference(pairs)
    by_session: dict[str, list[dict[str, Any]]] = {}
    for row in pairs:
        by_session.setdefault(row["session_id"], []).append(row)
    interval = _bootstrap(
        list(by_session),
        lambda sample: _weighted_risk_difference(
            [row for session in sample for row in by_session[session]]
        ),
    )

    slope = None
    if len(pairs) >= 3:
        beta = _ols(
            np.array([row["u_previous"] for row in pairs], dtype="float64"),
            np.array([row["u_next"] for row in pairs], dtype="float64"),
        )
        if beta is not None:
            def _slope(sample: list[str]) -> float | None:
                rows = [row for session in sample for row in by_session[session]]
                if len(rows) < 3:
                    return None
                fit = _ols(
                    np.array([row["u_previous"] for row in rows], dtype="float64"),
                    np.array([row["u_next"] for row in rows], dtype="float64"),
                )
                return None if fit is None else float(fit[1])

            slope = {
                "estimate": round(float(beta[1]), 3),
                "ci": _bootstrap(list(by_session), _slope),
            }

    return {
        "pairs": len(pairs),
        "triggers": sum(1 for row in pairs if row["trigger"]),
        "crosstab": [
            {"previous": previous, "next": following, "n": count}
            for (previous, following), count in sorted(table.items())
        ],
        "risk_difference": {"estimate": None if point is None else round(point, 4), "ci": interval},
        "odds_ratio": _mh_odds_ratio(pairs),
        "slope": slope,
        "by_stratum": per_stratum,
    }


def analyse_h2(frame: pd.DataFrame) -> dict[str, Any]:
    subset = frame[frame["u"].notna()]
    session_lifts: list[dict[str, Any]] = []
    for (session, exercise), group in subset.groupby(["session_id", "exercise_id"], sort=False):
        values = group["u"].to_numpy(dtype="float64")
        session_lifts.append({
            "session_id": str(session),
            "exercise_id": str(exercise),
            "date": str(group["occurred_on"].iloc[0])[:10],
            "mean_u": float(np.mean(values)),
            "n_sets": int(len(values)),
            "trigger": bool(np.any(values < -K_BAND)),
            "modified": any(value is True for value in group["modified"]),
        })
    session_lifts.sort(key=lambda row: (row["exercise_id"], row["date"], row["session_id"]))

    pairs: list[dict[str, Any]] = []
    by_exercise: dict[str, list[dict[str, Any]]] = {}
    for row in session_lifts:
        by_exercise.setdefault(row["exercise_id"], []).append(row)
    for exercise, rows in by_exercise.items():
        for index, current in enumerate(rows):
            for following in rows[index + 1:]:
                if following["session_id"] == current["session_id"]:
                    continue
                days = _days_between(current["date"], following["date"])
                if days is None or days <= 0 or days > NEXT_EXPOSURE_DAYS:
                    continue
                pairs.append({
                    "exercise_id": exercise,
                    "session_id": current["session_id"],
                    "trigger": current["trigger"],
                    "current_mean_u": current["mean_u"],
                    "next_mean_u": following["mean_u"],
                    "days": days,
                    "n_sets": current["n_sets"],
                    "next_n_sets": following["n_sets"],
                    "modified": bool(current["modified"] or following["modified"]),
                })
                break

    eligible = [row for row in pairs if not row["modified"]]
    triggers = [row for row in eligible if row["trigger"]]
    controls = [row for row in eligible if not row["trigger"]]
    difference = None
    if triggers and controls:
        difference = float(
            np.mean([row["next_mean_u"] for row in triggers])
            - np.mean([row["next_mean_u"] for row in controls])
        )
    by_session: dict[str, list[dict[str, Any]]] = {}
    for row in eligible:
        by_session.setdefault(row["session_id"], []).append(row)

    def _difference(sample: list[str]) -> float | None:
        rows = [row for session in sample for row in by_session[session]]
        triggered = [row for row in rows if row["trigger"]]
        controlled = [row for row in rows if not row["trigger"]]
        if not triggered or not controlled:
            return None
        return float(
            np.mean([row["next_mean_u"] for row in triggered])
            - np.mean([row["next_mean_u"] for row in controlled])
        )

    interval = _bootstrap(list(by_session), _difference)
    return {
        "session_lifts": len(session_lifts),
        "trigger_session_lifts": sum(1 for row in session_lifts if row["trigger"]),
        "pairs": len(eligible),
        "excluded_modified_pairs": len(pairs) - len(eligible),
        "trigger_pairs": len(triggers),
        "control_pairs": len(controls),
        "difference_mad": None if difference is None else round(difference, 4),
        "ci": interval,
        "raw": {
            "trigger_next_mean_u": (
                round(float(np.mean([row["next_mean_u"] for row in triggers])), 4) if triggers else None
            ),
            "control_next_mean_u": (
                round(float(np.mean([row["next_mean_u"] for row in controls])), 4) if controls else None
            ),
        },
    }


def analyse_h3(frame: pd.DataFrame) -> dict[str, Any]:
    subset = frame[frame["u"].notna()].copy()
    subset["rir_verdict"] = [
        "harder" if value < low else "easier" if value > high else "inside"
        for value, low, high in zip(subset["rir_value"], subset["rir_low"], subset["rir_high"], strict=True)
    ]
    subset["velocity_verdict"] = subset["u"].map(verdict_of)
    mapping = {"harder": "below", "easier": "above", "inside": "expected"}
    subset["rir_as_velocity"] = subset["rir_verdict"].map(mapping)
    subset = subset[subset["velocity_verdict"].isin({"below", "expected", "above"})]
    n = len(subset)
    if n == 0:
        return {"sets": 0, "agreement": None, "kappa": None, "table": [], "note": "no dual-channel sets"}
    agree = int((subset["rir_as_velocity"] == subset["velocity_verdict"]).sum())
    categories = ("below", "expected", "above")
    counts = Counter(zip(subset["rir_as_velocity"], subset["velocity_verdict"], strict=True))
    observed = agree / n
    expected = sum(
        (sum(1 for row in subset["rir_as_velocity"] if row == category) / n)
        * (sum(1 for row in subset["velocity_verdict"] if row == category) / n)
        for category in categories
    )
    kappa = None if expected >= 1.0 else (observed - expected) / (1.0 - expected)
    return {
        "sets": n,
        "agreement": round(observed, 4),
        "kappa": None if kappa is None else round(kappa, 4),
        "table": [
            {"rir_direction": left, "velocity_verdict": right, "n": count}
            for (left, right), count in sorted(counts.items())
        ],
        "note": "RIR inside/below/above its lift window mapped to expected/below/above velocity",
    }


def _days_between(first: str, second: str) -> int | None:
    import datetime as dt
    try:
        one = dt.date.fromisoformat(str(first)[:10])
        two = dt.date.fromisoformat(str(second)[:10])
    except (TypeError, ValueError):
        return None
    return (two - one).days


# --- verdict -----------------------------------------------------------------


def decide(report: dict[str, Any]) -> dict[str, Any]:
    thresholds = THRESHOLDS
    coverage = report["coverage"]
    h1 = report["h1"]
    h2 = report["h2"]
    h3 = report["h3"]

    yield_ok = (
        coverage["session_lifts"] >= thresholds["min_session_lifts"]
        and coverage["trigger_sets"] >= thresholds["min_trigger_sets"]
    )
    rd = h1["risk_difference"]["estimate"]
    rd_low = (h1["risk_difference"]["ci"] or {}).get("low")
    h1_rd_ok = rd is not None and rd >= thresholds["min_risk_difference"] and (rd_low is None or rd_low > 0)
    odds = h1["odds_ratio"]
    # A zero-cell stratum makes the OR not estimable; the risk difference remains primary,
    # so criterion 3 is then carried by criterion 2 (recorded in the specification).
    h1_or_ok = (odds is None and h1_rd_ok) or (
        odds is not None
        and odds["estimate"] > 1
        and (odds["low"] is None or odds["low"] > 1)
    )
    # Worse performance is a LOWER u, so persistence is a negative difference whose
    # interval lies entirely below zero.
    h2_ok = (
        h2["pairs"] >= thresholds["min_h2_pairs"]
        and h2["difference_mad"] is not None
        and h2["difference_mad"] <= -thresholds["min_next_shift_mad"]
        and h2["ci"] is not None
        and h2["ci"]["high"] < 0
    )
    h3_ok = (
        h3["agreement"] is not None
        and h3["agreement"] >= thresholds["min_agreement"]
        and h3["kappa"] is not None
        and h3["kappa"] >= thresholds["min_kappa"]
    )
    rate = coverage["trigger_rate"]
    trigger_ok = rate is not None and thresholds["trigger_rate_low"] <= rate <= thresholds["trigger_rate_high"]

    met = {
        "yield": yield_ok,
        "h1_risk_difference": h1_rd_ok,
        "h1_odds_ratio": h1_or_ok,
        "h2_persistence": h2_ok,
        "h3_agreement": h3_ok,
        "trigger_rate": trigger_ok,
    }
    reasons: list[str] = []
    if not yield_ok:
        reasons.append(
            f"yield gate not met ({coverage['session_lifts']} session-lifts, "
            f"{thresholds['min_session_lifts']} needed; {coverage['trigger_sets']} trigger sets, "
            f"{thresholds['min_trigger_sets']} needed)"
        )
        code = "inconclusive"
    elif not h3_ok:
        reasons.append("H3: RIR and velocity do not agree often enough for a corroborated rule")
        code = "stop"
    elif h1_rd_ok and h1_or_ok and h2_ok and trigger_ok:
        code = "pass"
        reasons.append("all pre-registered criteria met")
    elif h1_rd_ok and h1_or_ok and trigger_ok:
        code = "narrow"
        reasons.append("H1 met but H2 did not: current-session advisory only")
    else:
        code = "stop"
        reasons.append("H1 did not show carry-over beyond position")
    if h2["pairs"] < thresholds["min_h2_pairs"]:
        reasons.append(f"H2 underpowered ({h2['pairs']} pairs, {thresholds['min_h2_pairs']} needed)")
    if h1.get("pairs", 0) < 30 or h1.get("triggers", 0) < 5:
        reasons.append(
            f"H1 is underpowered ({h1.get('pairs', 0)} pairs, {h1.get('triggers', 0)} trigger pairs): "
            "no evidence of carry-over, not evidence of absence"
        )
    return {"code": code, "met": met, "reasons": reasons}


# --- rendering ---------------------------------------------------------------


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join("" if value is None else str(value) for value in row) + " |")
    return "\n".join(lines)


def _ci(low: Any, high: Any = None) -> str:
    if high is None:
        return "not estimable"
    return f"{low} to {high}"


def render_markdown(report: dict[str, Any]) -> str:
    coverage = report["coverage"]
    h1 = report["h1"]
    h2 = report["h2"]
    h3 = report["h3"]
    verdict = report["verdict"]
    odds = h1["odds_ratio"] or {}
    slope = h1["slope"] or {}
    lines: list[str] = [
        "# PERFORMANCE CARRY-OVER — PHASE 0 RESULT",
        "",
        f"**Generated:** {report['generated_at']}  ",
        f"**Database:** {report['database']['path']}  ",
        f"**Fingerprint:** {report['database']['fingerprint'][:16]}  ",
        "**Specification:** docs/archive/PERFORMANCE-CARRYOVER-PHASE0.md  ",
        f"**Verdict:** **{verdict['code']}**",
        "",
        "> Private analysis output. Contains personal training data. Do not commit.",
        "",
        "## Verdict",
        "",
        _table(["criterion", "met"], [[name, "yes" if value else "no"] for name, value in verdict["met"].items()]),
        "",
        *[f"- {reason}" for reason in verdict["reasons"]],
        "",
        "## Coverage",
        "",
        _table(
            ["item", "value"],
            [
                ["clean sets read", coverage["sets_read"]],
                ["eligible sets", coverage["eligible_sets"]],
                ["sets with an expectation", coverage["with_expectation"]],
                ["session-lifts", coverage["session_lifts"]],
                ["trigger sets (u < -2)", coverage["trigger_sets"]],
                ["trigger rate", coverage["trigger_rate"]],
                ["constant-load session-lifts", coverage["constant_load_session_lifts"]],
                ["stored-target sets", coverage["stored_target_sets"]],
            ],
        ),
        "",
        "**Exclusions (each relative to the rows still present):**",
        "",
        _table(["reason", "n"], [[reason, count] for reason, count in coverage["exclusions"].items()]),
        "",
        "## H1 — within-session carry-over",
        "",
        f"Pairs: **{h1['pairs']}**; trigger pairs: **{h1['triggers']}**.",
        "",
        _table(
            ["previous verdict", "next verdict", "n"],
            [[row["previous"], row["next"], row["n"]] for row in h1["crosstab"]],
        ),
        "",
        _table(
            ["stratum", "pairs", "triggers", "controls", "P(next below | trigger)", "P(next below | control)"],
            [
                [
                    row["stratum"], row["pairs"], row["triggers"], row["controls"],
                    row["p_next_below_trigger"], row["p_next_below_control"],
                ]
                for row in h1["by_stratum"]
            ],
        ),
        "",
        f"Risk difference: **{h1['risk_difference']['estimate']}** "
        f"(95% CI {_ci((h1['risk_difference']['ci'] or {}).get('low'), (h1['risk_difference']['ci'] or {}).get('high'))})",
        "",
        f"Mantel-Haenszel OR: **{odds.get('estimate')}** "
        f"(95% CI {_ci(odds.get('low'), odds.get('high'))})"
        + (" — continuity-corrected" if odds.get("continuity_corrected") else ""),
        "",
        f"Slope (next u on previous u): **{slope.get('estimate')}** "
        f"(95% CI {_ci((slope.get('ci') or {}).get('low'), (slope.get('ci') or {}).get('high'))})",
        "",
        "## H2 — next-exposure persistence",
        "",
        _table(
            ["item", "value"],
            [
                ["session-lifts", h2["session_lifts"]],
                ["trigger session-lifts", h2["trigger_session_lifts"]],
                ["pairs", h2["pairs"]],
                ["excluded (known-modified)", h2["excluded_modified_pairs"]],
                ["trigger pairs", h2["trigger_pairs"]],
                ["control pairs", h2["control_pairs"]],
                ["difference (MAD)", h2["difference_mad"]],
                ["95% CI", _ci((h2["ci"] or {}).get("low"), (h2["ci"] or {}).get("high"))],
            ],
        ),
        "",
        f"Raw means: trigger **{h2['raw']['trigger_next_mean_u']}**, control "
        f"**{h2['raw']['control_next_mean_u']}**.",
        "",
        "## H3 — RIR and velocity agreement",
        "",
        _table(
            ["rir direction", "velocity verdict", "n"],
            [[row["rir_direction"], row["velocity_verdict"], row["n"]] for row in h3["table"]],
        ),
        "",
        f"Agreement: **{h3['agreement']}**; Cohen's kappa: **{h3['kappa']}**; dual-channel sets: **{h3['sets']}**.",
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


def analyse(db_path: str | Path) -> dict[str, Any]:
    import datetime as dt

    conn = connect_readonly(db_path)
    try:
        raw = load_sets(conn)
        stored = load_stored_targets(conn)
    finally:
        conn.close()

    prepared, excluded = prepare(raw)
    expected = add_expected_velocity(prepared)

    eligible = expected[expected["u"].notna()]
    trigger_sets = int((eligible["u"] < -K_BAND).sum()) if not eligible.empty else 0

    stored_u = pd.DataFrame()
    if not stored.empty:
        stored_prepared, _ = prepare(stored, require_stored_target=True)
        stored_prepared = add_stored_target_u(stored_prepared, expected)
        stored_u = stored_prepared[stored_prepared["u"].notna()]

    pairs = make_pairs(expected)
    h1 = analyse_h1(pairs)
    h2 = analyse_h2(expected)
    h3 = analyse_h3(expected)

    if not stored_u.empty:
        stored_pairs = make_pairs(mark_constant_load(stored_u), constant_load_only=False)
        h1["stored_target"] = analyse_h1(stored_pairs)

    trigger_rate = (
        round(h2["trigger_session_lifts"] / h2["session_lifts"], 4) if h2["session_lifts"] else None
    )
    coverage = {
        "sets_read": int(len(raw)),
        "eligible_sets": int(len(eligible)),
        "with_expectation": int(expected["u"].notna().sum()),
        "session_lifts": int(h2["session_lifts"]),
        "constant_load_session_lifts": int(
            expected[expected["constant_load"]].groupby(["session_id", "exercise_id"]).ngroups
        ) if not expected.empty else 0,
        "trigger_sets": trigger_sets,
        "trigger_rate": trigger_rate,
        "stored_target_sets": int(len(stored_u)),
        "exclusions": excluded,
    }
    report: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "database": {"path": str(Path(db_path).resolve()), "fingerprint": fingerprint(db_path)},
        "thresholds": THRESHOLDS,
        "coverage": coverage,
        "h1": h1,
        "h2": h2,
        "h3": h3,
        "limitations": list(LIMITATIONS),
    }
    report["verdict"] = decide(report)
    return report


def assert_writable(path: str, *, force: bool) -> None:
    """Refuse an output path outside `private/`, by containment rather than by name.

    Membership of a `private` path part looked equivalent and was not: on macOS every
    temporary file resolves through `/private/var`, so the check passed for a path nowhere
    near the repository and the guard never fired.
    """
    if force:
        return
    resolved = Path(path).resolve()
    private_root = (paths.repo_root() / "private").resolve()
    if not resolved.is_relative_to(private_root):
        raise SystemExit(f"refusing to write outside private/: {resolved} (use --force)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 0 performance carry-over analysis.")
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
