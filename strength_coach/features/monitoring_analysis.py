"""Reusable read-only exploratory monitoring analysis.

The CLI and HTTP API both call this service. It describes dose, lagged associations and
calibration transparency; it never writes, fits a model, changes a prescription or alters
calibration state.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from strength_coach.domain.e1rm import E1RM_METHOD_VERSION
from strength_coach.features import calibration_observations, monitoring, strength_trend
from strength_coach.features import session_feedback as feedback_feature
from strength_coach.store import queries

ANALYSIS_VERSION = "monitoring-analysis-v1"
SEED = 0


def database_path(conn: sqlite3.Connection) -> Path | None:
    for row in conn.execute("PRAGMA database_list"):
        if str(row[1]) == "main" and row[2]:
            return Path(str(row[2]))
    return None


def fingerprint_connection(conn: sqlite3.Connection) -> str | None:
    path = database_path(conn)
    if path is None or not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
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


def build_analysis(
    conn: sqlite3.Connection,
    *,
    as_of: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    sessions = queries.sessions(conn, end=as_of)
    sets = queries.clean_sets(conn, end=as_of)
    exercises = sorted({str(value) for value in sets["exercise_id"]}) if not sets.empty else []
    dose_rows: list[dict[str, Any]] = []
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

    associations: list[dict[str, Any]] = []
    for exercise_id in exercises:
        observations = strength_trend.observations(conn, exercise_id, "1900-01-01", as_of)
        if len(observations) < 2:
            continue
        dates = [item.date for item in observations]
        hard_pairs: list[tuple[float, float]] = []
        load_pairs: list[tuple[float, float]] = []
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

    calibration = calibration_observations.observations(conn, to_date=as_of)
    calibration_block = {
        "as_of": as_of,
        "method_version": E1RM_METHOD_VERSION,
        "historical_state_reconstructable": False,
        "note": (
            "The factor and CI are the state available as of the selected date. "
            "They are not necessarily the factor that was available on each historical test date."
        ),
        "observations": [item.as_dict() for item in calibration],
    }
    return {
        "meta": {
            "analysis_version": ANALYSIS_VERSION,
            "as_of": as_of,
            "database_fingerprint": (
                fingerprint_connection(conn) if db_path is None
                else _fingerprint_path(db_path)
            ),
            "read_only": True,
            "seed": SEED,
            "basis": "raw formula-derived e1RM",
            "note": "Descriptive associations only; no causal claim or model adoption.",
        },
        "missingness": {
            "sessions": int(len(sessions)),
            "sessions_with_feedback": feedback_count,
            "sets": int(len(sets)),
            "exercises": len(exercises),
        },
        "dose": dose_rows,
        "associations": associations,
        "calibration": calibration_block,
        "limitations": [
            "Dose-response and lagged associations are observational and descriptive.",
            "Small n and missing feedback make many associations insufficient.",
            "Correlation does not establish causation or validate a predictive model.",
            "No model, prescription recommendation or causal claim is produced.",
            "Calibration context is current-as-of; historical factor state is not reconstructed.",
        ],
    }


def _fingerprint_path(db_path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(db_path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Monitoring exploratory analysis",
        "",
        "Read-only descriptive analysis. Personal output is local-only and must not be committed.",
        "",
        "## Method",
        "",
        f"- Analysis version: {report['meta']['analysis_version']}",
        f"- As of: {report['meta']['as_of']}",
        f"- Database fingerprint: {report['meta']['database_fingerprint']}",
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
        load = row["session_load_au"] if row["session_load_au"] is not None else "Unavailable"
        lines.append(
            f"| {row['date']} | {row['session_type']} | {row['working_sets']} | "
            f"{row['hard_sets']} | {row['tonnage_kg']} | {load} |"
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
    lines.extend([
        "",
        "## Calibration transparency",
        "",
        f"- As of: {report['calibration']['as_of']}",
        f"- Method version: {report['calibration']['method_version']}",
        f"- Historical state reconstructable: {report['calibration']['historical_state_reconstructable']}",
        f"- {report['calibration']['note']}",
        "",
        "| test date | exercise | measured | prior raw | factor | applied | CI |",
        "|---|---|---|---|---|---|---|",
    ])
    for row in report["calibration"]["observations"]:
        ci = (
            "Unavailable" if row["calibration_ci_low"] is None
            else f"{row['calibration_ci_low']}–{row['calibration_ci_high']}"
        )
        prior = "Unavailable" if row["prior_raw_e1rm_kg"] is None else row["prior_raw_e1rm_kg"]
        lines.append(
            f"| {row['performed_on']} | {row['exercise_id']} | {row['measured_kg']} | "
            f"{prior} | {row['existing_calibration_factor']} | "
            f"{row['existing_factor_applied']} | {ci} |"
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)
