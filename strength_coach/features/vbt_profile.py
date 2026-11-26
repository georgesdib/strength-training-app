"""Read-only VBT load-velocity profile for the Exercises screen.

Display only. This module answers "what does this lift's mean-velocity-vs-load
curve look like, and what 1RM would the curve imply" and never feeds a
prescription: `features.vbt_calibration` stays the authority for velocity
targets. The implied e1RM is labelled with its assumption in the payload and in
the UI.

The response variable is the stored set mean concentric velocity
(`clean_set.velocity_mps`), not a per-rep best: it is the quantity the device
reports, the quantity the prescription compares, and it exists for the whole
history. Per-rep data is used only where it already exists as detail.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from strength_coach.utils import exercises, stats

METHOD_VERSION = "1.0.0"

# RIR values the fit accepts. The RIR-0 window amendment makes 0 legal to log and
# calibrate; the fit band is wider than the prescription *target* band (2-3) on
# purpose, because load and RIR are collinear and the regression carries RIR.
FIT_RIR_BAND: tuple[int, int] = (0, 4)

# Fit gates. The same honesty rule as the calibration: a line from four sets is
# not a profile.
MIN_SETS = 12
MIN_SESSIONS = 3
MIN_LOADS = 3
MIN_LOAD_SPAN = 0.10          # fraction of the heaviest load in the fit
MAX_OUTLIER_MADS = 3.0
EXTRAPOLATION_LIMIT = 2.5     # an implied 1RM beyond this multiple of max load is refused

# The implied e1RM is also reported as a point-in-time series: at each weekly
# evaluation date only sets from the trailing window are used, so a later heavy
# block cannot rewrite an earlier value. Same 84-day window as the load solver.
SERIES_WINDOW_DAYS = 84
SERIES_STEP_DAYS = 7
SERIES_MAX_POINTS = 52

# Minimal-velocity thresholds (mean concentric velocity at 1RM), by VBT family.
# ASSUMPTION-58: these are literature-typical display anchors, not estimates from
# this athlete's data. They only place the "VBT e1RM" marker; no load, target or
# rule uses them. A lift whose family is absent uses DEFAULT_MVT.
MVT_MPS: dict[str, float] = {
    "squat": 0.30,
    "hinge": 0.18,
    "trap_bar": 0.18,
    "bench": 0.17,
    "horizontal_push": 0.17,
    "vertical_push": 0.20,
    "horizontal_pull": 0.20,
    "vertical_pull": 0.20,
}
DEFAULT_MVT = 0.20


@dataclass(frozen=True)
class ProfilePoint:
    date: str
    load_kg: float
    velocity_mps: float
    rir: int

    def as_dict(self) -> dict:
        return {
            "date": self.date,
            "load_kg": self.load_kg,
            "velocity_mps": self.velocity_mps,
            "rir": self.rir,
        }


@dataclass(frozen=True)
class VbtProfile:
    exercise_id: str
    status: str                     # "fitted" | "insufficient" | "no_data"
    reason: str | None = None
    rep_count: int | None = None
    available_reps: tuple[dict, ...] = ()
    slope: float | None = None       # m/s per kg
    intercept: float | None = None
    rir_coef: float | None = None    # m/s per RIR
    r2: float | None = None
    residual_mad: float | None = None
    load_min: float | None = None
    load_max: float | None = None
    n_sets: int = 0
    n_sessions: int = 0
    n_loads: int = 0
    points: tuple[ProfilePoint, ...] = ()
    e1rm_kg: float | None = None
    e1rm_mvt_mps: float | None = None
    e1rm_basis: str | None = None
    e1rm_series: tuple[dict, ...] = ()
    # Pooled model across the lift's rep counts: velocity ~ load + reps + RIR.
    pooled_status: str = "no_data"
    pooled_reason: str | None = None
    pooled_slope: float | None = None
    pooled_intercept: float | None = None
    pooled_rep_coef: float | None = None
    pooled_rir_coef: float | None = None
    pooled_residual_mad: float | None = None
    pooled_load_min: float | None = None
    pooled_load_max: float | None = None
    pooled_reps_min: int | None = None
    pooled_reps_max: int | None = None
    pooled_n_sets: int = 0
    pooled_n_sessions: int = 0
    pooled_r2: float | None = None
    pooled_observed_reps: tuple[dict, ...] = ()
    method_version: str = METHOD_VERSION

    def as_dict(self) -> dict:
        return {
            "exercise_id": self.exercise_id,
            "status": self.status,
            "reason": self.reason,
            "rep_count": self.rep_count,
            "available_reps": list(self.available_reps),
            "slope": self.slope,
            "intercept": self.intercept,
            "rir_coef": self.rir_coef,
            "r2": self.r2,
            "residual_mad": self.residual_mad,
            "load_min": self.load_min,
            "load_max": self.load_max,
            "n_sets": self.n_sets,
            "n_sessions": self.n_sessions,
            "n_loads": self.n_loads,
            "points": [point.as_dict() for point in self.points],
            "e1rm_kg": self.e1rm_kg,
            "e1rm_mvt_mps": self.e1rm_mvt_mps,
            "e1rm_basis": self.e1rm_basis,
            "e1rm_series": list(self.e1rm_series),
            "pooled_status": self.pooled_status,
            "pooled_reason": self.pooled_reason,
            "pooled_slope": self.pooled_slope,
            "pooled_intercept": self.pooled_intercept,
            "pooled_rep_coef": self.pooled_rep_coef,
            "pooled_rir_coef": self.pooled_rir_coef,
            "pooled_residual_mad": self.pooled_residual_mad,
            "pooled_load_min": self.pooled_load_min,
            "pooled_load_max": self.pooled_load_max,
            "pooled_reps_min": self.pooled_reps_min,
            "pooled_reps_max": self.pooled_reps_max,
            "pooled_n_sets": self.pooled_n_sets,
            "pooled_n_sessions": self.pooled_n_sessions,
            "pooled_r2": self.pooled_r2,
            "pooled_observed_reps": list(self.pooled_observed_reps),
            "method_version": self.method_version,
        }


def mvt_for(family: str | None) -> float:
    return MVT_MPS.get(str(family or ""), DEFAULT_MVT)


def build(
    sets: pd.DataFrame,
    exercise_id: str,
    *,
    rep_count: int | None = None,
    family: str | None = None,
    mvt_mps: float | None = None,
) -> VbtProfile:
    """Build the profile from an enriched clean-set frame (see `derived.enrich`)."""
    if sets is None or sets.empty:
        return VbtProfile(
            exercise_id=exercise_id, status="no_data", reason="no stored sets",
            pooled_status="no_data", pooled_reason="no stored sets",
        )

    frame = _filtered(sets, exercise_id)
    available = _available_reps(frame)
    pooled_fit, pooled_status, pooled_reason = _pooled_fit(frame)
    pooled = _pooled_payload(pooled_fit, pooled_status, pooled_reason, frame)
    if pooled_status == "fitted":
        # Let the selector reach a rep count with no sets of its own: the pooled line is
        # then shown as an extrapolation instead of the panel going blank.
        have = {item["reps"] for item in available}
        extra = [
            {"reps": rep, "n_sets": 0, "fitted": False, "pooled": True}
            for rep in range(1, 9) if rep not in have
        ]
        if extra:
            available = tuple(sorted(list(available) + extra, key=lambda item: item["reps"]))
    if frame.empty:
        return VbtProfile(
            exercise_id=exercise_id, status="no_data",
            reason="no working sets with a stored mean velocity in the fit band",
            available_reps=available, **pooled,
        )

    chosen = rep_count if rep_count is not None else _default_rep(frame)
    group = frame[frame["reps"].astype(int) == int(chosen)]
    reason = _gate_reason(group)
    if reason is not None:
        return VbtProfile(
            exercise_id=exercise_id, status="insufficient", reason=reason,
            rep_count=int(chosen), available_reps=available, n_sets=int(len(group)),
            **pooled,
        )

    fit = _fit(group)
    if fit is None:
        return VbtProfile(
            exercise_id=exercise_id, status="insufficient", reason="no usable slope",
            rep_count=int(chosen), available_reps=available, n_sets=int(len(group)),
            **pooled,
        )

    mvt = float(mvt_mps) if mvt_mps is not None else mvt_for(family)
    e1rm = _implied_e1rm(fit, mvt)
    points = tuple(
        ProfilePoint(
            date=str(row.date)[:10],
            load_kg=round(float(row.load_kg), 2),
            velocity_mps=round(float(row.velocity_mps), 4),
            rir=int(row.rir),
        )
        for row in group.sort_values(["load_kg", "date"]).itertuples(index=False)
    )
    return VbtProfile(
        exercise_id=exercise_id,
        status="fitted",
        rep_count=int(chosen),
        available_reps=available,
        slope=round(float(fit["slope"]), 6),
        intercept=round(float(fit["intercept"]), 4),
        rir_coef=round(float(fit["rir_coef"]), 4) if fit["rir_coef"] is not None else None,
        r2=round(float(fit["r2"]), 3) if np.isfinite(fit["r2"]) else None,
        residual_mad=round(float(fit["residual_mad"]), 4),
        load_min=round(float(fit["load_min"]), 2),
        load_max=round(float(fit["load_max"]), 2),
        n_sets=int(len(group)),
        n_sessions=_session_count(group),
        n_loads=int(group["load_kg"].nunique()),
        points=points,
        e1rm_kg=round(e1rm, 1) if e1rm is not None else None,
        e1rm_mvt_mps=round(mvt, 3),
        e1rm_basis=(
            "line evaluated at a minimal-velocity anchor; display only"
            if e1rm is not None else None
        ),
        e1rm_series=_e1rm_series(frame, int(chosen), mvt),
        **pooled,
    )


MIN_REPS = 2


def _pooled_fit(frame: pd.DataFrame) -> tuple[dict | None, str, str | None]:
    """Fit `velocity ~ load + reps + RIR` across the lift's rep counts.

    Display view of the same fallback the calibration uses. The rep term is the fitted
    version of "use the available rep counts to extrapolate"; a non-negative rep or load
    coefficient is refused rather than drawn.
    """
    if frame.empty:
        return None, "no_data", "no stored sets"
    loads = frame["load_kg"].to_numpy(dtype="float64")
    velocities = frame["velocity_mps"].to_numpy(dtype="float64")
    reps = frame["reps"].to_numpy(dtype="float64")
    rirs = frame["rir"].to_numpy(dtype="float64")
    if loads.size < MIN_SETS:
        return None, "insufficient", f"fewer than {MIN_SETS} clean sets across rep counts"
    if np.unique(reps).size < MIN_REPS:
        return None, "insufficient", "fewer than 2 rep counts in the fitted sets"
    if np.unique(loads).size < MIN_LOADS:
        return None, "insufficient", f"fewer than {MIN_LOADS} distinct loads"
    top = float(loads.max())
    if top <= 0 or (top - float(loads.min())) / top < MIN_LOAD_SPAN:
        return None, "insufficient", "load range too narrow for a slope"
    columns = [np.ones_like(loads), loads, reps]
    if np.ptp(rirs) > 0:
        columns.append(rirs)
    design = np.column_stack(columns)
    beta, *_ = np.linalg.lstsq(design, velocities, rcond=None)
    slope = float(beta[1])
    rep_coef = float(beta[2])
    if not np.isfinite(slope) or slope >= 0 or not np.isfinite(rep_coef) or rep_coef >= 0:
        return None, "insufficient", "no usable load/reps trend"
    predicted = design @ beta
    residual = velocities - predicted
    spread = float(stats.mad(residual))
    if not np.isfinite(spread):
        return None, "insufficient", "no usable residual spread"
    total = float(np.sum((velocities - velocities.mean()) ** 2))
    return (
        {
            "slope": slope,
            "intercept": float(beta[0]),
            "rep_coef": rep_coef,
            "rir_coef": float(beta[3]) if design.shape[1] == 4 else None,
            "residual_mad": spread,
            "r2": 1.0 - float(np.sum(residual ** 2)) / total if total > 0 else float("nan"),
            "load_min": float(loads.min()),
            "load_max": top,
            "reps_min": int(reps.min()),
            "reps_max": int(reps.max()),
            "n_sets": int(loads.size),
            "n_sessions": _session_count(frame),
        },
        "fitted",
        None,
    )


def _pooled_payload(
    fit: dict | None, status: str, reason: str | None, frame: pd.DataFrame
) -> dict:
    observed: tuple[dict, ...] = ()
    if frame is not None and not frame.empty:
        sizes = frame.groupby(frame["reps"].astype(int)).size()
        observed = tuple(
            {"reps": int(reps), "n_sets": int(count)}
            for reps, count in sorted(sizes.items())
        )
    if fit is None:
        return {
            "pooled_status": status,
            "pooled_reason": reason,
            "pooled_observed_reps": observed,
        }
    return {
        "pooled_status": "fitted",
        "pooled_reason": None,
        "pooled_slope": round(float(fit["slope"]), 6),
        "pooled_intercept": round(float(fit["intercept"]), 4),
        "pooled_rep_coef": round(float(fit["rep_coef"]), 6),
        "pooled_rir_coef": (
            round(float(fit["rir_coef"]), 4) if fit["rir_coef"] is not None else None
        ),
        "pooled_residual_mad": round(float(fit["residual_mad"]), 4),
        "pooled_load_min": round(float(fit["load_min"]), 2),
        "pooled_load_max": round(float(fit["load_max"]), 2),
        "pooled_reps_min": int(fit["reps_min"]),
        "pooled_reps_max": int(fit["reps_max"]),
        "pooled_n_sets": int(fit["n_sets"]),
        "pooled_n_sessions": int(fit["n_sessions"]),
        "pooled_r2": (
            round(float(fit["r2"]), 3) if np.isfinite(fit["r2"]) else None
        ),
        "pooled_observed_reps": observed,
    }


def _filtered(sets: pd.DataFrame, exercise_id: str) -> pd.DataFrame:
    frame = sets[sets["exercise_id"].astype(str) == str(exercise_id)].copy()
    if frame.empty:
        return frame
    frame = frame[
        frame["is_working_set"].fillna(False).astype(bool)
        & frame["velocity_present"].fillna(False).astype(bool)
        & frame["velocity_mps"].notna()
        & (frame["velocity_mps"] > 0)
        & frame["reps"].notna()
        & frame["reps"].between(1, 8)
        & frame["rir"].notna()
        & frame["rir"].between(*FIT_RIR_BAND)
        & ~frame["load_basis"].eq("unknown")
        & ~frame["flags"].fillna("").str.contains("REPS_TYPO", regex=False)
        & frame["load_kg"].notna()
        & (frame["load_kg"] > 0)
    ].copy()
    if frame.empty:
        return frame
    # Warm-up-range loads carry no useful profile information, matching calibration.
    e1rm = frame["e1rm_kg"]
    usable = e1rm.isna() | (e1rm <= 0) | (frame["load_kg"] >= e1rm * 0.60)
    return frame[usable].copy()


def _available_reps(frame: pd.DataFrame) -> tuple[dict, ...]:
    if frame.empty:
        return ()
    out = []
    for reps, group in frame.groupby(frame["reps"].astype(int)):
        out.append({
            "reps": int(reps),
            "n_sets": int(len(group)),
            "fitted": _gate_reason(group) is None,
        })
    return tuple(sorted(out, key=lambda item: item["reps"]))


def _default_rep(frame: pd.DataFrame) -> int:
    counts = frame.groupby(frame["reps"].astype(int)).size()
    # Prefer a fittable rep count, then the most sets; ties go to the lower rep count.
    fittable = [int(r) for r, g in frame.groupby(frame["reps"].astype(int))
                if _gate_reason(g) is None]
    if fittable:
        return max(fittable, key=lambda r: (int(counts.get(r, 0)), -r))
    return int(max(counts.index, key=lambda r: (int(counts[r]), -int(r))))


def _session_count(frame: pd.DataFrame) -> int:
    """Sessions are `session_id` after a DB read; the cleaner's frame only has `date`."""
    if "session_id" in frame.columns:
        return int(frame["session_id"].nunique())
    return int(frame["date"].astype(str).nunique())


def _gate_reason(group: pd.DataFrame) -> str | None:
    if len(group) < MIN_SETS:
        return f"fewer than {MIN_SETS} clean sets at this rep count"
    if _session_count(group) < MIN_SESSIONS:
        return f"fewer than {MIN_SESSIONS} sessions at this rep count"
    loads = group["load_kg"].astype(float)
    if loads.nunique() < MIN_LOADS:
        return f"fewer than {MIN_LOADS} distinct loads at this rep count"
    if (loads.max() - loads.min()) / loads.max() < MIN_LOAD_SPAN:
        return "load range too narrow for a slope"
    return None


def _fit(group: pd.DataFrame) -> dict | None:
    frame = group
    for _ in range(2):
        result = _ols(frame)
        if result is None:
            return None
        residual = frame["velocity_mps"].to_numpy(dtype=float) - result["predicted"]
        spread = stats.mad(residual)
        if not np.isfinite(spread) or spread <= 0:
            break
        keep = np.abs(residual) <= MAX_OUTLIER_MADS * spread
        if keep.all() or int(keep.sum()) < MIN_SETS:
            break
        frame = frame[keep]
    result = _ols(frame)
    if result is None:
        return None
    residual = frame["velocity_mps"].to_numpy(dtype=float) - result["predicted"]
    total = frame["velocity_mps"].to_numpy(dtype=float)
    ss_res = float(np.sum(residual ** 2))
    ss_tot = float(np.sum((total - total.mean()) ** 2))
    return {
        "slope": result["slope"],
        "intercept": result["intercept"],
        "rir_coef": result["rir_coef"],
        "predicted": result["predicted"],
        "r2": 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan"),
        "residual_mad": stats.mad(residual),
        "load_min": float(frame["load_kg"].min()),
        "load_max": float(frame["load_kg"].max()),
    }


def _ols(frame: pd.DataFrame) -> dict | None:
    load = frame["load_kg"].to_numpy(dtype=float)
    velocity = frame["velocity_mps"].to_numpy(dtype=float)
    rir = frame["rir"].to_numpy(dtype=float)
    rir_coef: float | None = None
    if np.ptp(rir) > 0:
        design = np.column_stack([np.ones_like(load), load, rir])
    else:
        design = np.column_stack([np.ones_like(load), load])
    beta, *_ = np.linalg.lstsq(design, velocity, rcond=None)
    slope = float(beta[1])
    if not np.isfinite(slope) or slope >= 0:
        return None
    if design.shape[1] == 3:
        rir_coef = float(beta[2])
    return {
        "slope": slope,
        "intercept": float(beta[0]),
        "rir_coef": rir_coef,
        "predicted": design @ beta,
    }


def _implied_e1rm(fit: dict, mvt: float) -> float | None:
    # RIR 0 is the 1RM effort the anchor describes.
    value = (mvt - fit["intercept"]) / fit["slope"]
    if not np.isfinite(value) or value <= 0:
        return None
    if value < fit["load_max"] or value > fit["load_max"] * EXTRAPOLATION_LIMIT:
        return None
    return float(value)


def _e1rm_series(frame: pd.DataFrame, rep_count: int, mvt: float) -> tuple[dict, ...]:
    """Weekly, point-in-time implied e1RM using only each date's trailing window."""
    dated = frame[frame["date"].notna()].copy()
    if dated.empty:
        return ()
    dated["date"] = pd.to_datetime(dated["date"], errors="coerce")
    dated = dated[dated["date"].notna()]
    if dated.empty:
        return ()
    end = dated["date"].max()
    start = dated["date"].min()
    at_rep = dated[dated["reps"].astype(int) == int(rep_count)]
    if at_rep.empty:
        return ()
    points: list[dict] = []
    # Forward from the first observation on a fixed weekly grid: a later row can only
    # append points, it can never move an earlier one.
    cursor = start
    while cursor <= end:
        low = cursor - pd.Timedelta(days=SERIES_WINDOW_DAYS)
        window = at_rep[(at_rep["date"] > low) & (at_rep["date"] <= cursor)]
        if _gate_reason(window) is None:
            fit = _fit(window)
            if fit is not None:
                value = _implied_e1rm(fit, mvt)
                if value is not None:
                    points.append({
                        "date": cursor.date().isoformat(),
                        "e1rm_kg": round(float(value), 1),
                        "n_sets": int(len(window)),
                    })
        cursor = cursor + pd.Timedelta(days=SERIES_STEP_DAYS)
    return tuple(points[-SERIES_MAX_POINTS:])


def build_for(conn, exercise_id: str, *, rep_count: int | None = None) -> VbtProfile:
    """Convenience wrapper: load, enrich and build for one exercise."""
    from strength_coach.features import derived
    from strength_coach.store import queries

    raw = queries.clean_sets(conn, exercise_ids=(str(exercise_id),))
    sets = derived.enrich(raw) if not raw.empty else raw
    family = (exercises.taxonomy().entities.get(str(exercise_id)) or {}).get("vbt_family")
    return build(sets, str(exercise_id), rep_count=rep_count, family=family)
