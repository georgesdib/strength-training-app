
"""Benchmark every registered Intelligence capability, directly and over MCP HTTP.

The original benchmark timed only get_training_overview through IntelligenceService on synthetic
data. This version discovers the registry, builds valid arguments from the benchmark database,
runs direct execution and (optionally) the real Streamable HTTP transport with the official MCP
client, and reports latency distributions and errors per capability.

Synthetic mode (default) is self-contained. Real mode opens an existing database read-only and
never builds, migrates or mutates source data.

    python tools/intelligence_benchmark.py --sessions 200 --runs 30
    python tools/intelligence_benchmark.py --mode both --url http://127.0.0.1:8765/mcp \
        --token-env STRENGTH_MCP_TOKEN --sessions 200 --runs 30
    python tools/intelligence_benchmark.py --db /path/to/copied/coach.db --runs 30
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as dt
import json
import math
import os
import platform
import statistics
import tempfile
import time
from pathlib import Path

import pandas as pd

from strength_coach.intelligence import (
    INTERNAL_PRINCIPAL,
    IntelligenceConfig,
    IntelligenceService,
)
from strength_coach.intelligence import capabilities as _capabilities  # noqa: F401 (registers)
from strength_coach.intelligence.mcp.db import connect_readonly
from strength_coach.intelligence.registry import CAPABILITIES
from strength_coach.store import db, importer
from strength_coach.utils import exercises as exercise_taxonomy

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

DEFAULT_URL = "http://127.0.0.1:8765/mcp"


def _frames(sessions: int) -> tuple[pd.DataFrame, pd.DataFrame, dt.date]:
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


def statistics_for(durations: list[float]) -> dict[str, float | int]:
    if not durations:
        return {"n": 0}
    return {
        "n": len(durations),
        "p50_ms": round(_percentile(durations, 0.50), 1),
        "p95_ms": round(_percentile(durations, 0.95), 1),
        "max_ms": round(max(durations), 1),
        "mean_ms": round(statistics.mean(durations), 1),
    }


def dataset_metadata(
    path: Path, sessions: int, sets: int, readiness: int, *, source: str
) -> dict:
    return {
        "source": source,
        "sessions": sessions,
        "sets": sets,
        "readiness_days": readiness,
        "database_mb": round(path.stat().st_size / (1024 * 1024), 2) if path.exists() else None,
    }


def environment_metadata() -> dict:
    import os

    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count() or 0,
    }


def _first_session(conn) -> str | None:
    row = conn.execute(
        "SELECT session_id FROM session WHERE voided = 0 ORDER BY occurred_on DESC LIMIT 1"
    ).fetchone()
    return None if row is None else str(row[0])


def _first_exercise(conn) -> str | None:
    entities = exercise_taxonomy.taxonomy().entities
    rows = conn.execute(
        "SELECT DISTINCT exercise_id FROM clean_set WHERE voided = 0 "
        "AND NOT EXISTS (SELECT 1 FROM clean_set child WHERE child.supersedes_id = clean_set.set_id) "
        "ORDER BY occurred_on DESC"
    ).fetchall()
    for row in rows:
        candidate = str(row[0])
        if candidate in entities:
            return candidate
    return None


def build_arguments(
    conn, day: dt.date, *, window_weeks: int = 4
) -> tuple[dict[str, dict], dict[str, str]]:
    """Valid arguments for every registered capability, plus explicit unsupported reasons."""
    as_of = day.isoformat()
    start_90 = (day - dt.timedelta(days=90)).isoformat()
    end_a = (day - dt.timedelta(days=28)).isoformat()
    start_a = (day - dt.timedelta(days=55)).isoformat()
    session_id = _first_session(conn)
    exercise_id = _first_exercise(conn)
    arguments: dict[str, dict] = {}
    unsupported: dict[str, str] = {}

    for name in CAPABILITIES.names():
        if name == "get_training_overview":
            arguments[name] = {"as_of": as_of, "window_weeks": window_weeks}
        elif name == "get_exercise_progression":
            if not exercise_id:
                unsupported[name] = "benchmark database has no clean sets"
            else:
                arguments[name] = {"exercise_id": exercise_id, "as_of": as_of}
        elif name == "get_readiness_history":
            arguments[name] = {"from": start_90, "to": as_of}
        elif name == "get_adherence_analysis":
            arguments[name] = {"as_of": as_of, "weeks": 8}
        elif name == "get_prescription":
            arguments[name] = {"for_date": as_of}
        elif name == "get_session_details":
            if not session_id:
                unsupported[name] = "benchmark database has no completed session"
            else:
                arguments[name] = {"session_id": session_id}
        elif name == "get_vbt_analysis":
            if not exercise_id:
                unsupported[name] = "benchmark database has no clean sets"
            else:
                arguments[name] = {
                    "exercise_id": exercise_id, "from": start_90, "to": as_of,
                }
        elif name == "get_programme_block_summary":
            arguments[name] = {"as_of": as_of}
        elif name == "get_weekly_review":
            arguments[name] = {
                "week_end": (day - dt.timedelta(days=day.weekday() + 1)).isoformat(),
            }
        elif name == "compare_training_periods":
            arguments[name] = {
                "period_a": {"start": start_a, "end": end_a},
                "period_b": {"start": end_a, "end": as_of},
                "metric": "attendance",
            }
        else:
            unsupported[name] = "no benchmark argument builder for this capability"
    return arguments, unsupported


def http_arguments(arguments: dict[str, dict]) -> dict[str, dict]:
    """Translate capability payloads to the MCP tool input schemas.

    Most tools mirror the capability fields, but readiness and VBT expose start/end while their
    capability payloads use from/to. Passing the wrong names is rejected by tool validation and
    would measure a fast error, not the capability.
    """
    out: dict[str, dict] = {}
    for name, payload in arguments.items():
        if name == "get_readiness_history":
            out[name] = {"start": payload["from"], "end": payload["to"]}
        elif name == "get_vbt_analysis":
            out[name] = {
                "start": payload["from"],
                "end": payload["to"],
                "exercise_id": payload.get("exercise_id"),
            }
        else:
            out[name] = payload
    return out


def _direct_call(service, name: str, arguments: dict) -> tuple[float, str | None, str | None]:
    started = time.perf_counter()
    try:
        result = service.execute(INTERNAL_PRINCIPAL, name, arguments)
    except Exception as exc:  # pragma: no cover - defensive for a benchmark
        return (time.perf_counter() - started) * 1000, "exception", f"{type(exc).__name__}: {exc}"
    elapsed = (time.perf_counter() - started) * 1000
    if not result.ok:
        return elapsed, "error", str(result.error)
    return elapsed, None, result.envelope.status


def run_direct(
    path: Path,
    arguments: dict[str, dict],
    unsupported: dict[str, str],
    *,
    iterations: int,
    warmup: int,
) -> dict:
    config = IntelligenceConfig(enabled=True)
    connection = connect_readonly(path)
    try:
        service = IntelligenceService(connection, config=config)
        results: dict[str, dict] = {}
        for name in sorted(set(arguments) | set(unsupported)):
            if name in unsupported:
                results[name] = {"benchmarked": False, "reason": unsupported[name]}
                continue
            samples: list[float] = []
            errors: list[str] = []
            status_counts: dict[str, int] = {}
            for _ in range(max(0, warmup)):
                _direct_call(service, name, arguments[name])
            for _ in range(iterations):
                elapsed, error, detail = _direct_call(service, name, arguments[name])
                if error:
                    errors.append(f"{error}: {detail}")
                else:
                    samples.append(elapsed)
                    status_counts[str(detail)] = status_counts.get(str(detail), 0) + 1
            entry = {
                "benchmarked": True,
                "arguments": arguments[name],
                "measured": iterations,
                "success": len(samples),
                "errors": len(errors),
                "error_examples": errors[:3],
                "status_counts": status_counts,
                **statistics_for(samples),
            }
            results[name] = entry
        return {"results": results}
    finally:
        connection.close()


@contextlib.asynccontextmanager
async def _http_session(url: str, token: str, timeout: float):
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx2.AsyncClient(headers=headers, timeout=timeout) as http_client:
        transport = streamable_http_client(url, http_client=http_client)
        async with Client(transport) as client:
            yield client


async def _run_http_async(
    url: str,
    token: str,
    timeout: float,
    arguments: dict[str, dict],
    unsupported: dict[str, str],
    *,
    iterations: int,
    warmup: int,
) -> dict:
    results: dict[str, dict] = {}
    translated = http_arguments(arguments)
    try:
        async with _http_session(url, token, timeout) as client:
            tools = await client.list_tools()
            available = {tool.name for tool in tools.tools}
            for name in sorted(set(arguments) | set(unsupported)):
                if name in unsupported:
                    results[name] = {"benchmarked": False, "reason": unsupported[name]}
                    continue
                if name not in available:
                    results[name] = {
                        "benchmarked": False,
                        "reason": "not exposed by the server's tools/list",
                    }
                    continue
                samples: list[float] = []
                errors: list[str] = []
                for _ in range(max(0, warmup)):
                    with contextlib.suppress(Exception):
                        await client.call_tool(name, translated[name])
                for _ in range(iterations):
                    started = time.perf_counter()
                    try:
                        result = await client.call_tool(name, translated[name])
                        elapsed = (time.perf_counter() - started) * 1000
                        # mcp >= 2 names this is_error; the old isError spelling silently
                        # counted every tool error as a successful sample.
                        if getattr(result, "is_error", False) or getattr(
                            result, "isError", False
                        ):
                            errors.append("tool_error")
                        else:
                            samples.append(elapsed)
                    except Exception as exc:
                        errors.append(f"{type(exc).__name__}: {exc}")
                results[name] = {
                    "benchmarked": True,
                    "measured": iterations,
                    "success": len(samples),
                    "errors": len(errors),
                    "error_examples": errors[:3],
                    **statistics_for(samples),
                }
            return {"tools": sorted(available), "results": results}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "results": results}


def run_http(
    url: str,
    token: str,
    timeout: float,
    arguments: dict[str, dict],
    unsupported: dict[str, str],
    *,
    iterations: int,
    warmup: int,
) -> dict:
    return asyncio.run(
        _run_http_async(
            url, token, timeout, arguments, unsupported,
            iterations=iterations, warmup=warmup,
        )
    )


def _analytics_state(path: Path) -> dict:
    """Readiness snapshot from a read-only connection; never builds."""
    from strength_coach.analytics import core as derived_core
    from strength_coach.analytics import status_snapshot

    conn = connect_readonly(path)
    try:
        snapshot = status_snapshot(
            conn, {derived_core.CORE_SPEC.family: derived_core.spec()}
        )
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    finally:
        conn.close()
    families = snapshot.get("families") or []
    core = next((row for row in families if row.get("family") == "core"), None)
    return {
        "revision": snapshot.get("revision"),
        "core_ready": bool(core and core.get("ready")),
        "core_status": core.get("status") if core else None,
        "readiness": core.get("readiness") if core else None,
    }


def _margin(http: dict, direct: dict) -> float | None:
    if not http.get("benchmarked") or not direct.get("benchmarked"):
        return None
    if not http.get("p50_ms") or not direct.get("p50_ms"):
        return None
    return round(float(http["p50_ms"]) - float(direct["p50_ms"]), 1)


def _summarise(report: dict) -> None:
    print("capability                         direct p50/p95 ms      http p50/p95 ms      overhead ms")
    for name in sorted(report["capabilities"]):
        row = report["capabilities"][name]
        direct = row.get("direct") or {}
        http = row.get("http") or {}
        print(
            f"{name:34}"
            f"{str(direct.get('p50_ms', '-')) + '/' + str(direct.get('p95_ms', '-')):22}"
            f"{str(http.get('p50_ms', '-')) + '/' + str(http.get('p95_ms', '-')):21}"
            f"{str(row.get('mcp_overhead_p50_ms', '-'))}"
        )


def _redact_arguments(row: dict | None) -> dict | None:
    if row is None:
        return None
    redacted = json.loads(json.dumps(row))
    arguments = redacted.get("arguments")
    if isinstance(arguments, dict):
        for key in ("session_id", "workout_id", "prescription_id"):
            if key in arguments:
                arguments[key] = "<redacted>"
    return redacted


def _build_report(
    *,
    path: Path,
    sessions: int,
    sets: int,
    readiness: int,
    source: str,
    arguments: dict[str, dict],
    unsupported: dict[str, str],
    direct: dict | None,
    http: dict | None,
    iterations: int,
    warmup: int,
    threshold_ms: float,
    url: str | None,
    http_error: str | None = None,
) -> dict:
    names = sorted(set(arguments) | set(unsupported))
    capabilities: dict[str, dict] = {}
    for name in names:
        direct_row = _redact_arguments((direct or {}).get("results", {}).get(name))
        http_row = _redact_arguments((http or {}).get("results", {}).get(name))
        overhead = _margin(http_row or {}, direct_row or {})
        capabilities[name] = {
            "direct": direct_row,
            "http": http_row,
            "mcp_overhead_p50_ms": overhead,
            "exceeds_threshold": bool(
                direct_row and direct_row.get("p95_ms", 0) > threshold_ms
            ) or bool(http_row and http_row.get("p95_ms", 0) > threshold_ms),
        }
    return {
        "environment": environment_metadata(),
        "dataset": {
            **dataset_metadata(path, sessions, sets, readiness, source=source),
            "analytics": _analytics_state(path),
        },
        "configuration": {
            "iterations": iterations,
            "warmup": warmup,
            "threshold_ms": threshold_ms,
            "mcp_url": url,
            "capabilities": names,
            "unsupported": unsupported,
        },
        "capabilities": capabilities,
        "http_tools": (http or {}).get("tools"),
        "http_error": http_error,
    }


def run(sessions: int, runs: int, window_weeks: int) -> dict:
    """Legacy overview-only entry point retained for existing callers."""
    report = run_extended(
        sessions=sessions,
        iterations=runs,
        warmup=0,
        db_path=None,
        mode="direct",
        url=DEFAULT_URL,
        token=None,
        timeout=15.0,
        only=["get_training_overview"],
        threshold_ms=1000.0,
        build_analytics=True,
        window_weeks=window_weeks,
    )
    direct = report["capabilities"]["get_training_overview"]["direct"]
    return {
        "environment": report["environment"],
        "dataset": {
            key: report["dataset"][key]
            for key in ("sessions", "sets", "exercises", "readiness_days", "database_mb")
            if key in report["dataset"]
        },
        "execution": {
            "capability": "get_training_overview",
            "window_weeks": window_weeks,
            "runs": runs,
            "p50_ms": direct.get("p50_ms"),
            "p95_ms": direct.get("p95_ms"),
            "max_ms": direct.get("max_ms"),
            "mean_ms": direct.get("mean_ms"),
        },
    }


def run_extended(
    *,
    sessions: int,
    iterations: int,
    warmup: int,
    db_path: str | None,
    mode: str,
    url: str,
    token: str | None,
    timeout: float,
    only: list[str] | None,
    threshold_ms: float,
    build_analytics: bool,
    window_weeks: int = 4,
) -> dict:
    tempdir = None
    if db_path is None:
        tempdir = tempfile.TemporaryDirectory(prefix="intelligence-bench-")
        path = Path(tempdir.name) / "coach.db"
        training, readiness, last_day = _frames(sessions)
        store = db.Store(path)
        try:
            importer.import_export(
                store.connection, training, readiness,
                training_sha256=importer.sha256_frame(training),
                readiness_sha256=importer.sha256_frame(readiness),
            )
            if build_analytics:
                from strength_coach.analytics import core

                core.build(store.connection)
        finally:
            store.close()
        set_count = int(len(training))
        readiness_count = int(len(readiness))
    else:
        path = Path(db_path)
        if not path.exists():
            raise SystemExit(f"database not found: {path}")
        last_day = dt.date.today()
        set_count = 0
        readiness_count = 0

    conn = connect_readonly(path)
    try:
        actual_day = last_day
        arguments, unsupported = build_arguments(
            conn, actual_day, window_weeks=window_weeks
        )
        session_count = int(conn.execute("SELECT COUNT(*) FROM session").fetchone()[0])
        set_count = int(conn.execute("SELECT COUNT(*) FROM clean_set").fetchone()[0])
        readiness_count = int(
            conn.execute("SELECT COUNT(*) FROM readiness_day").fetchone()[0]
        )
    finally:
        conn.close()

    if only:
        wanted = set(only)
        unknown = wanted - set(arguments) - set(unsupported)
        for name in sorted(unknown):
            unsupported[name] = "unknown capability"
        arguments = {k: v for k, v in arguments.items() if k in wanted}
        unsupported = {k: v for k, v in unsupported.items() if k in wanted}

    direct = None
    if mode in ("direct", "both"):
        direct = run_direct(
            path, arguments, unsupported, iterations=iterations, warmup=warmup
        )
    http = None
    if mode in ("http", "both"):
        if not token:
            http = {"error": "no token supplied (set the token environment variable)"}
        else:
            http = run_http(
                url, token, timeout, arguments, unsupported,
                iterations=iterations, warmup=warmup,
            )

    report = _build_report(
        path=path, sessions=session_count, sets=set_count, readiness=readiness_count,
        source="synthetic" if db_path is None else "database",
        arguments=arguments, unsupported=unsupported, direct=direct, http=http,
        http_error=(http or {}).get("error"),
        iterations=iterations, warmup=warmup, threshold_ms=threshold_ms, url=url,
    )
    if tempdir is not None:
        tempdir.cleanup()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=int, default=200)
    parser.add_argument("--runs", type=int, default=30, help="measured iterations")
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--window-weeks", type=int, default=4, help="overview window")
    parser.add_argument("--mode", choices=("direct", "http", "both"), default="direct")
    parser.add_argument("--db", default=None, help="existing database (read-only)")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument(
        "--token-env", default="STRENGTH_MCP_TOKEN", help="environment variable holding the token"
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--capability", action="append", default=None)
    parser.add_argument("--threshold-ms", type=float, default=1000.0)
    parser.add_argument("--no-analytics-build", action="store_true")
    parser.add_argument("--output", default=None, help="write JSON report to this path")
    parser.add_argument("--json", action="store_true", help="print JSON only")
    args = parser.parse_args(argv)
    token = os.environ.get(args.token_env)
    report = run_extended(
        sessions=args.sessions,
        iterations=args.runs,
        warmup=args.warmup,
        db_path=args.db,
        mode=args.mode,
        url=args.url,
        token=token,
        timeout=args.timeout,
        only=args.capability,
        threshold_ms=args.threshold_ms,
        build_analytics=not args.no_analytics_build,
        window_weeks=args.window_weeks,
    )
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("dataset:", report["dataset"])
        print("analytics:", report["dataset"].get("analytics"))
        _summarise(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
