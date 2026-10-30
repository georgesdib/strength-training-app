#!/usr/bin/env python
"""Read-only exploratory analysis for monitoring.

Descriptive dose-response and lagged associations only. This tool does not fit or adopt a
model, change a prescription, or write to the database. The default report is private because
it may contain personal training data.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strength_coach.features import (  # noqa: E402
    monitoring,
    strength_trend,
)
from strength_coach.features import session_feedback as feedback_feature  # noqa: E402
from strength_coach.store import queries  # noqa: E402
from strength_coach.utils import paths  # noqa: E402

DEFAULT_OUT = "private/docs/MONITORING-ANALYSIS.md"
SEED = 0


def connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"database does not exist: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def fingerprint(db_path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(db_path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _corr(pairs: list[tuple[float, float]]) -> dict[str, Any]:
    if len(pairs) < 3:
        return {"n": len(pairs), "r": None, "status": "insufficient"}
    x, y = zip(*pairs, strict=True)
    if np.std(x) == 0 or np.std(y) == 0:
        return {"n": len(pairs), "r": None, "status": "no_variation"}
    return {"n": len(pairs), "r": round(float(np.corrcoef(x, y)[0, 1]), 3), "status": "descriptive"}


def build_analysis(conn: sqlite3.Connection, *, as_of: str, db_path: str | Path) -> dict[str, Any]:
    sessions = queries.sessions(conn, end=as_of)
    sets = queries.clean_sets(conn, end=as_of)
    exercises = sorted({str(value) for value in sets["exercise_id"]}) if not sets.empty else []
    dose_rows = []
    feedback_count = 0
    for _, session in sessions.iterrows():
        session_id = str(session["session_id"])
        group = sets[sets["session_id"].astype(str).eq(session_id)] if not sets.empty else sets
        work = group[group["is_working_set"].fillna(False).astype(bool)] if not group.empty else group
        feedback = feedback_feature.merged(conn, session_id)
        if feedback:
            feedback_count += 1
        load = monitoring.session_load(feedback) if feedback else monitoring.Unavailable("no feedback")
        tonnage = (
            float(pd.to_numeric(work["tonnage_kg"], errors="coerce").dropna().sum())
            if not work.empty else 0.0
        )
        dose_rows.append({
            "session_id": session_id,
            "date": str(session["occurred_on"])[:10],
            "session_type": str(session.get("session_type") or ""),
            "working_sets": int(len(work)),
            "hard_sets": monitoring.hard_sets(work),
            "tonnage_kg": round(tonnage, 1),
            "session_load_au": None if isinstance(load, monitoring.Unavailable) else round(float(load), 1),
        })

    associations = []
    for exercise_id in exercises:
        observations = strength_trend.observations(conn, exercise_id, "1900-01-01", as_of)
        if len(observations) < 2:
            continue
        dates = [item.date for item in observations]
        hard_pairs = []
        load_pairs = []
        for index, observation in enumerate(observations[:-1]):
            next_observation = observations[index + 1]
            session_id = observation.session_id
            group = sets[sets["session_id"].astype(str).eq(session_id)]
            work = group[group["is_working_set"].fillna(False).astype(bool)] if not group.empty else group
            hard_pairs.append((float(monitoring.hard_sets(work)), next_observation.estimate.kg))
            feedback = feedback_feature.merged(conn, session_id)
            load = monitoring.session_load(feedback) if feedback else monitoring.Unavailable("no feedback")
            if not isinstance(load, monitoring.Unavailable):
                load_pairs.append((float(load), next_observation.estimate.kg))
        associations.append({
            "exercise_id": exercise_id,
            "observations": len(observations),
            "first": dates[0],
            "last": dates[-1],
            "hard_sets_vs_next_e1rm": _corr(hard_pairs),
            "session_load_vs_next_e1rm": _corr(load_pairs),
        })
    missing = {
        "sessions": int(len(sessions)),
        "sessions_with_feedback": feedback_count,
        "sets": int(len(sets)),
        "exercises": len(exercises),
    }
    return {
        "meta": {
            "as_of": as_of,
            "db_sha256": fingerprint(db_path),
            "read_only": True,
            "seed": SEED,
            "basis": "raw formula-derived e1RM",
            "note": "Descriptive associations only; no causal claim or model adoption.",
        },
        "missingness": missing,
        "dose": dose_rows,
        "associations": associations,
        "limitations": [
            "Dose-response and lagged associations are observational and descriptive.",
            "Small n and missing feedback make many associations insufficient.",
            "No model, prescription recommendation or causal claim is produced.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Monitoring exploratory analysis",
        "",
        "Read-only descriptive analysis. Personal output is local-only and must not be committed.",
        "",
        "## Method",
        "",
        f"- As of: {report['meta']['as_of']}",
        f"- Database SHA-256: {report['meta']['db_sha256']}",
        f"- Seed: {report['meta']['seed']}",
        f"- Note: {report['meta']['note']}",
        "",
        "## Coverage",
        "",
        "| metric | count |",
        "|---|---|",
    ]
    for key, value in report["missingness"].items():
        lines.append(f"| {key} | {value} |")
    lines.extend([
        "",
        "## Dose by session",
        "",
        "| date | type | working sets | hard sets | tonnage kg | session load AU |",
        "|---|---|---|---|---|---|",
    ])
    for row in report["dose"]:
        lines.append(
            f"| {row['date']} | {row['session_type']} | {row['working_sets']} | "
            f"{row['hard_sets']} | {row['tonnage_kg']} | "
            f"{row['session_load_au'] if row['session_load_au'] is not None else 'Unavailable'} |"
        )
    lines.extend([
        "",
        "## Lagged associations",
        "",
        "| exercise | observations | hard sets vs next e1RM | session load vs next e1RM |",
        "|---|---|---|---|",
    ])
    for row in report["associations"]:
        hard = row["hard_sets_vs_next_e1rm"]
        load = row["session_load_vs_next_e1rm"]
        lines.append(
            f"| {row['exercise_id']} | {row['observations']} | "
            f"{hard['status']} (n={hard['n']}, r={hard['r']}) | "
            f"{load['status']} (n={load['n']}, r={load['r']}) |"
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(paths.data_dir("coach.db")))
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args(argv)
    as_of = args.as_of or datetime.date.today().isoformat()
    try:
        conn = connect_readonly(args.db)
        try:
            report = build_analysis(conn, as_of=as_of, db_path=args.db)
        finally:
            conn.close()
    except (FileNotFoundError, sqlite3.DatabaseError) as exc:
        print(f"analysis error: {exc}", file=sys.stderr)
        return 2
    text = (
        json.dumps(report, indent=2, sort_keys=True)
        if args.format == "json" else render_markdown(report)
    ) + "\n"
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
