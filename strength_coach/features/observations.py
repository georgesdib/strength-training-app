"""AFC-3 longitudinal observations over the AFC-2 evidence contract.

The service reads the payloads the owning services already produce (`adherence`,
`vbt_performance`) and reports one repeated pattern per family. It computes no metric: every
number is copied, every claim is wrapped by `features/evidence.py`, and a family that cannot
support a claim abstains with a reason instead of producing a value (DEC-AFC-01, DEC-AFC-04).

Observations are descriptive. They never diagnose, never change a prescription, and never feed
the Phase 5A instruments.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from strength_coach import adherence, workout
from strength_coach.features import vbt_performance
from strength_coach.features.evidence import EvidenceItem
from strength_coach.prescribe import session_identity
from strength_coach.store import queries
from strength_coach.utils import paths

FAMILIES = ("incomplete_work", "rir", "vbt")
DEFAULT_WINDOW_WEEKS = 8
MAX_WINDOW_WEEKS = 52
MAX_VBT_OBSERVATIONS = 3


@dataclass(frozen=True)
class ObservationConfig:
    """Display thresholds for AFC-3; see config/observations.v1.yaml."""

    window_weeks: int = DEFAULT_WINDOW_WEEKS
    comparison_sessions: int = 5
    repeated_required: int = 3
    vbt_max_within_band_ratio: float = 0.5

    @classmethod
    def load(cls, path: str | Path | None = None) -> ObservationConfig:
        source = Path(path or paths.config_dir("observations.v1.yaml"))
        data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        window = int(data.get("window_weeks", DEFAULT_WINDOW_WEEKS))
        comparison = int(data.get("comparison_sessions", 5))
        required = int(data.get("repeated_required", 3))
        if not 1 <= window <= MAX_WINDOW_WEEKS:
            raise ValueError("observations.window_weeks must be between 1 and 52")
        if not 1 <= required <= comparison:
            raise ValueError("observations.repeated_required must be within comparison_sessions")
        return cls(
            window_weeks=window,
            comparison_sessions=comparison,
            repeated_required=required,
            vbt_max_within_band_ratio=float(
                data.get("vbt_max_within_band_ratio", 0.5)
            ),
        )


def analyse(
    conn,
    *,
    as_of: str,
    weeks: int | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Detect the first-cut observations for the window ending `as_of`.

    `persist` appends only genuinely produced observations; a re-run of the same evidence is a
    no-op, and an abstention is never stored.
    """
    config = ObservationConfig.load()
    window_weeks = int(weeks or config.window_weeks)
    if not 1 <= window_weeks <= MAX_WINDOW_WEEKS:
        raise ValueError("weeks must be between 1 and 52")
    end = dt.date.fromisoformat(str(as_of))
    start = end - dt.timedelta(days=7 * window_weeks)
    window = {"start": start.isoformat(), "end": end.isoformat()}
    sessions = _comparable_sessions(conn, start.isoformat(), end.isoformat())

    observations: list[dict[str, Any]] = []
    abstain: list[dict[str, Any]] = []

    rir, rir_abstain = _rir_observation(sessions, config, window)
    _extend(observations, abstain, rir, rir_abstain)

    incomplete, incomplete_abstain = _incomplete_observation(sessions, config, window)
    _extend(observations, abstain, incomplete, incomplete_abstain)

    vbt_rows, vbt_abstain = _vbt_observations(conn, config, window)
    for row in vbt_rows:
        observations.append(row)
    if vbt_abstain is not None:
        abstain.append(vbt_abstain)

    observations.sort(key=lambda row: (FAMILIES.index(row["family"]), row["statement"]))
    if persist:
        _persist(conn, observations)
    return {
        "from": window["start"],
        "to": window["end"],
        "window_weeks": window_weeks,
        "comparison_sessions": config.comparison_sessions,
        "repeated_required": config.repeated_required,
        "sessions_in_window": len(sessions),
        "observations": observations,
        "abstain": abstain,
    }


def _extend(observations, abstain, row, reason) -> None:
    if row is not None:
        observations.append(row)
    if reason is not None:
        abstain.append(reason)


def _comparable_sessions(conn, start: str, end: str) -> list[dict[str, Any]]:
    """Completed app-tracked workouts in the window, newest first.

    Imports have no prescription snapshot and technique sessions have no normal plan, so both
    are excluded before any family sees them; the exclusion is reported once in the payload.
    """
    rows = conn.execute(
        """
        SELECT w.workout_id, w.for_date, w.session_type
          FROM workout_session w
          JOIN session s ON s.session_id = w.workout_id
         WHERE w.status = 'completed'
           AND w.for_date BETWEEN ? AND ?
           AND COALESCE(s.voided, 0) = 0
         ORDER BY w.for_date DESC, w.workout_id DESC
        """,
        (start, end),
    ).fetchall()
    output: list[dict[str, Any]] = []
    for row in rows:
        workout_id = str(row["workout_id"])
        if session_identity.is_technique(row["session_type"]):
            continue
        data = workout.get(conn, workout_id)
        if data is None:
            continue
        payload = adherence.analyse({
            **data,
            "sets": queries.session_clean_sets(conn, workout_id),
        })
        if payload.get("status") != "available":
            continue
        output.append({
            "workout_id": workout_id,
            "date": str(row["for_date"]),
            "adherence": payload,
        })
    return output


def _rir_observation(sessions, config, window):
    tolerance = adherence.RIR_TOLERANCE
    considered: list[dict[str, Any]] = []
    for session in sessions:
        rir = ((session["adherence"].get("final_plan") or {}).get("rir") or {})
        deviation = rir.get("mean_deviation")
        if deviation is None or int(rir.get("evaluated_sets") or 0) == 0:
            continue
        if deviation > tolerance:
            direction = "above"
        elif deviation < -tolerance:
            direction = "below"
        else:
            direction = "at"
        considered.append({
            "session": session,
            "direction": direction,
            "deviation": float(deviation),
            "rir": rir,
        })
        if len(considered) >= config.comparison_sessions:
            break

    if len(considered) < config.comparison_sessions:
        return None, {
            "family": "rir",
            "reason": (
                f"{len(considered)} comparable session(s) with evaluated RIR in the window, "
                f"need {config.comparison_sessions}"
            ),
        }

    counts = Counter(row["direction"] for row in considered if row["direction"] != "at")
    if not counts:
        return None, {
            "family": "rir",
            "reason": "every comparable session stayed inside the RIR tolerance",
        }
    direction, repeated = counts.most_common(1)[0]
    if repeated < config.repeated_required:
        return None, {
            "family": "rir",
            "reason": (
                f"{repeated} of {len(considered)} comparable sessions share a direction, "
                f"need {config.repeated_required}"
            ),
        }

    matching = [row for row in considered if row["direction"] == direction]
    mean_deviation = round(
        sum(row["deviation"] for row in matching) / len(matching), 2
    )
    set_ids = _rir_set_ids(matching)
    statement = (
        f"RIR sat {direction} target in {repeated} of the last {len(considered)} comparable "
        f"sessions (mean {mean_deviation:+.2f} RIR, tolerance {tolerance:g})."
    )
    item = EvidenceItem(
        source="adherence.rir",
        source_ids=tuple(set_ids),
        window_start=window["start"],
        window_end=window["end"],
        value={
            "direction": direction,
            "sessions_in_direction": repeated,
            "sessions_considered": len(considered),
            "mean_deviation": mean_deviation,
            "tolerance": tolerance,
        },
        unit="rir",
        n=len(considered),
        comparability="comparable",
        gate="signal",
        quality_flags=(
            ("sets_without_rir",)
            if any(int(row["rir"].get("unavailable_sets") or 0) > 0 for row in considered)
            else ()
        ),
        limitations=(
            "RIR is self-reported; a deviation is descriptive, not a judgment of effort",
            "tolerance is the adherence engine's own RIR tolerance, not a new threshold",
        ),
        rule_ids=("PRG-RIR-001", "DEC-AFC-01"),
    )
    return _observation("rir", statement, item, window), None


def _rir_set_ids(rows) -> list[Any]:
    ids: list[Any] = []
    for row in rows:
        for exercise in (row["session"]["adherence"].get("final_plan") or {}).get("exercises") or []:
            for detail in exercise.get("sets") or []:
                if detail.get("set_id") is not None:
                    ids.append(detail["set_id"])
    return ids


def _incomplete_observation(sessions, config, window):
    considered: list[dict[str, Any]] = []
    for session in sessions:
        slots = ((session["adherence"].get("final_plan") or {}).get("set_completion") or {})
        denominator = int(slots.get("denominator") or 0)
        if denominator == 0:
            continue
        missing = denominator - int(slots.get("numerator") or 0)
        considered.append({"session": session, "missing": missing, "slots": slots})
        if len(considered) >= config.comparison_sessions:
            break

    if len(considered) < config.comparison_sessions:
        return None, {
            "family": "incomplete_work",
            "reason": (
                f"{len(considered)} comparable session(s) with prescribed slots in the window, "
                f"need {config.comparison_sessions}"
            ),
        }

    incomplete = [row for row in considered if row["missing"] > 0]
    if len(incomplete) < config.repeated_required:
        return None, {
            "family": "incomplete_work",
            "reason": (
                f"{len(incomplete)} of {len(considered)} comparable sessions ended incomplete, "
                f"need {config.repeated_required}"
            ),
        }

    total_missing = sum(row["missing"] for row in incomplete)
    item = EvidenceItem(
        source="adherence.set_completion",
        source_ids=tuple(row["session"]["workout_id"] for row in incomplete),
        window_start=window["start"],
        window_end=window["end"],
        value={
            "incomplete_sessions": len(incomplete),
            "sessions_considered": len(considered),
            "missing_sets": total_missing,
        },
        unit="sets",
        n=len(considered),
        comparability="comparable",
        gate="signal",
        limitations=(
            "unperformed prescribed slots are descriptive; incomplete work is not athlete failure",
            "judged against final_plan; original is shown when the plan was modified",
        ),
        rule_ids=("DEC-AFC-01",),
    )
    statement = (
        f"{len(incomplete)} of the last {len(considered)} comparable sessions ended with "
        f"unperformed prescribed slots ({total_missing} sets)."
    )
    return _observation("incomplete_work", statement, item, window), None


def _vbt_observations(conn, config, window):
    payload = vbt_performance.analyse(conn, start=window["start"], end=window["end"])
    cohorts = [
        cohort for cohort in payload.get("cohorts") or []
        if cohort.get("gate") in {"signal", "evaluation"}
    ]
    selected: list[Mapping[str, Any]] = []
    for cohort in cohorts:
        band = cohort.get("within_calibration_band") or {}
        ratio = band.get("ratio")
        if ratio is None or ratio > config.vbt_max_within_band_ratio:
            continue
        selected.append(cohort)
    if not selected:
        reasons = (payload.get("summary") or {}).get("abstain") or (
            "no cohort reached signal"
        )
        return [], {
            "family": "vbt",
            "reason": "; ".join(str(reason) for reason in reasons[:2]),
        }
    selected.sort(
        key=lambda cohort: abs(cohort.get("median_relative_delta_pct") or 0), reverse=True
    )
    rows = []
    for cohort in selected[:MAX_VBT_OBSERVATIONS]:
        band = cohort.get("within_calibration_band") or {}
        statement = (
            f"VBT residuals for {cohort.get('exercise_name') or cohort.get('exercise_id')} "
            f"({cohort.get('target_rep_count')} reps) centre "
            f"{(cohort.get('median_residual_mps') or 0):+.2f} m/s from target; "
            f"{int(round((1 - float(band.get('ratio') or 0)) * 100))}% of comparable sets fall "
            f"outside the calibration band."
        )
        item = EvidenceItem(
            source="vbt_performance.cohort",
            source_ids=tuple(cohort.get("set_ids") or ()),
            window_start=window["start"],
            window_end=window["end"],
            value={
                "exercise_id": cohort.get("exercise_id"),
                "scope": cohort.get("scope"),
                "target_rep_count": cohort.get("target_rep_count"),
                "median_residual_mps": cohort.get("median_residual_mps"),
                "median_relative_delta_pct": cohort.get("median_relative_delta_pct"),
                "within_band_ratio": band.get("ratio"),
                "above_target": cohort.get("above_target"),
                "below_target": cohort.get("below_target"),
            },
            unit="m/s",
            n=int(cohort.get("n") or 0),
            comparability="comparable",
            gate=str(cohort.get("gate")),
            quality_flags=tuple(sorted(str(key) for key in (cohort.get("reasons") or {}))),
            calibration_ids=tuple(str(value) for value in cohort.get("calibration_ids") or ()),
            limitations=(
                "a residual outside the calibration band is not a failed session",
                "comparability and gate are the cohort's own; nothing is re-derived here",
            ),
            rule_ids=("DEC-AFC-01",),
        )
        rows.append(_observation("vbt", statement, item, window))
    return rows, None


def _observation(family: str, statement: str, item: EvidenceItem, window) -> dict[str, Any]:
    evidence = item.as_dict()
    observation_id = "ob:" + hashlib.sha256(
        "|".join([
            family, window["start"], window["end"], str(evidence["gate"]),
            str(evidence["n"]), str(evidence["evidence_id"]),
        ]).encode("utf-8")
    ).hexdigest()[:24]
    return {
        "observation_id": observation_id,
        "family": family,
        "statement": statement,
        "gate": evidence["gate"],
        "n": evidence["n"],
        "window": {"start": window["start"], "end": window["end"]},
        "evidence_id": evidence["evidence_id"],
        "value": evidence["value"],
        "evidence": evidence,
    }


def _persist(conn, observations) -> None:
    for observation in observations:
        payload = json.dumps(
            {
                "statement": observation["statement"],
                "value": observation["value"],
                "evidence": observation["evidence"],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        )
        conn.execute(
            """
            INSERT INTO observation (
                observation_id, family, window_start, window_end, gate, n, evidence_id,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(observation_id) DO NOTHING
            """,
            (
                observation["observation_id"],
                observation["family"],
                observation["window"]["start"],
                observation["window"]["end"],
                observation["gate"],
                observation["n"],
                observation["evidence_id"],
                payload,
            ),
        )
    conn.commit()
