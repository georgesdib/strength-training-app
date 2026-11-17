"""Cardio analytics: activity minutes, coverage and time in zone.

Deterministic, and every number says which tier produced it. Two policy rules shape the code:

* classification is a cascade -- Apple's METs, then %HRmax, then unclassified (`DEC-CARDIO-05`);
* a value is either measured or absent. Nothing is imputed, and unclassified time is reported as its
  own quantity rather than folded into zero.

Time in zone is computed per heart-rate sample and only for workouts whose series passes the continuity
test. Density is bimodal across this history -- a chest strap in 2016-2018 and live recording in 2026 are
dense, wrist background sampling in 2019-2025 is not -- so a samples-per-minute gate would measure the
recording mode rather than the data.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from typing import Any

MAX_HR_BPM = 200  # observed maximum in this store; reported with every result
MET_BANDS = (3.0, 6.0)  # WHO: moderate 3-6 METs, vigorous above 6
HR_BANDS = (0.64, 0.76)  # share of HRmax: light / moderate / vigorous
ZONES = ("light", "moderate", "vigorous")
RESISTANCE_TYPES = (
    "HKWorkoutActivityTypeTraditionalStrengthTraining",
    "HKWorkoutActivityTypeFunctionalStrengthTraining",
)
CONTINUITY_MAX_GAP_S = 30.0
CONTINUITY_MAX_INTERNAL_GAP_S = 120.0
CONTINUITY_MIN_COVERAGE = 0.5


def classify_met(mets: float | None) -> str | None:
    if mets is None or mets <= 0:
        return None
    if mets < MET_BANDS[0]:
        return "light"
    return "vigorous" if mets > MET_BANDS[1] else "moderate"


def classify_hr(heart_rate: float | None, max_hr: int = MAX_HR_BPM) -> str | None:
    if heart_rate is None or heart_rate <= 0:
        return None
    share = heart_rate / max_hr
    if share < HR_BANDS[0]:
        return "light"
    return "vigorous" if share > HR_BANDS[1] else "moderate"


def classify(workout: dict[str, Any], average_hr: float | None) -> tuple[str | None, str | None]:
    """Return (zone, tier); zone is None when the workout cannot be classified."""
    zone = classify_met(workout.get("avg_mets"))
    if zone is not None:
        return zone, "met"
    zone = classify_hr(average_hr)
    if zone is not None:
        return zone, "hr"
    return None, None


def continuity(epochs: list[float], duration_s: int) -> tuple[bool, float]:
    """(eligible for time-in-zone, median gap in seconds)."""
    if len(epochs) < 2:
        return False, 0.0
    gaps = sorted(b - a for a, b in zip(epochs, epochs[1:], strict=False))
    median = gaps[len(gaps) // 2]
    covered = epochs[-1] - epochs[0]
    # Three conditions, because each one alone lies. Coverage alone admits three samples across two
    # hours; the median alone admits a cluster of samples at the start and one hours later, which is
    # what a strength session looks like (median gap small, one long tail). The widest gap is what
    # distinguishes a recording from an accident.
    dense = median <= CONTINUITY_MAX_GAP_S
    unbroken = gaps[-1] <= CONTINUITY_MAX_INTERNAL_GAP_S
    spans = covered >= CONTINUITY_MIN_COVERAGE * duration_s
    return (dense and unbroken and spans), median


def _share(counter: Counter) -> dict[str, Any]:
    total = counter["total_min"]
    moderate, vigorous = counter["moderate_min"], counter["vigorous_min"]
    unclassified = counter["unclassified_min"]
    return {
        "workouts": counter["workouts"],
        "total_minutes": round(total, 1),
        "moderate_minutes": round(moderate, 1),
        "vigorous_minutes": round(vigorous, 1),
        "light_minutes": round(counter["light_min"], 1),
        "unclassified_minutes": round(unclassified, 1),
        "equivalent_minutes": round(moderate + 2 * vigorous, 1),
        "resistance_minutes": round(counter["resistance_min"], 1),
        "resistance_classified_minutes": round(counter["resistance_classified_min"], 1),
        "tier_minutes": {
            "met": round(counter["tier_met"], 1),
            "hr": round(counter["tier_hr"], 1),
            "none": round(counter["tier_none"], 1),
        },
        "classified_share": round((total - unclassified) / total, 3) if total else 0.0,
    }


def _hr_values(conn) -> dict[str, list[tuple[float, float]]]:
    """(epoch, bpm) per workout, ordered."""
    values: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in conn.execute(
        """
        SELECT external_workout_id, sampled_at, value FROM health_sample
        WHERE kind = 'heart_rate' AND external_workout_id IS NOT NULL
        ORDER BY external_workout_id, sampled_at
        """
    ):
        values[row["external_workout_id"]].append(
            (dt.datetime.fromisoformat(row["sampled_at"]).timestamp(), float(row["value"]))
        )
    return values


def report(conn, *, since: str | None = None, weeks_limit: int = 104) -> dict[str, Any]:
    workouts = [
        dict(row)
        for row in conn.execute("SELECT * FROM external_workout ORDER BY started_at")
    ]
    hr = _hr_values(conn)

    years: dict[str, Counter] = defaultdict(Counter)
    weeks: dict[str, Counter] = defaultdict(Counter)
    modalities: dict[str, Counter] = defaultdict(Counter)
    zone_minutes: dict[str, Counter] = defaultdict(Counter)
    eligible_by_year: Counter = Counter()
    eligible = 0

    for workout in workouts:
        started = dt.datetime.fromisoformat(workout["started_at"])
        if since and started.date().isoformat() < since:
            continue
        duration = int(workout["duration_s"])
        minutes = round(duration / 60.0, 1)
        series = hr.get(workout["external_workout_id"], [])
        average_hr = workout["avg_heart_rate"]
        if average_hr is None and series:
            average_hr = sum(bpm for _t, bpm in series) / len(series)
        zone, tier = classify(workout, average_hr)
        resistance = workout["activity_type"] in RESISTANCE_TYPES
        week = dt.date.fromisoformat(started.date().isoformat()).isocalendar()
        week_key = f"{week[0]}-W{week[1]:02d}"

        for bucket in (years[str(started.year)], weeks[week_key], modalities[workout["activity_type"]]):
            bucket["workouts"] += 1
            bucket["total_min"] += minutes
            bucket[f"{zone or 'unclassified'}_min"] += minutes
            bucket[f"tier_{tier or 'none'}"] += minutes
            if resistance:
                bucket["resistance_min"] += minutes
                if zone is not None:
                    bucket["resistance_classified_min"] += minutes

        if series:
            ok, _median = continuity([t for t, _bpm in series], duration)
            if ok:
                eligible += 1
                eligible_by_year[str(started.year)] += 1
                per_sample_min = minutes / len(series)
                for _t, bpm in series:
                    sample_zone = classify_hr(bpm)
                    if sample_zone is not None:
                        zone_minutes[str(started.year)][sample_zone] += per_sample_min

    ordered_weeks = sorted(weeks)
    rolling: dict[str, Any] = {}
    if workouts:
        latest = max(dt.datetime.fromisoformat(w["ended_at"]) for w in workouts)
        for label, days in (("7d", 7), ("28d", 28)):
            cutoff = latest - dt.timedelta(days=days)
            totals: Counter = Counter()
            for workout in workouts:
                ended = dt.datetime.fromisoformat(workout["ended_at"])
                if ended < cutoff:
                    continue
                series = hr.get(workout["external_workout_id"], [])
                average_hr = workout["avg_heart_rate"]
                if average_hr is None and series:
                    average_hr = sum(bpm for _t, bpm in series) / len(series)
                zone, _tier = classify(workout, average_hr)
                minutes = round(int(workout["duration_s"]) / 60.0, 1)
                totals[zone or "unclassified"] += minutes
                totals["total_min"] += minutes
            rolling[label] = {
                "total_minutes": round(totals["total_min"], 1),
                "moderate_minutes": round(totals["moderate"], 1),
                "vigorous_minutes": round(totals["vigorous"], 1),
                "equivalent_minutes": round(totals["moderate"] + 2 * totals["vigorous"], 1),
                "unclassified_minutes": round(totals["unclassified"], 1),
            }

    return {
        "policy": {
            "max_hr_bpm": MAX_HR_BPM,
            "met_bands": list(MET_BANDS),
            "hr_bands_share": list(HR_BANDS),
            "zones": list(ZONES),
            "continuity": {
                "max_median_gap_s": CONTINUITY_MAX_GAP_S,
                "max_internal_gap_s": CONTINUITY_MAX_INTERNAL_GAP_S,
                "min_coverage": CONTINUITY_MIN_COVERAGE,
            },
        },
        "years": {year: _share(counter) for year, counter in sorted(years.items())},
        "weeks": {week: _share(weeks[week]) for week in ordered_weeks[-weeks_limit:]},
        "modality": {
            name.replace("HKWorkoutActivityType", ""): _share(counter)
            for name, counter in sorted(modalities.items(), key=lambda kv: -kv[1]["total_min"])
        },
        "rolling": rolling,
        "time_in_zone": {
            "eligible_workouts": eligible,
            "eligible_by_year": dict(sorted(eligible_by_year.items())),
            "minutes_by_year": {
                year: {zone: round(counter[zone], 1) for zone in ZONES}
                for year, counter in sorted(zone_minutes.items())
            },
        },
    }
