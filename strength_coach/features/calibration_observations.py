"""Read-only calibration observations around the existing active mechanism.

This module does not calculate or apply a calibration factor. It reports the measured tests
already stored, the prior raw formula estimate, and the factor/CI that the existing
e1rm_calibration.build() already produced. Existing factors are reported as found.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from strength_coach.domain.e1rm import E1RM_METHOD_VERSION
from strength_coach.features import e1rm_calibration, strength_trend
from strength_coach.store import queries


@dataclass(frozen=True)
class CalibrationObservation:
    observation_id: str
    source_override_id: int
    exercise_id: str
    performed_on: str
    test_type: str | None
    measured_kg: float
    measured_source: str
    prior_raw_e1rm_kg: float | None
    prior_raw_method: str | None
    prior_raw_method_version: str
    prior_raw_observed_on: str | None
    prior_raw_ref: str | None
    date_gap_days: int | None
    protocol: str
    equipment: str
    eligibility: str
    exclusion_reason: str | None
    linked_exposure_id: str | None
    existing_calibration_factor: float
    existing_factor_applied: bool
    calibration_ci_low: float | None
    calibration_ci_high: float | None
    calibration_ci_width: float | None
    calibration_eligibility_reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "source_override_id": self.source_override_id,
            "exercise_id": self.exercise_id,
            "performed_on": self.performed_on,
            "test_type": self.test_type,
            "measured_kg": round(self.measured_kg, 2),
            "measured_source": self.measured_source,
            "prior_raw_e1rm_kg": (
                None if self.prior_raw_e1rm_kg is None
                else round(self.prior_raw_e1rm_kg, 2)
            ),
            "prior_raw_method": self.prior_raw_method,
            "prior_raw_method_version": self.prior_raw_method_version,
            "prior_raw_observed_on": self.prior_raw_observed_on,
            "prior_raw_ref": self.prior_raw_ref,
            "date_gap_days": self.date_gap_days,
            "protocol": self.protocol,
            "equipment": self.equipment,
            "eligibility": self.eligibility,
            "exclusion_reason": self.exclusion_reason,
            "linked_exposure_id": self.linked_exposure_id,
            "existing_calibration_factor": round(self.existing_calibration_factor, 4),
            "existing_factor_applied": self.existing_factor_applied,
            "calibration_ci_low": (
                None if self.calibration_ci_low is None else round(self.calibration_ci_low, 4)
            ),
            "calibration_ci_high": (
                None if self.calibration_ci_high is None else round(self.calibration_ci_high, 4)
            ),
            "calibration_ci_width": (
                None if self.calibration_ci_width is None
                else round(self.calibration_ci_width, 4)
            ),
            "calibration_eligibility_reason": self.calibration_eligibility_reason,
        }


def _linked_exposures(conn) -> dict[str, dict[str, Any]]:
    return {
        str(row["source_id"]): dict(row)
        for row in conn.execute(
            "SELECT * FROM high_intensity_exposure WHERE source_id IS NOT NULL"
        )
    }


def observations(
    conn,
    *,
    exercise_id: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[CalibrationObservation]:
    """Measured tests with their prior raw estimate and existing calibration context.

    Only e1rm_override.source measured (or clinician, labelled explicitly) is considered.
    Ordinary training sets are never treated as criterion tests.
    """
    as_of = to_date or pd.Timestamp.today().date().isoformat()
    overrides = [
        row for row in queries.e1rm_overrides(conn)
        if row.get("source") in {"measured", "clinician"}
        and (from_date is None or str(row["effective_from"]) >= from_date)
        and str(row["effective_from"]) <= as_of
        and (exercise_id is None or str(row["exercise_id"]) == exercise_id)
    ]
    calibration_rows = {
        str(row.exercise_id): row
        for row in e1rm_calibration.build(conn, as_of=as_of)
    }
    exposures = _linked_exposures(conn)
    out: list[CalibrationObservation] = []
    for override in sorted(overrides, key=lambda row: (str(row["effective_from"]), int(row["override_id"]))):
        measured_on = str(override["effective_from"])
        ex_id = str(override["exercise_id"])
        prior_points = [
            point for point in strength_trend.observations(
                conn, ex_id, "1900-01-01", measured_on
            )
            if point.date < measured_on
        ]
        prior = prior_points[-1] if prior_points else None
        linked = exposures.get(f"e1rm_override:{int(override['override_id'])}")
        calibration = calibration_rows.get(ex_id)
        prior_kg = None if prior is None else prior.estimate.kg
        prior_ref = (
            None if prior is None
            else f"set:{prior.session_id}/{int(prior.estimate.set_id)}"
        )
        gap = (
            None if prior is None
            else abs((pd.Timestamp(measured_on) - pd.Timestamp(prior.date)).days)
        )
        if prior is None:
            eligibility = "excluded"
            exclusion = "no prior raw e1RM strictly before the measured test"
        else:
            eligibility = "eligible"
            exclusion = None
        ci_low = None if calibration is None else calibration.ci_low
        ci_high = None if calibration is None else calibration.ci_high
        out.append(CalibrationObservation(
            observation_id=f"e1rm_override:{int(override['override_id'])}",
            source_override_id=int(override["override_id"]),
            exercise_id=ex_id,
            performed_on=measured_on,
            test_type=None if linked is None else linked.get("test_type"),
            measured_kg=float(override["e1rm_kg"]),
            measured_source=str(override.get("source") or "measured"),
            prior_raw_e1rm_kg=prior_kg,
            prior_raw_method=None if prior is None else prior.estimate.method,
            prior_raw_method_version=(
                E1RM_METHOD_VERSION if prior is None else prior.estimate.method_version
            ),
            prior_raw_observed_on=None if prior is None else prior.date,
            prior_raw_ref=prior_ref,
            date_gap_days=gap,
            protocol="unknown",
            equipment="unknown",
            eligibility=eligibility,
            exclusion_reason=exclusion,
            linked_exposure_id=None if linked is None else str(linked.get("exposure_id")),
            existing_calibration_factor=(
                1.0 if calibration is None else float(calibration.correction_factor)
            ),
            existing_factor_applied=(
                False if calibration is None else bool(calibration.correction_applied)
            ),
            calibration_ci_low=ci_low,
            calibration_ci_high=ci_high,
            calibration_ci_width=(
                None if ci_low is None or ci_high is None else float(ci_high - ci_low)
            ),
            calibration_eligibility_reason=(
                "no calibration row for this lift" if calibration is None
                else calibration.correction_reason
            ),
        ))
    return out
