"""Time the resolver and the programme forecast on a database copy.

This is the A/B harness for the hot-path work recorded in docs/PERFORMANCE-PROFILE.md. It never
writes to the source database: the file is copied to a temporary directory, the resolver flag is
enabled on the copy, and every build runs there.

    python tools/resolver_benchmark.py --db /path/to/coach.db --runs 5
    python tools/resolver_benchmark.py --db /path/to/coach.db --date 2026-11-04 \
        --session-type squat --forecast-weeks 2

The deployment target is the ODROID-C4 (see §2 and §9 of the profile); absolute seconds on a
laptop are not deployment numbers, so report the machine with the result.
"""

from __future__ import annotations

import argparse
import cProfile
import json
import platform
import pstats
import sqlite3
import statistics
import tempfile
import time
from pathlib import Path

from strength_coach import settings_profile
from strength_coach.features import programme as programme_feature
from strength_coach.prescribe import resolver
from strength_coach.prescribe.evaluator import EvaluationInputs
from strength_coach.store import db


def _copy_database(source: Path) -> tuple[Path, tempfile.TemporaryDirectory]:
    """SQLite backup, not a file copy: a WAL database copied by shutil can miss committed pages."""
    staging = tempfile.TemporaryDirectory(prefix="resolver-bench-")
    target = Path(staging.name) / "coach.db"
    with (
        sqlite3.connect(f"file:{source}?mode=ro", uri=True) as origin,
        sqlite3.connect(target) as copy,
    ):
        origin.backup(copy)
    return target, staging


def _enable_resolver(conn, effective_from: str) -> None:
    settings_profile.save(
        conn,
        set_values={"resolver.enabled": True},
        resolver_enable_confirmed=True,
        effective_from=effective_from,
    )


def _timed(fn, runs: int) -> dict:
    samples: list[float] = []
    result = None
    for _ in range(runs):
        started = time.perf_counter()
        result = fn()
        samples.append(time.perf_counter() - started)
    samples.sort()
    return {
        "runs": runs,
        "min_s": round(samples[0], 3),
        "p50_s": round(statistics.median(samples), 3),
        "max_s": round(samples[-1], 3),
        "result": result,
    }


def _category(source: str) -> str:
    if source.startswith("{") or source == "~":
        return "c/builtin"
    if "/site-packages/pandas" in source or "/site-packages/numpy" in source:
        return "pandas/numpy python-level"
    if "/site-packages/yaml" in source:
        return "pyyaml"
    if "strength_coach" in source:
        return "strength_coach"
    if "/lib/python" in source or "python3." in source:
        return "stdlib"
    return "other"


def _profile_summary(profiler: cProfile.Profile, limit: int = 20) -> dict:
    """Where a build spends its time, grouped the way section 11 of the profile reports it."""
    stats = pstats.Stats(profiler)
    total = stats.total_tt or 1e-9
    categories: dict[str, float] = {}
    rows: list[tuple[float, float, int, str, int, str]] = []
    for (source, line, func), (_cc, calls, own, cumulative, _callers) in stats.stats.items():
        categories[_category(source or "")] = (
            categories.get(_category(source or ""), 0.0) + own
        )
        rows.append((cumulative, own, calls, source or "", line, func))
    coach = [row for row in rows if "strength_coach" in row[3]]
    coach.sort(key=lambda row: row[0], reverse=True)
    return {
        "profiled_s": round(stats.total_tt, 3),
        "categories": {
            name: round(100 * seconds / total, 1)
            for name, seconds in sorted(categories.items(), key=lambda kv: -kv[1])
        },
        "top_strength_coach": [
            {
                "cum_s": round(cumulative, 3),
                "own_s": round(own, 3),
                "calls": calls,
                "where": f"{source.split('strength_coach/')[-1]}:{line} {func}",
            }
            for cumulative, own, calls, source, line, func in coach[:limit]
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="source database (copied, never written)")
    parser.add_argument("--date", default="2026-11-04", help="prescription date")
    parser.add_argument("--session-type", default="squat")
    parser.add_argument("--minimum-target-minutes", type=int, default=30)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--forecast-weeks", type=int, default=0, help="also time a forecast of N weeks")
    parser.add_argument(
        "--profile",
        type=Path,
        default=None,
        help="also profile one build, write the pstats dump here and print a summary",
    )
    args = parser.parse_args()

    if not args.db.is_file():
        parser.error(f"database not found: {args.db}")

    try:
        target, staging = _copy_database(args.db)
    except sqlite3.DatabaseError as exc:
        parser.error(f"not a readable SQLite database: {args.db}: {exc}")
    try:
        store = db.Store(target)
        conn = store.connection
        _enable_resolver(conn, effective_from="2000-01-01")

        def build():
            resolved = resolver.build_resolved(
                conn,
                for_date=args.date,
                session_type=args.session_type,
                inputs=EvaluationInputs(
                    minimum_target_minutes=args.minimum_target_minutes,
                    top_set_intent="off",
                ),
            )
            return [item.exercise_id for item in resolved.prescription.items]

        build()  # warm process-wide caches; not measured
        resolver_run = _timed(build, max(1, args.runs))

        profiled: dict | None = None
        if args.profile is not None:
            profiler = cProfile.Profile()
            profiler.enable()
            build()
            profiler.disable()
            args.profile.parent.mkdir(parents=True, exist_ok=True)
            profiler.dump_stats(str(args.profile))
            profiled = _profile_summary(profiler)

        report: dict = {
            "environment": {
                "machine": platform.platform(),
                "processor": platform.processor() or platform.machine(),
                "python": platform.python_version(),
            },
            "database": str(args.db),
            "resolver": {
                "date": args.date,
                "session_type": args.session_type,
                **{k: v for k, v in resolver_run.items() if k != "result"},
            },
            "items": resolver_run["result"],
        }
        if profiled is not None:
            report["profile"] = {"dump": str(args.profile), **profiled}

        if args.forecast_weeks:
            def forecast():
                entries = programme_feature.build_programme(
                    conn, start=args.date, weeks=args.forecast_weeks, per_week=3
                )
                return len(entries)

            forecast()
            report["forecast"] = {
                "weeks": args.forecast_weeks,
                **_timed(forecast, max(1, args.runs)),
            }

        store.close()
        print(json.dumps(report, indent=2))
        return 0
    finally:
        staging.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
