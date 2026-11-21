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
import sqlite3
import statistics
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from strength_coach import settings_profile
from strength_coach.store import db
from strength_coach.store.cardio import hidden_workout_ids

DEFAULT_MAX_HR_BPM = 200  # registry default; an effective-dated profile override wins at read time
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
#: A gap wider than this is unobserved time; it is never spread across the adjacent zones. The
#: continuity gate already rejects such a series, so this is a second, independent guard.
MAX_ZONE_INTEGRATION_GAP_S = CONTINUITY_MAX_INTERNAL_GAP_S


def classify_met(mets: float | None) -> str | None:
    if mets is None or mets <= 0:
        return None
    if mets < MET_BANDS[0]:
        return "light"
    return "vigorous" if mets > MET_BANDS[1] else "moderate"


def configured_max_hr(conn, *, on_date: str | None = None) -> int:
    """Return the effective profile value for percent-HRmax classification.

    The anchor follows the module's reporting zone, so a server outside Europe/London cannot
    resolve a different profile version around midnight than the calendar windows use.
    """
    day = _as_of_date(on_date).isoformat()
    profile = settings_profile.latest(conn, day)
    overrides = profile["overrides"] if profile else {}
    return int(settings_profile.resolved_registry(overrides)["cardio.max_hr_bpm"])


def classify_hr(heart_rate: float | None, max_hr: int = DEFAULT_MAX_HR_BPM) -> str | None:
    if heart_rate is None or heart_rate <= 0:
        return None
    share = heart_rate / max_hr
    if share < HR_BANDS[0]:
        return "light"
    return "vigorous" if share > HR_BANDS[1] else "moderate"


def classify(
    workout: dict[str, Any], average_hr: float | None, *, max_hr: int = DEFAULT_MAX_HR_BPM,
) -> tuple[str | None, str | None]:
    """Return (zone, tier); zone is None when the workout cannot be classified."""
    zone = classify_met(workout.get("avg_mets"))
    if zone is not None:
        return zone, "met"
    zone = classify_hr(average_hr, max_hr)
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


def _workout_hr_rows(conn, workout_ids: list[str] | None = None):
    """Heart-rate samples that belong to a workout's own interval.

    Two filters, deliberately independent: the importer labels the ten-minute recovery window
    after a workout as association 'tail', and a mislabelled row can still sit outside
    [started_at, ended_at]. Intensity is only ever read from a sample that passes both.
    """
    sql = """
        SELECT s.external_workout_id, s.sampled_at, s.value
          FROM health_sample s
          JOIN external_workout w
            ON w.external_workout_id = s.external_workout_id
         WHERE s.kind = 'heart_rate'
           AND s.association = 'workout'
           AND s.sampled_at >= w.started_at
           AND s.sampled_at <= w.ended_at
    """
    if workout_ids is None:
        yield from conn.execute(sql + " ORDER BY s.external_workout_id, s.sampled_at")
        return
    unique = list(dict.fromkeys(workout_ids))
    # SQLite caps the number of bound parameters, so large windows are read in chunks.
    for start in range(0, len(unique), 500):
        chunk = unique[start:start + 500]
        marks = ",".join("?" * len(chunk))
        yield from conn.execute(
            sql + f" AND s.external_workout_id IN ({marks})"
            " ORDER BY s.external_workout_id, s.sampled_at",
            chunk,
        )


def _hr_values(conn) -> dict[str, list[tuple[float, float]]]:
    """(epoch, bpm) per workout, ordered; workout samples inside the workout interval only."""
    values: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in _workout_hr_rows(conn):
        values[row["external_workout_id"]].append(
            (dt.datetime.fromisoformat(row["sampled_at"]).timestamp(), float(row["value"]))
        )
    return values


def hr_values_for(conn, workout_ids: list[str]) -> dict[str, list[tuple[float, float]]]:
    """(epoch, bpm) per workout, for the named workouts only.

    The corpus holds ~590,000 heart-rate samples; loading all of them to answer a 28-day question
    cost 6 s on the ODROID, while the 25 workouts in that window hold ~4,900. Chunked because
    SQLite caps the number of bound parameters.
    """
    values: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in _workout_hr_rows(conn, workout_ids):
        values[row["external_workout_id"]].append(
            (dt.datetime.fromisoformat(row["sampled_at"]).timestamp(), float(row["value"]))
        )
    return values


def classification_rows(conn, *, max_hr: int = DEFAULT_MAX_HR_BPM) -> list[dict[str, Any]]:
    """Classify every workout once, using the series mean only where Apple supplied no average.

    The fallback mean is computed from workout-interval samples only. Recovery-tail samples are
    kept in the corpus for recovery, but they are not exercise intensity and must never move a
    workout's zone.
    """
    averaged = {
        row["external_workout_id"]: row["avg_hr"]
        for row in conn.execute(
            """
            SELECT s.external_workout_id, AVG(s.value) AS avg_hr
              FROM health_sample s
              JOIN external_workout w
                ON w.external_workout_id = s.external_workout_id
             WHERE s.kind = 'heart_rate'
               AND s.association = 'workout'
               AND s.sampled_at >= w.started_at
               AND s.sampled_at <= w.ended_at
             GROUP BY s.external_workout_id
            """
        )
    }
    rows = []
    for workout in conn.execute("SELECT * FROM external_workout ORDER BY started_at"):
        average_hr = workout["avg_heart_rate"]
        if average_hr is None:
            average_hr = averaged.get(workout["external_workout_id"])
        zone, tier = classify(dict(workout), average_hr, max_hr=max_hr)
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


CLASSIFICATION_STATE = "classification"


def invalidate_classification(conn) -> None:
    """Force the next summary read to rebuild the cache from source.

    This is the cheap half of the invalidation contract: a heart-rate sample can change a
    workout's classification without changing the workout count, so ingestion drops the state
    marker instead of making every read scan ~590,000 samples to discover it. Re-inserting an
    identical sample is a no-op in the store and does not reach here, so a re-import does not
    cause a rebuild.
    """
    conn.execute(
        "DELETE FROM cardio_cache_state WHERE name = ?", (CLASSIFICATION_STATE,)
    )


def rebuild_classification(conn, *, max_hr: int = DEFAULT_MAX_HR_BPM) -> int:
    """Replace the cache from source. Idempotent; safe to run on every import."""
    rows = classification_rows(conn, max_hr=max_hr)
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
            INSERT INTO cardio_cache_state (name, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET value = excluded.value,
                                           updated_at = excluded.updated_at
            """,
            (CLASSIFICATION_STATE, f"{len(rows)}:{max_hr}", now),
        )
    return len(rows)


def cache_is_stale(conn, *, max_hr: int = DEFAULT_MAX_HR_BPM) -> bool:
    """True when the cache is absent or the workout corpus has changed since it was built.

    Presence of the state marker is the ingestion signal: adding heart-rate samples for an
    already-imported workout deletes it. The fingerprint also includes the configured maximum
    heart rate, so changing the profile reclassifies existing cardio history. The row-count
    comparison still catches a new or removed workout written by any path.
    """
    state = conn.execute(
        "SELECT value FROM cardio_cache_state WHERE name = ?", (CLASSIFICATION_STATE,)
    ).fetchone()
    if state is None:
        return True
    cached = conn.execute("SELECT COUNT(*) FROM cardio_classification").fetchone()[0]
    live = conn.execute("SELECT COUNT(*) FROM external_workout").fetchone()[0]
    return cached != live or state[0] != f"{live}:{max_hr}"


#: One rebuild at a time per process. Without this, every request that sees a stale cache
#: builds its own copy: the expensive classification runs before the write transaction, so
#: concurrent readers multiply the work instead of waiting for the first rebuild to finish.
_REBUILD_LOCK = threading.Lock()


def ensure_classification(conn, *, max_hr: int = DEFAULT_MAX_HR_BPM) -> None:
    """Rebuild the cache at most once when several requests observe the same stale corpus."""
    if not cache_is_stale(conn, max_hr=max_hr):
        return
    with _REBUILD_LOCK:
        if cache_is_stale(conn, max_hr=max_hr):
            rebuild_classification(conn, max_hr=max_hr)


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
    max_hr = configured_max_hr(conn, on_date=anchor.isoformat())
    hidden = hidden_workout_ids(conn)
    try:
        ensure_classification(conn, max_hr=max_hr)
        rows = [
            dict(row)
            for row in conn.execute("SELECT * FROM cardio_classification")
            if row["external_workout_id"] not in hidden
        ]
    except sqlite3.OperationalError as exc:
        # Intelligence reads run on a read-only SQLite handle by policy. A stale or absent
        # classification cache must not turn an otherwise read-only summary into a 500: classify
        # from source in memory instead of writing the cache.
        if "readonly" not in str(exc).lower():
            raise
        rows = [
            row for row in classification_rows(conn, max_hr=max_hr)
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
            "max_hr_bpm": max_hr,
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


def dashboard_card(summary: dict[str, Any]) -> dict[str, Any]:
    """Compact Today-card fields derived from one activity summary.

    The card and the longevity panel must agree, so the average is the mean of the last four
    weeks' *equivalent* minutes (moderate + 2 * vigorous) -- the quantity the WHO reference
    describes -- and the reference is the shared constant rather than a second copy.
    """
    weeks = summary.get("weeks") or []
    equivalent = [float(week.get("equivalent_minutes") or 0.0) for week in weeks][-4:]
    return {
        "average_weekly_minutes": round(statistics.mean(equivalent), 1) if equivalent else None,
        "sessions": sum(int(week.get("workouts") or 0) for week in weeks),
        "reference_min": int(REFERENCE_MINUTES[0]),
        "reference_max": int(REFERENCE_MINUTES[1]),
    }


def report(conn, *, since: str | None = None, weeks_limit: int = 104) -> dict[str, Any]:
    max_hr = configured_max_hr(conn)
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
    covered_seconds = 0.0
    workout_seconds = 0.0

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
        zone, tier = classify(workout, average_hr, max_hr=max_hr)
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

        zones = sample_zone_minutes(
            series,
            started_at=workout["started_at"],
            ended_at=workout["ended_at"],
            max_hr=max_hr,
        )
        if zones is not None:
            eligible += 1
            eligible_by_year[str(started.year)] += 1
            covered_seconds += zones.covered_seconds
            workout_seconds += zones.workout_seconds
            for zone_name, value in zones.minutes.items():
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
                zone, _tier = classify(workout, average_hr, max_hr=max_hr)
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
            "max_hr_bpm": max_hr,
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
            "covered_minutes": round(covered_seconds / 60.0, 1),
            "workout_minutes": round(workout_seconds / 60.0, 1),
            "unobserved_minutes": round(
                max(workout_seconds - covered_seconds, 0.0) / 60.0, 1
            ),
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


@dataclass(frozen=True)
class ZoneIntegration:
    """Zone minutes and the interval they actually represent for one workout.

    covered_seconds is the sum of the adjacent-sample intervals that were integrated. It is not
    the workout duration: the first sample opens the series, each interval is attributed to the
    sample that opens it, and the final sample closes no interval. Unobserved time (before the
    first sample, after the last, or across a gap wider than MAX_ZONE_INTEGRATION_GAP_S) is
    excluded rather than extrapolated into a zone.
    """

    minutes: Counter
    covered_seconds: float
    workout_seconds: float
    samples: int

    @property
    def unobserved_seconds(self) -> float:
        return max(self.workout_seconds - self.covered_seconds, 0.0)

    @property
    def temporal_coverage(self) -> float:
        if self.workout_seconds <= 0:
            return 0.0
        return min(self.covered_seconds / self.workout_seconds, 1.0)


def integrate_zone_minutes(
    series: list[tuple[float, float]], *, started_at: str, ended_at: str,
    max_hr: int = DEFAULT_MAX_HR_BPM,
) -> ZoneIntegration | None:
    """Elapsed-time integration of adjacent heart-rate samples, clipped to the workout.

    Methodology: the sample at t describes [t, next_t). The interval is clipped to the workout's
    actual start and end, so a sample recorded just outside the workout cannot extend the covered
    time. A gap wider than MAX_ZONE_INTEGRATION_GAP_S is unobserved and is not allocated to any
    zone. The final sample represents no duration because there is no following sample to bound
    it; this intentionally understates coverage rather than inventing it.

    Returns None for an empty or single-sample series: one sample cannot represent an interval.
    """
    start = dt.datetime.fromisoformat(started_at).timestamp()
    end = dt.datetime.fromisoformat(ended_at).timestamp()
    workout_seconds = end - start
    if workout_seconds <= 0:
        return None
    points = sorted((t, bpm) for t, bpm in series if start <= t <= end)
    if len(points) < 2:
        return None
    out: Counter = Counter()
    covered = 0.0
    for (t0, bpm), (t1, _next_bpm) in zip(points, points[1:], strict=False):
        gap = t1 - t0
        if gap <= 0 or gap > MAX_ZONE_INTEGRATION_GAP_S:
            continue
        lo = max(t0, start)
        hi = min(t1, end)
        if hi <= lo:
            continue
        span = hi - lo
        covered += span
        zone = classify_hr(bpm, max_hr)
        if zone is not None:
            out[zone] += span / 60.0
    return ZoneIntegration(
        minutes=out,
        covered_seconds=covered,
        workout_seconds=workout_seconds,
        samples=len(points),
    )


def sample_zone_minutes(
    series: list[tuple[float, float]], *, started_at: str, ended_at: str,
    max_hr: int = DEFAULT_MAX_HR_BPM,
) -> ZoneIntegration | None:
    """Integrated zone minutes for one workout, or None when its series is not eligible.

    One implementation for both consumers: the per-year time-in-zone report and the longevity
    panel. Whole-workout classification is a different (and more generous) estimate. The
    continuity gate is deliberately separate from temporal coverage: a series can be continuous
    and still cover only half the workout, in which case the missing half is reported as
    unobserved instead of being spread over the samples that exist.
    """
    duration_s = (
        dt.datetime.fromisoformat(ended_at) - dt.datetime.fromisoformat(started_at)
    ).total_seconds()
    if not series or duration_s <= 0:
        return None
    ok, _median = continuity([t for t, _bpm in series], int(duration_s))
    if not ok:
        return None
    return integrate_zone_minutes(
        series, started_at=started_at, ended_at=ended_at, max_hr=max_hr,
    )


def time_in_zone(conn, *, on_date: str | None = None, days: int = 28) -> dict[str, Any]:
    """Sample-based zone minutes over a calendar window, with its own coverage.

    This covers only continuity-eligible workouts, so it is reported as its own block and never
    merged into the weekly total. Hidden workouts are excluded like everywhere else. Two
    coverages are reported: the share of workouts whose series is continuity-eligible, and the
    share of eligible workout time represented by integrated samples.
    """
    anchor = _as_of_date(on_date)
    max_hr = configured_max_hr(conn, on_date=anchor.isoformat())
    first = anchor - dt.timedelta(days=days - 1)
    hidden = hidden_workout_ids(conn)
    in_window: list[dict[str, Any]] = []
    for row in conn.execute("SELECT * FROM external_workout"):
        workout = dict(row)
        if workout["external_workout_id"] in hidden:
            continue
        ended = dt.datetime.fromisoformat(workout["ended_at"]).astimezone(
            ZoneInfo("Europe/London")
        ).date()
        if first <= ended <= anchor:
            in_window.append(workout)
    series_by_workout = hr_values_for(
        conn, [workout["external_workout_id"] for workout in in_window]
    )
    totals: Counter = Counter()
    with_series = 0
    eligible = 0
    covered_seconds = 0.0
    workout_seconds = 0.0
    for workout in in_window:
        series = series_by_workout.get(workout["external_workout_id"], [])
        if not series:
            continue
        with_series += 1
        zones = sample_zone_minutes(
            series,
            started_at=workout["started_at"],
            ended_at=workout["ended_at"],
            max_hr=max_hr,
        )
        if zones is None:
            continue
        eligible += 1
        totals.update(zones.minutes)
        covered_seconds += zones.covered_seconds
        workout_seconds += zones.workout_seconds
    return {
        "window": {"start": first.isoformat(), "end": anchor.isoformat(), "days": days},
        "workouts_with_series": with_series,
        "eligible_workouts": eligible,
        "coverage_share": round(eligible / with_series, 3) if with_series else 0.0,
        "covered_minutes": round(covered_seconds / 60.0, 1),
        "workout_minutes": round(workout_seconds / 60.0, 1),
        "unobserved_minutes": round(max(workout_seconds - covered_seconds, 0.0) / 60.0, 1),
        "temporal_coverage_share": (
            round(min(covered_seconds / workout_seconds, 1.0), 3) if workout_seconds else 0.0
        ),
        "minutes": {zone: round(totals[zone], 1) for zone in ZONES},
        "equivalent_minutes": round(totals["moderate"] + 2 * totals["vigorous"], 1),
        "method": (
            "elapsed time between adjacent heart-rate samples, clipped to the workout; "
            "gaps over 120 s and the final sample are not allocated"
        ),
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
            "method": None,
            "age_days": None,
        }
    measured = dt.date.fromisoformat(str(row["measured_on"]))
    age_days = (today - measured).days
    return {
        "status": "stale" if age_days > stale_days else "current",
        "value": round(float(row["value"]), 1),
        "unit": str(row.get("unit") or "ml/kg/min"),
        "measured_on": measured.isoformat(),
        # source is the provenance class (device/config); method is the recording app or
        # algorithm that produced the estimate. Both are reported when the row has them.
        "source": row.get("source"),
        "method": row.get("method"),
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
        elif equivalent > ref_max:
            # Above the band is its own state. The upper bound is contextual, not a maximum safe
            # dose, so this is never described as excessive or harmful.
            relation = "above"
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
