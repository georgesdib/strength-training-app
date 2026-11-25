"""Shadow comparison of baseline methods. Nothing here changes a score or a load.

The shipped baseline is a rolling median. This report also projects the same prior readings
with a log-linear trend (a simple learned baseline) and reports how far the normalised device
values would move. It is a diagnostic, not a second prescription path.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics

from strength_coach.features import readiness_registry
from strength_coach.store import queries


def _normalised(value: float, baseline: float, direction: str, slope: float) -> float:
    ratio = value / baseline
    delta = ratio - 1.0 if direction == "higher" else 1.0 - ratio
    return max(0.0, min(1.0, 0.5 + delta / (2.0 * slope)))


def _projection(history: list[dict], field: str, target: dt.date,
                minimum: int) -> float | None:
    points: list[tuple[int, float]] = []
    first: dt.date | None = None
    for row in history:
        try:
            day = dt.date.fromisoformat(str(row["on_date"]))
            value = float(row.get(field))
        except (KeyError, TypeError, ValueError):
            continue
        if value <= 0:
            continue
        first = first or day
        points.append(((day - first).days, math.log(value)))
    if len(points) < minimum:
        return None
    n = len(points)
    sx = sum(x for x, _ in points)
    sy = sum(y for _, y in points)
    sxx = sum(x * x for x, _ in points)
    sxy = sum(x * y for x, y in points)
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    target_x = (target - first).days
    # Extrapolated log trends can explode; a shadow diagnostic must stay in a sane band.
    predicted = math.exp(intercept + slope * target_x)
    median = statistics.median(math.exp(y) for _, y in points)
    return max(median * 0.5, min(median * 1.5, predicted))


def report(conn, end: str | None = None, days: int = 90) -> str:
    end = end or dt.date.today().isoformat()
    summary = readiness_registry.load(conn, end)
    if summary is None:
        return "SHADOW BASELINE — no readiness registry is effective"
    summary_hrv = summary.metric("hrv_ms")
    summary_rhr = summary.metric("rhr_bpm")
    if summary_hrv is None or summary_rhr is None:
        return "SHADOW BASELINE — the registry has no hrv_ms/rhr_bpm metrics"
    boundary = dt.date.fromisoformat(end)
    start = (boundary - dt.timedelta(days=max(0, int(days) - 1))).isoformat()
    dates = queries.readiness_dates(conn, start, end)
    results: dict[str, list[tuple[float, float, float, float]]] = {
        "hrv_ms": [], "rhr_bpm": []
    }
    for day in dates:
        current = queries.readiness_day(conn, day)
        registry = readiness_registry.load(conn, day) or summary
        if not current:
            continue
        for field in ("hrv_ms", "rhr_bpm"):
            metric = registry.metric(field)
            if metric is None or not metric.enabled:
                continue
            history = queries.readiness_history(conn, day, metric.baseline_days)
            try:
                value = float(current.get(field))
            except (TypeError, ValueError):
                continue
            values = []
            for row in history:
                try:
                    number = float(row.get(field))
                except (TypeError, ValueError):
                    continue
                if number > 0:
                    values.append(number)
            minimum = int(metric.min_readings or 1)
            if len(values) < minimum:
                continue
            median = statistics.median(values)
            projected = _projection(history, field, dt.date.fromisoformat(day), minimum)
            if projected is None:
                continue
            direction = "higher" if metric.higher_is_better else "lower"
            slope = float(metric.slope or 0.5)
            results[field].append((
                value,
                _normalised(value, median, direction, slope),
                _normalised(value, projected, direction, slope),
                projected / median,
            ))

    lines = [
        "SHADOW BASELINE — rolling median vs trend-projected (no effect on prescriptions)",
        f"registry v{summary.registry_id}; window {summary_hrv.baseline_days} d; "
        f"minimum {summary_hrv.min_readings} readings; "
        f"slope {float(summary_hrv.slope or 0.5):g}/{float(summary_rhr.slope or 0.5):g}",
        f"dates compared: {len(dates)}",
    ]
    for field, label in (("hrv_ms", "HRV"), ("rhr_bpm", "RHR")):
        data = results[field]
        if not data:
            lines.append(f"{label}: no comparable dates")
            continue
        diffs = [abs(median_norm - trend_norm) for _, median_norm, trend_norm, _ in data]
        ratios = [ratio for *_, ratio in data]
        lines.append(
            f"{label}: {len(data)} dates; mean |Δ normalised| {statistics.mean(diffs):.3f}; "
            f"max {max(diffs):.3f}; trend/median ratio {statistics.median(ratios):.3f}"
        )
    lines.append("No prescription uses the trend-projected baseline. This is diagnostic only.")
    return "\n".join(lines)
