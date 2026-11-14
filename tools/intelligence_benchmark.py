"""Synthetic performance baseline for get_training_overview.

Creates a disposable database with a realistic shape (several sessions a week, three sets per
exercise, six exercises, readiness on most days), then times the capability through the same
read-only path the MCP server uses. No real training data is read or written.

    python tools/intelligence_benchmark.py --sessions 200 --runs 40
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import platform
import statistics
import tempfile
import time
from pathlib import Path

import pandas as pd

from strength_coach.intelligence import INTERNAL_PRINCIPAL, IntelligenceConfig, IntelligenceService
from strength_coach.intelligence.mcp.db import connect_readonly
from strength_coach.store import db, importer

EXERCISES = (
    ("Competition Squat", "Quadriceps"),
    ("Competition Bench Press", "Chest"),
    ("Trap Bar Deadlift", "Hamstrings"),
    ("Romanian Deadlift", "Hamstrings"),
    ("Overhead Press", "Shoulders"),
    ("Barbell Row", "Back"),
)

TRAINING_COLUMNS = {
    "Workout": "Synthetic",
    "Weight_Units": "kg",
    "ExertionLoad": "0.0",
    "Mechanics": "Compound",
    "Force": "Push",
    "Avg_velocity": "0.000000",
    "Avg_power": "0",
    "Avg_rom": "0",
    "TUT": "0",
    "Form": "0",
    "Video": "",
}

READINESS_COLUMNS = {
    "Sleep": "4",
    "Energy": "4",
    "Mood": "4",
    "Soreness": "2",
    "Stress": "2",
    "Squat_Readiness": "4",
    "Bench_Readiness": "4",
    "Deadlift_Readiness": "4",
    "HRV": "0",
    "RHR": "0",
    "Weight": "80.0",
    "Fat_Percent": "20.0",
}


def _frames(sessions: int) -> tuple[pd.DataFrame, pd.DataFrame, dt.date]:
    # Spread the history over a fixed span ending yesterday, so the as-of date is never in the
    # future and a longer run means more density, not a longer calendar.
    end = dt.date.today() - dt.timedelta(days=1)
    span_days = min(1100, max(90, sessions * 2))
    start = end - dt.timedelta(days=span_days)
    training_rows: list[dict[str, str]] = []
    readiness_rows: list[dict[str, str]] = []
    last_day = start
    for index in range(sessions):
        day = start + dt.timedelta(days=(index * span_days) // max(1, sessions - 1))
        last_day = day
        base = 60.0 + 20.0 * math.sin(index / 11.0) + index * 0.15
        for offset, (exercise, muscle) in enumerate(EXERCISES):
            for set_index in range(3):
                training_rows.append({
                    "Date": day.isoformat(),
                    "Exercise": exercise,
                    "Main_Muscle": muscle,
                    "Weight_Used": f"{base + offset * 10 + set_index * 2.5:.1f}",
                    "Reps_Done": "5",
                    "RIR": "2",
                    **TRAINING_COLUMNS,
                })
        if index % 2 == 0:
            readiness_rows.append({"Date": day.isoformat(), **READINESS_COLUMNS})
    training = pd.DataFrame(training_rows).astype(str)
    readiness = pd.DataFrame(readiness_rows).astype(str)
    return training, readiness, last_day


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def run(sessions: int, runs: int, window_weeks: int) -> dict[str, object]:
    training, readiness, last_day = _frames(sessions)
    with tempfile.TemporaryDirectory(prefix="intelligence-bench-") as directory:
        path = Path(directory) / "coach.db"
        store = db.Store(path)
        try:
            importer.import_export(
                store.connection,
                training,
                readiness,
                training_sha256=importer.sha256_frame(training),
                readiness_sha256=importer.sha256_frame(readiness),
            )
        finally:
            store.close()

        config = IntelligenceConfig(enabled=True)
        durations: list[float] = []
        statuses: list[str] = []
        connection = connect_readonly(path)
        try:
            service = IntelligenceService(connection, config=config)
            arguments = {"as_of": last_day.isoformat(), "window_weeks": window_weeks}
            for _ in range(runs):
                started = time.perf_counter()
                result = service.execute(
                    INTERNAL_PRINCIPAL, "get_training_overview", arguments
                )
                durations.append((time.perf_counter() - started) * 1000)
                if not result.ok:
                    raise SystemExit(f"benchmark call failed: {result.error}")
                statuses.append(result.envelope.status)
        finally:
            connection.close()

        size_mb = path.stat().st_size / (1024 * 1024)

    return {
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpu_count": platform.machine() and (os_cpu_count() or 0),
        },
        "dataset": {
            "sessions": sessions,
            "sets": int(len(training)),
            "exercises": len(EXERCISES),
            "readiness_days": int(len(readiness)),
            "database_mb": round(size_mb, 2),
        },
        "execution": {
            "capability": "get_training_overview",
            "window_weeks": window_weeks,
            "runs": runs,
            "statuses": sorted(set(statuses)),
            "p50_ms": round(_percentile(durations, 0.50), 1),
            "p95_ms": round(_percentile(durations, 0.95), 1),
            "max_ms": round(max(durations), 1),
            "mean_ms": round(statistics.mean(durations), 1),
        },
    }


def os_cpu_count() -> int | None:
    import os

    return os.cpu_count()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=int, default=200)
    parser.add_argument("--runs", type=int, default=40)
    parser.add_argument("--window-weeks", type=int, default=4)
    parser.add_argument("--json", action="store_true", help="print JSON only")
    args = parser.parse_args(argv)
    report = run(args.sessions, args.runs, args.window_weeks)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    print("dataset:", report["dataset"])
    print("environment:", report["environment"])
    print("execution:", report["execution"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
