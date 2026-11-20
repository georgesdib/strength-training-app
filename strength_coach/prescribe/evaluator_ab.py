"""Synthetic fixed-history A/B review for the resolver evaluator.

This command replays four deterministic synthetic histories through the real resolver. For each
case it compares the pre-WP6 additive key with the WP6 role-quality hierarchy over the same
finalists and writes a review table. It creates only in-memory databases, never reads real
training data and never persists a prescription.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

import pandas as pd

from strength_coach import settings_profile
from strength_coach.prescribe import resolver, resolver_policy, templates
from strength_coach.prescribe.evaluator import EvaluationInputs
from strength_coach.prescribe.generator import CandidatePools
from strength_coach.store import db, importer, repositories


def _training(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "Date": "2024-01-01", "Workout": "Sheiko", "Exercise": "Competition Squat",
        "Weight_Used": "100.0", "Weight_Units": "kg", "Reps_Done": "5", "RIR": "2",
        "ExertionLoad": "0.0", "Main_Muscle": "Quadriceps", "Mechanics": "Compound",
        "Force": "Push", "Avg_velocity": "0.000000", "Avg_power": "0",
        "Avg_rom": "0", "TUT": "0", "Form": "0", "Video": "",
    }
    return pd.DataFrame([{**defaults, **row} for row in rows]).astype(str)


def _readiness() -> pd.DataFrame:
    return pd.DataFrame([{
        "Date": "2024-01-01", "Sleep": "4", "Energy": "4", "Mood": "4",
        "Soreness": "4", "Stress": "4", "Squat_Readiness": "4",
        "Bench_Readiness": "4", "Deadlift_Readiness": "4", "HRV": "0", "RHR": "0",
        "Weight": "80.0", "Fat_Percent": "20.0",
    }]).astype(str)


def _pools() -> CandidatePools:
    base = templates.SessionTemplate.load("squat")
    slots = tuple(slot for slot in base.slots if slot.id in {"power", "squat_main"})
    main = next(slot for slot in slots if slot.id == "squat_main")
    return CandidatePools(
        template=replace(base, slots=slots),
        pools={"power": ("box_jump",), "squat_main": ("ssb_squat", "competition_squat")},
        main_slot=main,
        policy_digest="p" * 64,
        catalogue_digest="c" * 64,
    )


def _previous_workout(conn, *, exercise_id: str, for_date: str = "2024-01-10") -> None:
    plan = {"items": [{"order_index": 1, "exercise_id": exercise_id}]}
    conn.execute(
        "INSERT INTO workout_session "
        "(workout_id, for_date, session_type, status, plan_json, readiness_json, "
        " started_at, ended_at) VALUES (?, ?, 'squat', 'completed', ?, '{}', ?, ?)",
        (f"previous-{exercise_id}", for_date, json.dumps(plan),
         f"{for_date}T10:00:00Z", f"{for_date}T11:00:00Z"),
    )


CASES = {
    "straight": {
        "rows": [
            {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100", "RIR": "2", "Reps_Done": "5"},
            {"Date": "2024-01-08", "Exercise": "Safety Squat Bar", "Weight_Used": "100", "RIR": "2", "Reps_Done": "5"},
            {"Date": "2024-01-02", "Exercise": "Competition Squat", "Weight_Used": "120", "RIR": "2", "Reps_Done": "5"},
            {"Date": "2024-01-09", "Exercise": "Competition Squat", "Weight_Used": "120", "RIR": "2", "Reps_Done": "5"},
        ],
        "intent": "off",
    },
    "top_set": {
        "rows": [
            {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "120", "RIR": "1", "Reps_Done": "3"},
            {"Date": "2024-01-08", "Exercise": "Safety Squat Bar", "Weight_Used": "120", "RIR": "1", "Reps_Done": "3"},
            {"Date": "2024-01-02", "Exercise": "Competition Squat", "Weight_Used": "140", "RIR": "1", "Reps_Done": "3"},
            {"Date": "2024-01-09", "Exercise": "Competition Squat", "Weight_Used": "140", "RIR": "1", "Reps_Done": "3"},
        ],
        "intent": "preferred",
    },
    "substitution": {
        "rows": [
            {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100", "RIR": "2", "Reps_Done": "5"},
            {"Date": "2024-01-08", "Exercise": "Safety Squat Bar", "Weight_Used": "100", "RIR": "2", "Reps_Done": "5"},
            {"Date": "2024-01-02", "Exercise": "Competition Squat", "Weight_Used": "120", "RIR": "2", "Reps_Done": "5"},
            {"Date": "2024-01-09", "Exercise": "Competition Squat", "Weight_Used": "120", "RIR": "2", "Reps_Done": "5"},
        ],
        "intent": "off",
        "previous": "competition_squat",
    },
    "divergent": {
        "rows": [
            {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100", "RIR": "3", "Reps_Done": "8"},
            {"Date": "2024-01-03", "Exercise": "Safety Squat Bar", "Weight_Used": "110", "RIR": "1", "Reps_Done": "2"},
            {"Date": "2024-01-08", "Exercise": "Competition Squat", "Weight_Used": "120", "RIR": "2", "Reps_Done": "5"},
            {"Date": "2024-01-10", "Exercise": "Competition Squat", "Weight_Used": "140", "RIR": "1", "Reps_Done": "3"},
        ],
        "intent": "off",
        "previous": "ssb_squat",
    },
}


def _run_case(name: str) -> dict:
    case = CASES[name]
    training = _training(case["rows"])
    readiness = _readiness()
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        if case.get("previous"):
            _previous_workout(store.connection, exercise_id=case["previous"])
        base = _pools()
        for slot in base.template.slots:
            repositories.append_exercise_suitability(
                store.connection, exercise_id=slot.exercises[0],
                rated_on="2024-01-01", can_do=True, will_do=True, feels_bad=False,
            )
        settings_profile.save(
            store.connection, set_values={"resolver.enabled": True},
            resolver_enable_confirmed=True, effective_from="2024-01-01",
        )
        policy = resolver_policy.ResolverPolicy.load()
        empty = replace(
            policy,
            required_patterns=MappingProxyType({s: () for s in templates.SESSION_TYPES}),
        )
        with patch.object(
            resolver_policy.ResolverPolicy, "load",
            classmethod(lambda cls, path=None: empty),
        ), patch.object(resolver.generator, "candidate_pools", lambda *a, **k: base):
            resolved = resolver.build_resolved(
                store.connection, for_date="2024-01-15", session_type="squat",
                inputs=EvaluationInputs(top_set_intent=case["intent"]),
            )
        feasible = [item for item in resolved.beam.evaluated if item.feasible]
        classic = min(feasible, key=lambda item: item.classic_score_key) if feasible else None
        quality = resolved.beam.best
        return {
            "name": name,
            "intent": case["intent"],
            "evaluated": len(resolved.beam.evaluated),
            "feasible": len(feasible),
            "classic": dict(classic.assignment) if classic else None,
            "quality": dict(quality.assignment) if quality else None,
            "changed": bool(classic and quality and classic.assignment != quality.assignment),
            "classic_feasible": bool(classic),
            "quality_feasible": bool(quality and quality.feasible),
            "band_penalty": quality.quality.vector[0] if quality and quality.quality else None,
            "volume_error": quality.components.volume_error if quality else None,
            "time_over": quality.components.time_over_minutes if quality else None,
            "warnings": quality.components.warnings if quality else None,
            "top_set": (quality.prescription.notes.get("top_set") or {}).get("status") if quality else None,
        }
    finally:
        store.close()


def _markdown(results: list[dict]) -> str:
    lines = [
        "# Resolver evaluator A/B review (synthetic)",
        "",
        "Fixed synthetic histories; no real training data. A = pre-WP6 additive score, "
        "B = WP6 lexicographic role-quality hierarchy, over the same finalists.",
        "",
        "| Case | A choice | B choice | Changed | Feasible | Band | Volume error | Time over | Warnings | Top set | Verdict |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for case in results:
        a = case["classic"].get("squat_main") if case["classic"] else "—"
        b = case["quality"].get("squat_main") if case["quality"] else "—"
        band = "inside" if case["band_penalty"] == 0 else "outside"
        lines.append(
            f"| {case['name']} | {a} | {b} | {'yes' if case['changed'] else 'no'} | "
            f"{'yes' if case['quality_feasible'] else 'no'} | {band} | "
            f"{case['volume_error']:.2f} | {case['time_over']:.1f} | "
            f"{case['warnings']} | {case['top_set'] or '—'} | pending |"
        )
    lines += [
        "",
        "Verdicts are the owner review: mark each row accept or reject. A rejection reverts or "
        "retunes the hierarchy for that case; no case is marked complete automatically.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthetic fixed-history evaluator A/B")
    parser.add_argument("--out", type=Path, default=Path("private/evaluator-ab-review.md"))
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    results = [_run_case(name) for name in CASES]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(_markdown(results), encoding="utf-8")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

