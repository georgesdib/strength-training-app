"""Part B: the VBT execution residual, shadow only (DEC-RESIDUAL-01).

The residual is observed mean velocity minus the target the prescription was built with, on the
same lift, rep count and load basis, using a lift-scoped calibration only. It never changes a
prescription; the gates in ASSUMPTION-56 decide when it is even worth printing.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass
from typing import Any

# 84 days rather than 56: the evaluation gate needs 8 weeks of coverage, which a 56-day
# window can only just reach. The window bounds what is compared, not what is claimed.
WINDOW_DAYS = 84
MIN_OBSERVATIONS = 5
EVAL_OBSERVATIONS = 20
EVAL_WEEKS = 8


@dataclass(frozen=True)
class LiftResidual:
    exercise_id: str
    reps: int
    load_basis: str
    n: int
    weeks: float
    mean_residual: float
    spread: float | None
    calibration_scope: str
    gate: str  # insufficient | signal | evaluation
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "exercise_id": self.exercise_id,
            "reps": self.reps,
            "load_basis": self.load_basis,
            "n": self.n,
            "weeks": round(self.weeks, 1),
            "mean_residual": round(self.mean_residual, 3),
            "spread": None if self.spread is None else round(self.spread, 3),
            "calibration_scope": self.calibration_scope,
            "gate": self.gate,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ResidualReport:
    on_date: str
    window_days: int
    lifts: tuple[LiftResidual, ...]
    signal_available: bool
    evaluation_ready: bool
    abstain: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "on_date": self.on_date,
            "window_days": self.window_days,
            "lifts": [lift.as_dict() for lift in self.lifts],
            "signal_available": self.signal_available,
            "evaluation_ready": self.evaluation_ready,
            "abstain": list(self.abstain),
            "gates": {
                "min_observations": MIN_OBSERVATIONS,
                "evaluation_observations": EVAL_OBSERVATIONS,
                "evaluation_weeks": EVAL_WEEKS,
            },
        }


def _rows(conn, start: str, end: str) -> list[Any]:
    # Only sets that were performed against a stored prescription target can have a residual;
    # imported sets carry no target and must not be compared with a later calibration.
    return conn.execute(
        """
        SELECT ws.velocity, ws.reps, ws.exercise_id, w.for_date,
               pi.velocity_target, pi.load_basis, pi.vbt_basis
        FROM workout_set ws
        JOIN workout_session w ON w.workout_id = ws.workout_id
        JOIN prescription_item pi
          ON pi.prescription_id = w.prescription_id
         AND pi.order_index = ws.prescription_item_index
        WHERE ws.velocity IS NOT NULL AND ws.velocity > 0
          AND ws.reps IS NOT NULL
          AND pi.velocity_target IS NOT NULL
          AND w.for_date BETWEEN ? AND ?
        ORDER BY w.for_date
        """,
        (start, end),
    ).fetchall()


def compute(conn, on_date: str, *, window_days: int = WINDOW_DAYS) -> ResidualReport:
    """Group comparable execution residuals and apply the two sufficiency gates."""
    day = dt.date.fromisoformat(str(on_date)[:10])
    start = (day - dt.timedelta(days=window_days - 1)).isoformat()
    grouped: dict[tuple[str, int, str], list[tuple[str, float, str]]] = {}
    skipped_scope: set[str] = set()
    rows = _rows(conn, start, day.isoformat())
    for row in rows:
        scope = str(row["vbt_basis"] or "").split(" · ")[0].strip()
        if scope != "lift":
            # Family or pooled targets are not independent evidence for one lift.
            skipped_scope.add(str(row["exercise_id"]))
            continue
        key = (str(row["exercise_id"]), int(row["reps"]), str(row["load_basis"]))
        grouped.setdefault(key, []).append(
            (str(row["for_date"]), float(row["velocity"]) - float(row["velocity_target"]), scope)
        )

    abstain: list[str] = []
    if not rows:
        abstain.append(
            "no prescribed set in the window has both a velocity target and a stored velocity"
        )
    if skipped_scope:
        abstain.append(
            "lift-scoped calibration only: ignored "
            + ", ".join(sorted(skipped_scope))
        )
    if not grouped and rows:
        abstain.append("no lift-scoped comparable observations")

    lifts: list[LiftResidual] = []
    for (exercise_id, reps, load_basis), observations in sorted(grouped.items()):
        residuals = [item[1] for item in observations]
        dates = [dt.date.fromisoformat(item[0]) for item in observations]
        weeks = (max(dates) - min(dates)).days / 7.0
        n = len(residuals)
        spread = statistics.stdev(residuals) if n > 1 else None
        scope = observations[0][2]
        if n >= EVAL_OBSERVATIONS and weeks >= EVAL_WEEKS and spread is not None:
            gate = "evaluation"
            reason = (
                f"{n} observations over {weeks:.1f} weeks with a residual spread; "
                "ready for a prospective evaluation"
            )
        elif n >= MIN_OBSERVATIONS:
            gate = "signal"
            reason = (
                f"{n} observations, need {EVAL_OBSERVATIONS} over {EVAL_WEEKS} weeks "
                "before evaluation"
            )
        else:
            gate = "insufficient"
            reason = f"{n} observations, need {MIN_OBSERVATIONS} for a signal"
            abstain.append(f"{exercise_id} {reps}s: {reason}")
        lifts.append(LiftResidual(
            exercise_id=exercise_id, reps=reps, load_basis=load_basis, n=n,
            weeks=weeks, mean_residual=statistics.fmean(residuals), spread=spread,
            calibration_scope=scope, gate=gate, reason=reason,
        ))

    evaluation_ready = sum(1 for lift in lifts if lift.gate == "evaluation") >= 2
    return ResidualReport(
        on_date=day.isoformat(),
        window_days=window_days,
        lifts=tuple(lifts),
        signal_available=any(lift.gate in {"signal", "evaluation"} for lift in lifts),
        evaluation_ready=evaluation_ready,
        abstain=tuple(abstain),
    )
