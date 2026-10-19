"""Back-progression summary: evidence for a suitability review, never a clearance.

It exists because the athlete asked whether a "strong and recovered" back could unlock a lift.
The app has no medical model. What it can do is count symptom-free time and tolerated spinal
loading, state what it used, disclaim it, and recommend that the athlete review a rating. It may
never set `exercise_suitability` or clear a constraint (DEC-BACKSIGNAL-01).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from strength_coach.rules.context import flare_from
from strength_coach.store import queries
from strength_coach.utils import exercises

DISCLAIMER = (
    "Not medical clearance. A symptom-free streak is weak evidence; the athlete decides, and "
    "a clinician should be involved if there is doubt."
)


@dataclass(frozen=True)
class BackSignal:
    status: str                 # unknown | insufficient | monitoring | review
    summary: str
    symptom_free_days: int | None
    last_flare_on: str | None
    loaded_sessions: int
    ramp_week: int | None
    recommendation: str | None
    disclaimer: str = DISCLAIMER

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "summary": self.summary,
            "symptom_free_days": self.symptom_free_days,
            "last_flare_on": self.last_flare_on,
            "loaded_sessions": self.loaded_sessions,
            "ramp_week": self.ramp_week,
            "recommendation": self.recommendation,
            "disclaimer": self.disclaimer,
        }


def _days_between(start: str, end: str) -> int:
    return (dt.date.fromisoformat(end[:10]) - dt.date.fromisoformat(start[:10])).days


def compute(conn, on_date: str, thresholds, *, ramp_week: int | None = None) -> BackSignal:
    entries = [e for e in queries.symptom_entries(conn) if str(e["logged_on"]) <= on_date]
    if not entries:
        return BackSignal(
            "unknown", "no symptom entries, so nothing can be said", None, None, 0,
            ramp_week, None,
        )

    latest = entries[-1]
    age = _days_between(str(latest["logged_on"]), on_date)
    flares = [e for e in entries if flare_from(int(e["level"]), e["settled_within_48h"])]
    last_flare = str(flares[-1]["logged_on"]) if flares else None
    level = int(latest["level"])

    if level > 0:
        streak = 0
        summary = f"latest reading is level {level}; no symptom-free streak to count"
    else:
        start = last_flare or str(entries[0]["logged_on"])
        streak = max(0, _days_between(start, on_date))
        summary = f"{streak} days since the last flare (or first clean entry)"

    if age > thresholds.back_signal_max_entry_age_days:
        return BackSignal(
            "insufficient",
            f"last symptom entry is {age} days old; log a reading to make this meaningful",
            streak, last_flare, 0, ramp_week, None,
        )

    high_fatigue = {
        eid for eid, entity in exercises.taxonomy().entities.items()
        if entity.get("high_fatigue_spinal")
    }
    loaded = 0
    if high_fatigue:
        start = last_flare or str(entries[0]["logged_on"])
        placeholders = ",".join("?" for _ in high_fatigue)
        row = conn.execute(
            f"SELECT COUNT(DISTINCT occurred_on) AS n FROM clean_set "
            f"WHERE occurred_on > ? AND occurred_on <= ? AND exercise_id IN ({placeholders})",
            (start, on_date, *sorted(high_fatigue)),
        ).fetchone()
        loaded = int(row["n"]) if row is not None else 0

    if (streak >= thresholds.back_signal_symptom_free_days
            and loaded >= thresholds.back_signal_min_loaded_sessions):
        return BackSignal(
            "review",
            f"{streak} days symptom-free with {loaded} loaded spinal sessions since the last flare",
            streak, last_flare, loaded, ramp_week,
            "consider reviewing the suitability of any unrated lift; the athlete still decides",
        )

    return BackSignal(
        "monitoring",
        f"{summary}; {loaded} loaded spinal sessions since the last flare",
        streak, last_flare, loaded, ramp_week, None,
    )
