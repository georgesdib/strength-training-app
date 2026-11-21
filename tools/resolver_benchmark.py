"""Time the resolver on a database copy or a fixed synthetic fixture.

Real-database mode copies the source database to a temporary directory, enables the resolver
on the copy, and never writes to the source. Synthetic mode reuses the fixed-history
`evaluator_ab` fixtures, so the same inputs can be compared before/after and on another
machine without copying the athlete's data.

    python tools/resolver_benchmark.py --db /path/to/coach.db --runs 10
    python tools/resolver_benchmark.py --synthetic --case secondary_complementarity --runs 10
    python tools/resolver_benchmark.py --synthetic --case straight --runs 10 --json out.json

The deployment target is the ODROID-C4 (see docs/PERFORMANCE-PROFILE.md); absolute seconds on
a laptop are not deployment numbers. The report names the machine and marks the ODROID
measurement pending until the command is run there.
"""

from __future__ import annotations

import argparse
import contextlib
import cProfile
import json
import math
import os
import platform
import pstats
import sqlite3
import statistics
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any
from unittest.mock import patch

from strength_coach import settings_profile
from strength_coach.features import programme as programme_feature
from strength_coach.prescribe import evaluator as evaluator_mod
from strength_coach.prescribe import evaluator_ab, resolver, resolver_policy, role_quality, templates
from strength_coach.prescribe.evaluator import EvaluationInputs
from strength_coach.store import db, importer, repositories


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


def _percentile(samples: list[float], percentile: float) -> float | None:
    """Nearest-rank percentile; deterministic for small repeated-run samples."""
    if not samples:
        return None
    ordered = sorted(samples)
    index = max(0, math.ceil(percentile / 100.0 * len(ordered)) - 1)
    return ordered[index]


def _timed(fn: Callable[[], Any], runs: int) -> dict:
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
        "p95_s": round(_percentile(samples, 95) or 0.0, 3),
        "max_s": round(samples[-1], 3),
        "result": result,
    }


@contextlib.contextmanager
def _counted_build() -> Iterator[tuple[Callable[[], int], Callable[[bool], None]]]:
    """Wrap the evaluator's build call in this process only.

    The production path is untouched: the wrapper exists only for the benchmark and counts one
    call per evaluated finalist. It is never imported by the resolver.
    """
    original = evaluator_mod.build_prescription
    state = {"count": 0, "enabled": False}

    def wrapper(*args, **kwargs):
        if state["enabled"]:
            state["count"] += 1
        return original(*args, **kwargs)

    evaluator_mod.build_prescription = wrapper
    try:
        yield lambda: state["count"], lambda enabled: state.__setitem__("enabled", enabled)
    finally:
        evaluator_mod.build_prescription = original


def _beam_counts(resolved) -> dict[str, Any]:
    result = resolved.beam
    return {
        "finalist_evaluations": len(result.evaluated),
        "candidate_count": sum(len(pool) for pool in resolved.pools.pools.values()),
        "beam_config": dict(resolved.generated_session.get("beam_config") or {}),
        "truncated": result.truncated,
        "candidate_cap_applied": result.candidate_cap_applied,
        "evaluation_budget_applied": result.evaluation_budget_applied,
        "candidate_ids_removed": result.candidate_ids_removed,
        "pruned": result.pruned,
        "structural_pruned": result.structural_pruned,
        "final_assignments_pruned": result.final_assignments_pruned,
        "exhaustive": result.exhaustive,
    }


def _environment() -> dict[str, Any]:
    return {
        "machine": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
    }


def _synthetic_fixture(name: str) -> tuple[Any, dict, Any, resolver_policy.ResolverPolicy]:
    """Prepare one fixed-history fixture, mirroring evaluator_ab._run_case's inputs."""
    case = evaluator_ab.CASES[name]
    rows = list(case["rows"])
    if case.get("seed"):
        rows += evaluator_ab._seed_rows(case["seed"])
    training = evaluator_ab._training(rows)
    readiness = evaluator_ab._readiness()
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    if case.get("previous"):
        evaluator_ab._previous_workout(
            store.connection, exercise_id=case["previous"]
        )
    if case.get("volume_budget"):
        repositories.append_athlete_profile(
            store.connection, effective_from="2024-01-01",
            volume_budget_enabled=True, main_lift_policy="preserve",
        )
    base = evaluator_ab._full_pools(case) if case.get("slots") else evaluator_ab._pools()
    for slot in base.template.slots:
        for exercise_id in base.pools.get(slot.id, ()):
            repositories.append_exercise_suitability(
                store.connection, exercise_id=exercise_id,
                rated_on="2024-01-01", can_do=True, will_do=True, feels_bad=False,
            )
    _enable_resolver(store.connection, effective_from="2024-01-01")
    policy = resolver_policy.ResolverPolicy.load()
    empty = replace(
        policy,
        required_patterns=MappingProxyType({s: () for s in templates.SESSION_TYPES}),
    )
    return store, case, base, empty


def _synthetic_measure(
    *,
    conn,
    case: dict,
    base,
    policy: resolver_policy.ResolverPolicy,
    runs: int,
    baseline_key: bool,
) -> dict:
    """Time repeated builds with the same fixed fixture.

    `baseline_key` disables the role-quality snapshot to measure the same builds under the
    pre-WP6 selection key. The build inputs and finalist set are unchanged.
    """
    inputs = EvaluationInputs(top_set_intent=case["intent"])
    patchers = [
        patch.object(
            resolver_policy.ResolverPolicy, "load",
            classmethod(lambda cls, path=None: policy),
        ),
        patch.object(resolver.generator, "candidate_pools", lambda *a, **k: base),
    ]
    if baseline_key:
        patchers.append(patch.object(role_quality, "snapshot", lambda **kwargs: None))
    samples: list[float] = []
    cold_s: float | None = None
    counts: dict[str, Any] | None = None
    with contextlib.ExitStack() as stack, _counted_build() as (build_count, set_enabled):
        for patcher in patchers:
            stack.enter_context(patcher)
        for run in range(runs + 1):
            set_enabled(True)
            before = build_count()
            started = time.perf_counter()
            resolved = resolver.build_resolved(
                conn,
                for_date=case.get("for_date", "2024-01-15"),
                session_type=case.get("session_type", "squat"),
                inputs=inputs,
            )
            elapsed = time.perf_counter() - started
            builds = build_count() - before
            set_enabled(False)
            if run == 0:
                cold_s = elapsed
            else:
                samples.append(elapsed)
            counts = {**_beam_counts(resolved), "prescription_builds": builds}
    samples.sort()
    return {
        "cold_start_s": round(cold_s or 0.0, 3),
        "runs": len(samples),
        "min_s": round(samples[0], 3),
        "p50_s": round(statistics.median(samples), 3),
        "p95_s": round(_percentile(samples, 95) or 0.0, 3),
        "max_s": round(samples[-1], 3),
        "counts": counts,
    }


def _synthetic_report(case_name: str, runs: int) -> dict:
    store, case, base, policy = _synthetic_fixture(case_name)
    try:
        corrected = _synthetic_measure(
            conn=store.connection, case=case, base=base, policy=policy,
            runs=runs, baseline_key=False,
        )
        baseline = _synthetic_measure(
            conn=store.connection, case=case, base=base, policy=policy,
            runs=runs, baseline_key=True,
        )
    finally:
        store.close()
    return {
        "evidence": "synthetic fixed-history fixture; no real training data",
        "case": case_name,
        "environment": _environment(),
        "fixture": {
            "for_date": case.get("for_date", "2024-01-15"),
            "session_type": case.get("session_type", "squat"),
            "template": "full" if case.get("slots") else "legacy",
            "volume_budget": bool(case.get("volume_budget")),
            "candidate_pools": {
                slot: list(exercises)
                for slot, exercises in base.pools.items()
            },
        },
        "corrected": corrected,
        "baseline_same_inputs": baseline,
        "odroid_measurement": (
            "pending: run this command on the ODROID-C4; laptop seconds are not a "
            "deployment number"
        ),
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


def _real_report(args) -> dict:
    try:
        target, staging = _copy_database(args.db)
    except sqlite3.DatabaseError as exc:
        raise SystemExit(f"not a readable SQLite database: {args.db}: {exc}") from exc
    counter = contextlib.ExitStack()
    try:
        store = db.Store(target)
        conn = store.connection
        _enable_resolver(conn, effective_from="2000-01-01")

        build_count, set_enabled = counter.enter_context(_counted_build())

        def build():
            set_enabled(True)
            before = build_count()
            resolved = resolver.build_resolved(
                conn,
                for_date=args.date,
                session_type=args.session_type,
                inputs=EvaluationInputs(
                    minimum_target_minutes=args.minimum_target_minutes,
                    top_set_intent="off",
                ),
            )
            builds = build_count() - before
            set_enabled(False)
            return resolved, [item.exercise_id for item in resolved.prescription.items], builds

        cold_started = time.perf_counter()
        warm, _items, warm_builds = build()
        cold_s = time.perf_counter() - cold_started
        resolver_run = _timed(build, max(1, args.runs))
        resolved, items, builds = resolver_run["result"]

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
            "evidence": "real database copy; never written",
            "environment": _environment(),
            "database": str(args.db),
            "resolver": {
                "date": args.date,
                "session_type": args.session_type,
                "cold_start_s": round(cold_s, 3),
                "runs": resolver_run["runs"],
                "min_s": resolver_run["min_s"],
                "p50_s": resolver_run["p50_s"],
                "p95_s": resolver_run["p95_s"],
                "max_s": resolver_run["max_s"],
                "counts": {
                    **_beam_counts(resolved),
                    "prescription_builds": builds,
                    "warm_builds": warm_builds,
                },
            },
            "items": items,
            "odroid_measurement": (
                "pending: run this command on the ODROID-C4; laptop seconds are not a "
                "deployment number"
            ),
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
        return report
    finally:
        counter.close()
        staging.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, help="source database (copied, never written)")
    parser.add_argument(
        "--synthetic", action="store_true",
        help="use a fixed evaluator_ab fixture instead of a database copy",
    )
    parser.add_argument(
        "--case", default="secondary_complementarity",
        choices=sorted(evaluator_ab.CASES),
        help="synthetic fixture case",
    )
    parser.add_argument("--date", default="2026-11-04", help="prescription date (real DB mode)")
    parser.add_argument("--session-type", default="squat")
    parser.add_argument("--minimum-target-minutes", type=int, default=30)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--forecast-weeks", type=int, default=0, help="also time a forecast of N weeks")
    parser.add_argument(
        "--profile", type=Path, default=None,
        help="also profile one build, write the pstats dump here and print a summary",
    )
    parser.add_argument("--json", type=Path, default=None, help="write the report to a JSON file")
    args = parser.parse_args()

    if not args.synthetic and args.db is None:
        parser.error("pass --db or --synthetic")
    if args.db is not None and not args.db.is_file():
        parser.error(f"database not found: {args.db}")

    report = (
        _synthetic_report(args.case, max(1, args.runs))
        if args.synthetic else _real_report(args)
    )
    body = json.dumps(report, indent=2)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(body, encoding="utf-8")
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
