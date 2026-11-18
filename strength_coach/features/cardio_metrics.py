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
from zoneinfo import ZoneInfo

from strength_coach.store import db
from strength_coach.store.cardio import hidden_workout_ids

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


def classification_rows(conn) -> list[dict[str, Any]]:
    """Classify every workout once, using the series mean only where Apple supplied no average."""
    averaged = {
        row["external_workout_id"]: row["avg_hr"]
        for row in conn.execute(
            "SELECT external_workout_id, AVG(value) AS avg_hr FROM health_sample "
            "WHERE kind = 'heart_rate' AND external_workout_id IS NOT NULL "
            "GROUP BY external_workout_id"
        )
    }
    rows = []
    for workout in conn.execute("SELECT * FROM external_workout ORDER BY started_at"):
        average_hr = workout["avg_heart_rate"]
        if average_hr is None:
            average_hr = averaged.get(workout["external_workout_id"])
        zone, tier = classify(dict(workout), average_hr)
        rows.append(
            {
                "external_workout_id": workout["external_workout_id"],
                "zone": zone,
                "tier": tier,
                "is_resistance": 1 if workout["activity_type"] in RESISTANCE_TYPES else 0,
                "minutes": round(int(workout["duration_s"]) / 60.0, 1),
                "started_at": workout["started_at"],
                "ended_at": workout["ended_at"],
            }
        )
    return rows


def rebuild_classification(conn) -> int:
    """Replace the cache from source. Idempotent; safe to run on every import."""
    rows = classification_rows(conn)
    now = dt.datetime.now(dt.UTC).isoformat()
    with db.transaction(conn):
        conn.execute("DELETE FROM cardio_classification")
        conn.executemany(
            """
            INSERT INTO cardio_classification (
                external_workout_id, zone, tier, is_resistance, minutes, started_at,
                ended_at, built_at
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            [
                (
                    row["external_workout_id"], row["zone"], row["tier"], row["is_resistance"],
                    row["minutes"], row["started_at"], row["ended_at"], now,
                )
                for row in rows
            ],
        )
        conn.execute(
            """
            INSERT INTO cardio_cache_state (name, value, updated_at) VALUES ('classification', ?, ?)
            ON CONFLICT(name) DO UPDATE SET value = excluded.value,
                                           updated_at = excluded.updated_at
            """,
            (str(len(rows)), now),
        )
    return len(rows)


def cache_is_stale(conn) -> bool:
    """True when the corpus has grown since the cache was built."""
    cached = conn.execute("SELECT COUNT(*) FROM cardio_classification").fetchone()[0]
    live = conn.execute("SELECT COUNT(*) FROM external_workout").fetchone()[0]
    return cached != live


def _as_of_date(as_of: str | None) -> dt.date:
    """Anchor for calendar windows: explicit when given, otherwise today in the reporting zone."""
    if as_of:
        return dt.date.fromisoformat(str(as_of))
    return dt.datetime.now(ZoneInfo("Europe/London")).date()


def _iso_week_key(day: dt.date) -> str:
    iso = day.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def activity_summary(
    conn, *, weeks: int = 12, as_of: str | None = None
) -> dict[str, Any]:
    """Weekly activity, rolling windows and coverage, read from the classification cache.

    Windows are **calendar** windows ending at `as_of` (default: today in Europe/London), never at
    the last workout. Anchoring on the last workout made "last 7 days" exclude the days since you
    last trained, which reads as a measurement error rather than a quiet week. `as_of` is injectable
    so the value is deterministic in tests.

    The cache is rebuilt here when the corpus has grown, so a page load is only ever slow once --
    on the first request after an import. Time-in-zone still needs the sample series and remains a
    separate, slower path.
    """
    anchor = _as_of_date(as_of)
    if cache_is_stale(conn):
        rebuild_classification(conn)
    hidden = hidden_workout_ids(conn)
    rows = [
        dict(row)
        for row in conn.execute("SELECT * FROM cardio_classification")
        if row["external_workout_id"] not in hidden
    ]

    # Every week in the window exists, even with no workouts: a gap is a real week with zero
    # minutes, not a week that disappears from the chart.
    anchor_week_start = anchor - dt.timedelta(days=anchor.weekday())
    week_totals: dict[str, Counter] = {
        _iso_week_key(anchor_week_start - dt.timedelta(weeks=offset)): Counter()
        for offset in range(weeks - 1, -1, -1)
    }
    year_totals: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        started = dt.datetime.fromisoformat(row["started_at"])
        iso = started.isocalendar()
        week_key = f"{iso[0]}-W{iso[1]:02d}"
        for bucket in (week_totals.setdefault(week_key, Counter()), year_totals[str(started.year)]):
            bucket["workouts"] += 1
            bucket["total_min"] += row["minutes"]
            bucket[f"{row['zone'] or 'unclassified'}_min"] += row["minutes"]
            bucket[f"tier_{row['tier'] or 'none'}"] += row["minutes"]
            if row["is_resistance"]:
                bucket["resistance_min"] += row["minutes"]
                if row["zone"] is not None:
                    bucket["resistance_classified_min"] += row["minutes"]

    ordered = sorted(week_totals)
    rolling: dict[str, Any] = {}
    for label, days in (("7d", 7), ("28d", 28)):
        first_day = anchor - dt.timedelta(days=days - 1)
        totals: Counter = Counter()
        for row in rows:
            ended = dt.datetime.fromisoformat(row["ended_at"]).astimezone(
                ZoneInfo("Europe/London")
            ).date()
            if not first_day <= ended <= anchor:
                continue
            totals[row["zone"] or "unclassified"] += row["minutes"]
            totals["total_min"] += row["minutes"]
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
            "equivalent_rule": "moderate + 2 * vigorous",
        },
        "weeks": [{"iso_week": week, **_share(week_totals[week])} for week in ordered[-weeks:]],
        "years": {year: _share(counter) for year, counter in sorted(year_totals.items())},
        "rolling": rolling,
        "latest_workout_at": max((row["ended_at"] for row in rows), default=None),
        "cache": {
            "rows": len(rows),
            "source_rows": conn.execute("SELECT COUNT(*) FROM external_workout").fetchone()[0],
        },
    }


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

        zones = sample_zone_minutes(series, duration_s=duration, minutes=minutes)
        if zones is not None:
            eligible += 1
            eligible_by_year[str(started.year)] += 1
            for zone_name, value in zones.items():
                zone_minutes[str(started.year)][zone_name] += value

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

# --- Longevity assessment -------------------------------------------------
#
# The three questions the Today card and the web Longevity panel answer (is the aerobic
# reference met, is the stored VO2max readable, what volume headroom remains) are computed here
# and nowhere else, so the phone, the browser and the intelligence capability cannot disagree.
# Everything is deterministic: no model, no randomness, and the anchor date is injectable.

REFERENCE_MINUTES = (150.0, 300.0)  # WHO 2020: 150-300 moderate (75-150 vigorous) per week
CLASSIFIED_FLOOR = 0.5  # below half the week classified, the weekly relation stays unknown
VO2MAX_STALE_DAYS = 90  # Apple writes VO2max weekly-ish; a season-old estimate is not current


def sample_zone_minutes(
    series: list[tuple[float, float]], *, duration_s: int, minutes: float
) -> Counter | None:
    """Per-sample zone minutes for one workout, or None when its series is not eligible.

    One implementation for both consumers: the per-year time-in-zone report and the longevity
    panel. Whole-workout classification is a different (and more generous) estimate.
    """
    if not series:
        return None
    ok, _median = continuity([t for t, _bpm in series], duration_s)
    if not ok:
        return None
    out: Counter = Counter()
    per_sample = minutes / len(series)
    for _t, bpm in series:
        zone = classify_hr(bpm)
        if zone is not None:
            out[zone] += per_sample
    return out


def time_in_zone(conn, *, on_date: str | None = None, days: int = 28) -> dict[str, Any]:
    """Sample-based zone minutes over a calendar window, with its own coverage.

    This covers only continuity-eligible workouts, so it is reported as its own block and never
    merged into the weekly total. Hidden workouts are excluded like everywhere else.
    """
    anchor = _as_of_date(on_date)
    first = anchor - dt.timedelta(days=days - 1)
    hidden = hidden_workout_ids(conn)
    series_by_workout = _hr_values(conn)
    totals: Counter = Counter()
    covered = 0
    eligible = 0
    for row in conn.execute("SELECT * FROM external_workout"):
        workout = dict(row)
        if workout["external_workout_id"] in hidden:
            continue
        ended = dt.datetime.fromisoformat(workout["ended_at"]).astimezone(
            ZoneInfo("Europe/London")
        ).date()
        if not first <= ended <= anchor:
            continue
        series = series_by_workout.get(workout["external_workout_id"], [])
        if not series:
            continue
        covered += 1
        minutes = round(int(workout["duration_s"]) / 60.0, 1)
        zones = sample_zone_minutes(
            series, duration_s=int(workout["duration_s"]), minutes=minutes
        )
        if zones is None:
            continue
        eligible += 1
        totals.update(zones)
    return {
        "window": {"start": first.isoformat(), "end": anchor.isoformat(), "days": days},
        "workouts_with_series": covered,
        "eligible_workouts": eligible,
        "coverage_share": round(eligible / covered, 3) if covered else 0.0,
        "minutes": {zone: round(totals[zone], 1) for zone in ZONES},
        "equivalent_minutes": round(totals["moderate"] + 2 * totals["vigorous"], 1),
        "source": "heart-rate samples of continuity-eligible workouts",
    }


def latest_vo2max(conn) -> dict[str, Any] | None:
    """The newest stored VO2max measurement row, or None when the athlete has none."""
    row = conn.execute(
        """
        SELECT m.*, d.unit AS unit
          FROM measurement m
          JOIN metric_definition d ON d.metric_key = m.metric_key
         WHERE m.metric_key = 'vo2max'
         ORDER BY m.measured_on DESC, m.created_at DESC
         LIMIT 1
        """
    ).fetchone()
    return dict(row) if row is not None else None


def vo2max_assessment(
    row: dict[str, Any] | None, today: dt.date, *, stale_days: int = VO2MAX_STALE_DAYS
) -> dict[str, Any]:
    """The stored estimate as it may be read: value, date, source, currency.

    No reference category: age and sex are not stored, and a consumer estimate does not support
    a banded verdict (DEC-LONGEVITY-04). Absence is reported as absent, never as poor fitness.
    """
    if row is None:
        return {
            "status": "absent",
            "value": None,
            "unit": "ml/kg/min",
            "measured_on": None,
            "source": None,
            "age_days": None,
        }
    measured = dt.date.fromisoformat(str(row["measured_on"]))
    age_days = (today - measured).days
    return {
        "status": "stale" if age_days > stale_days else "current",
        "value": round(float(row["value"]), 1),
        "unit": str(row.get("unit") or "ml/kg/min"),
        "measured_on": measured.isoformat(),
        "source": row.get("source"),
        "age_days": age_days,
    }


def adequacy(
    summary: dict[str, Any],
    *,
    today: dt.date,
    vo2max_row: dict[str, Any] | None = None,
    patterns: dict[str, Any] | None = None,
    sessions_remaining: int | None = None,
    time_in_zone_block: dict[str, Any] | None = None,
    stale_days: int = VO2MAX_STALE_DAYS,
    classified_floor: float = CLASSIFIED_FLOOR,
) -> dict[str, Any]:
    """The deterministic longevity assessment over three frames.

    The relation to the WHO reference is stated for the **last completed week** only: a
    week-to-date reading would report "below" every Monday. The current week reports progress and
    what is left, and the coming week is where the advice points.

    Pure: takes an already-built activity summary, the latest VO2max row, the optional pattern
    headroom and the optional time-in-zone block. No database access, no clock.
    """
    ref_min, ref_max = REFERENCE_MINUTES
    missing: list[str] = []
    by_week = {str(row.get("iso_week")): row for row in summary.get("weeks", [])}
    current_start = today - dt.timedelta(days=today.weekday())
    current_end = current_start + dt.timedelta(days=6)
    last_start = current_start - dt.timedelta(days=7)
    last_end = current_start - dt.timedelta(days=1)

    current_row = by_week.get(_iso_week_key(current_start))
    if current_row is None:
        missing.append(f"no classification rows for {_iso_week_key(current_start)}")
        current_row = {}
    current_week = {
        "iso_week": _iso_week_key(current_start),
        "start": current_start.isoformat(),
        "end": current_end.isoformat(),
        "days_elapsed": (today - current_start).days + 1,
        "days_remaining": (current_end - today).days,
        "workouts": int(current_row.get("workouts") or 0),
        "total_minutes": round(float(current_row.get("total_minutes") or 0.0), 1),
        "moderate_minutes": round(float(current_row.get("moderate_minutes") or 0.0), 1),
        "vigorous_minutes": round(float(current_row.get("vigorous_minutes") or 0.0), 1),
        "equivalent_minutes": round(float(current_row.get("equivalent_minutes") or 0.0), 1),
        "unclassified_minutes": round(float(current_row.get("unclassified_minutes") or 0.0), 1),
    }

    last_row = by_week.get(_iso_week_key(last_start))
    if last_row is None:
        missing.append(f"no completed week to assess (missing {_iso_week_key(last_start)})")
        last_week = None
    else:
        equivalent = float(last_row.get("equivalent_minutes") or 0.0)
        share = float(last_row.get("classified_share") or 0.0)
        gate = "signal" if share >= classified_floor else "insufficient"
        if gate == "insufficient":
            relation = "unknown"
            remaining_minutes = None
        elif equivalent >= ref_min:
            relation = "inside"
            remaining_minutes = None
        else:
            relation = "below"
            remaining_minutes = round(ref_min - equivalent, 1)
        last_week = {
            "iso_week": _iso_week_key(last_start),
            "start": last_start.isoformat(),
            "end": last_end.isoformat(),
            "workouts": int(last_row.get("workouts") or 0),
            "total_minutes": round(float(last_row.get("total_minutes") or 0.0), 1),
            "moderate_minutes": round(float(last_row.get("moderate_minutes") or 0.0), 1),
            "vigorous_minutes": round(float(last_row.get("vigorous_minutes") or 0.0), 1),
            "equivalent_minutes": round(equivalent, 1),
            "unclassified_minutes": round(float(last_row.get("unclassified_minutes") or 0.0), 1),
            "resistance_minutes": round(float(last_row.get("resistance_minutes") or 0.0), 1),
            "resistance_classified_minutes": round(
                float(last_row.get("resistance_classified_minutes") or 0.0), 1
            ),
            "classified_share": share,
            "gate": gate,
            "relation": relation,
            "above_upper": None if gate == "insufficient" else equivalent > ref_max,
            "remaining_minutes": remaining_minutes,
            "tier_minutes": dict(last_row.get("tier_minutes") or {}),
        }

    return {
        "as_of": today.isoformat(),
        "reference": {
            "min_minutes": ref_min,
            "max_minutes": ref_max,
            "equivalence": "moderate + 2 * vigorous",
            "role": "context, not a target",
            "source": "WHO 2020 aerobic activity guideline",
        },
        "last_week": last_week,
        "current_week": current_week,
        "sessions_remaining": sessions_remaining,
        "vo2max": vo2max_assessment(vo2max_row, today, stale_days=stale_days),
        "time_in_zone": time_in_zone_block,
        "patterns": patterns,
        "missing": missing,
    }


def assessment(
    conn,
    *,
    as_of: str | None = None,
    include_tiz: bool = False,
    patterns: dict[str, Any] | None = None,
    sessions_remaining: int | None = None,
) -> dict[str, Any]:
    """Compose the assessment from one summary read, the VO2max row and the caller's extra blocks.

    `patterns` (per-pattern volume headroom) and `sessions_remaining` are supplied by the caller
    because they belong to the programme, not to cardio; the cardio module must not read the
    programme itself.
    """
    day = _as_of_date(as_of)
    summary = activity_summary(conn, weeks=2, as_of=day.isoformat())
    return adequacy(
        summary,
        today=day,
        vo2max_row=latest_vo2max(conn),
        patterns=patterns,
        sessions_remaining=sessions_remaining,
        time_in_zone_block=time_in_zone(conn, on_date=day.isoformat()) if include_tiz else None,
    )
