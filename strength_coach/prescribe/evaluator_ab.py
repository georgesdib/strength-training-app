"""Synthetic fixed-history A/B review for the resolver evaluator.

This command replays deterministic synthetic histories through the real resolver. For each
case it compares the pre-WP6 additive key with the corrected WP6 role-quality hierarchy over
the same finalists and writes a review table. It creates only in-memory databases, never reads
real training data and never persists a prescription.

The legacy cases exercise the main-lift key. The full-template cases add a main lift, a
secondary and at least one accessory whose alternatives differ in complementarity, redundancy,
coverage or stimulus cost. They are synthetic fixtures, not evidence of generalisation.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any
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


def _history(exercise: str, *, weight: float = 80.0, reps: int = 5,
             rir: int = 2) -> list[dict]:
    return [
        {"Date": "2024-01-01", "Exercise": exercise, "Weight_Used": str(weight),
         "Reps_Done": str(reps), "RIR": str(rir)},
        {"Date": "2024-01-08", "Exercise": exercise, "Weight_Used": str(weight),
         "Reps_Done": str(reps), "RIR": str(rir)},
    ]


def _seed_rows(seed: dict[str, int], *, date: str = "2024-01-16") -> list[dict]:
    """Deterministic completed weekly volume for the full-template cases.

    One row is one working set. The values are chosen to put the weekly total inside the
    volume band and to make one pattern already covered while another is in deficit; they
    are synthetic fixture inputs, not a training recommendation.
    """
    rows: list[dict] = []
    for exercise, sets in seed.items():
        for _ in range(sets):
            rows.append({
                "Date": date, "Exercise": exercise, "Weight_Used": "60.0",
                "Reps_Done": "5", "RIR": "2",
            })
    return rows


#: A mid-week synthetic week. Total = 52 working sets before the planned session, so the
#: 5-slot session lands inside the 69-set weekly band (62.1-75.9).
FULL_SEED = {
    "Safety Squat Bar": 10,
    "Trap Bar Deadlift": 6,
    "Competition Bench Press": 9,
    "Dumbbell Row": 9,
    "Ab Wheel": 5,
    "Lying Leg Curls": 5,
    "Lat Pulldown": 5,
    "Overhead Press (seated)": 3,
}


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


def _full_pools(case: dict[str, Any]) -> CandidatePools:
    base = templates.SessionTemplate.load(case["session_type"])
    slots_by_id = {slot.id: slot for slot in base.slots}
    slots = tuple(slots_by_id[slot_id] for slot_id in case["slots"])
    return CandidatePools(
        template=replace(base, slots=slots),
        pools={slot_id: tuple(pool) for slot_id, pool in case["pools"].items()},
        main_slot=slots_by_id[case["main_slot"]],
        policy_digest="p" * 64,
        catalogue_digest="c" * 64,
    )


def _previous_workout(conn, *, exercise_id: str, for_date: str = "2024-01-10") -> None:
    """One completed session whose working set is the previous exposure for plan slot 1.

    The set is materialised, not merely prescribed: resolver specificity reads what was
    performed (the release-integrity audit's WP5), so a plan-only synthetic session would
    correctly contribute no previous choice.
    """
    workout_id = f"previous-{exercise_id}"
    plan = {"items": [{"order_index": 1, "exercise_id": exercise_id}]}
    conn.execute(
        "INSERT INTO workout_session "
        "(workout_id, for_date, session_type, status, plan_json, readiness_json, "
        " started_at, ended_at) VALUES (?, ?, 'squat', 'completed', ?, '{}', ?, ?)",
        (workout_id, for_date, json.dumps(plan),
         f"{for_date}T10:00:00Z", f"{for_date}T11:00:00Z"),
    )
    conn.execute(
        "INSERT INTO session (session_id, occurred_on, workout_label, set_count, "
        "working_set_count, exercise_count, main_lifts, session_type, source, workout_id) "
        "VALUES (?, ?, 'workout mode', 1, 1, 1, ?, 'squat', 'workout', ?)",
        (workout_id, for_date, json.dumps([exercise_id]), workout_id),
    )
    raw_id = int(conn.execute(
        "INSERT INTO raw_row (table_name, source_row, file_sha256, payload) "
        "VALUES ('training', ?, ?, ?) RETURNING raw_id",
        (900000 + len(exercise_id), f"previous-{exercise_id}", json.dumps({
            "exercise": exercise_id, "date": for_date,
        })),
    ).fetchone()["raw_id"])
    conn.execute(
        "INSERT INTO clean_set (raw_id, session_id, occurred_on, exercise_id, raw_exercise, "
        "load_kg, load_basis, reps, reps_unit, rir, rir_source, velocity_present, "
        "is_working_set, flags, prescription_item_index) "
        "VALUES (?, ?, ?, ?, ?, 100.0, 'external', 5, 'reps', 2, 'logged', 0, 1, '[]', 1)",
        (raw_id, workout_id, for_date, exercise_id, exercise_id),
    )


CASES: dict[str, dict[str, Any]] = {
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
    # --- full-template cases: main + secondary + accessory ---
    "secondary_complementarity": {
        "session_type": "squat",
        "slots": ("power", "squat_main", "bench_support", "accessory_row",
                  "core_anti_extension"),
        "main_slot": "squat_main",
        "pools": {
            "power": ("box_jump",),
            "squat_main": ("ssb_squat",),
            "bench_support": ("bench_press", "split_squat"),
            "accessory_row": ("dumbbell_row",),
            "core_anti_extension": ("ab_wheel",),
        },
        "rows": (
            _history("Safety Squat Bar", weight=100)
            + _history("Competition Bench Press", weight=80)
            + _history("Split Squat", weight=50)
            + _history("Dumbbell Row", weight=30)
            + _history("Ab Wheel", weight=0)
        ),
        "seed": FULL_SEED,
        "volume_budget": True,
        "for_date": "2024-01-18",
        "intent": "off",
    },
    "secondary_redundancy": {
        "session_type": "squat",
        "slots": ("power", "squat_main", "bench_support", "core_anti_extension",
                  "accessory_row"),
        "main_slot": "squat_main",
        "pools": {
            "power": ("box_jump",),
            "squat_main": ("ssb_squat",),
            "bench_support": ("bench_press", "dumbbell_row"),
            "core_anti_extension": ("bench_press_narrow",),
            "accessory_row": ("ab_wheel",),
        },
        "rows": (
            _history("Safety Squat Bar", weight=100)
            + _history("Competition Bench Press", weight=80)
            + _history("Dumbbell Row", weight=30)
            + _history("Bench Press (narrow grip)", weight=70)
            + _history("Ab Wheel", weight=0)
        ),
        "intent": "off",
    },
    "accessory_coverage": {
        "session_type": "squat",
        "slots": ("power", "squat_main", "bench_support", "accessory_row",
                  "core_anti_extension"),
        "main_slot": "squat_main",
        "pools": {
            "power": ("box_jump",),
            "squat_main": ("ssb_squat",),
            "bench_support": ("bench_press",),
            "accessory_row": ("dumbbell_row", "bench_press_narrow"),
            "core_anti_extension": ("ab_wheel",),
        },
        "rows": (
            _history("Safety Squat Bar", weight=100)
            + _history("Competition Bench Press", weight=80)
            + _history("Dumbbell Row", weight=30)
            + _history("Bench Press (narrow grip)", weight=70)
            + _history("Ab Wheel", weight=0)
        ),
        "seed": FULL_SEED,
        "volume_budget": True,
        "for_date": "2024-01-18",
        "intent": "off",
    },
    "accessory_stimulus": {
        "session_type": "bench_squat",
        "slots": ("power", "bench_main", "squat_support", "accessory_vertical_press"),
        "main_slot": "bench_main",
        "pools": {
            "power": ("medicine_ball_chest_pass",),
            "bench_main": ("bench_press",),
            "squat_support": ("sumo_deadlift",),
            "accessory_vertical_press": ("front_squat", "hanging_leg_raise"),
        },
        "rows": (
            _history("Competition Bench Press", weight=80)
            + _history("Sumo Deadlift", weight=140)
            + _history("Front Squat", weight=70)
            + _history("Hanging Leg Raise", weight=0)
        ),
        "intent": "off",
    },
    "accessory_stimulus_high": {
        "session_type": "bench_squat",
        "slots": ("power", "bench_main", "squat_support", "accessory_vertical_press"),
        "main_slot": "bench_main",
        "pools": {
            "power": ("medicine_ball_chest_pass",),
            "bench_main": ("bench_press",),
            "squat_support": ("competition_squat",),
            "accessory_vertical_press": ("lat_pulldown", "seated_cable_row"),
        },
        "rows": (
            _history("Competition Bench Press", weight=80)
            + _history("Competition Squat", weight=100)
            + _history("Lat Pulldown", weight=50)
            + _history("Seated Cable Row", weight=50)
        ),
        "intent": "off",
    },
}


def _class_snapshot(evaluation) -> dict[str, list[dict[str, Any]]] | None:
    if evaluation is None or evaluation.quality is None:
        return None
    return {
        role: [
            {"slot_id": entry["slot_id"], "exercise_id": entry["exercise_id"],
             "classes": dict(entry["classes"])}
            for entry in entries
        ]
        for role, entries in evaluation.quality.roles.items()
    }


def _changed_slots(a: dict[str, str] | None, b: dict[str, str] | None) -> list[str]:
    if not a or not b:
        return []
    return sorted(slot for slot in a if a[slot] != b.get(slot))


def _run_case(name: str) -> dict:
    case = CASES[name]
    rows = list(case["rows"])
    if case.get("seed"):
        rows += _seed_rows(case["seed"])
    training = _training(rows)
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
        if case.get("volume_budget"):
            repositories.append_athlete_profile(
                store.connection, effective_from="2024-01-01",
                volume_budget_enabled=True, main_lift_policy="preserve",
            )
        base = _full_pools(case) if case.get("slots") else _pools()
        for slot in base.template.slots:
            for exercise_id in base.pools.get(slot.id, ()):
                repositories.append_exercise_suitability(
                    store.connection, exercise_id=exercise_id,
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
                store.connection, for_date=case.get("for_date", "2024-01-15"),
                session_type=case.get("session_type", "squat"),
                inputs=EvaluationInputs(top_set_intent=case["intent"]),
            )
        feasible = [item for item in resolved.beam.evaluated if item.feasible]
        classic = min(feasible, key=lambda item: item.classic_score_key) if feasible else None
        quality = resolved.beam.best
        finalists = [
            {
                "assignment": dict(item.assignment),
                "feasible": item.feasible,
                "classic_score_key": list(item.classic_score_key),
                "quality_key": list(item.quality_key),
                "band_penalty": item.quality.vector[0] if item.quality else None,
                "volume_error": item.components.volume_error,
                "time_over": item.components.time_over_minutes,
                "warnings": item.components.warnings,
                "classes": _class_snapshot(item),
            }
            for item in resolved.beam.evaluated
        ]
        return {
            "name": name,
            "evidence": "synthetic",
            "template": "full" if case.get("slots") else "legacy",
            "volume_budget": bool(case.get("volume_budget")),
            "intent": case["intent"],
            "evaluated": len(resolved.beam.evaluated),
            "feasible": len(feasible),
            "classic": dict(classic.assignment) if classic else None,
            "quality": dict(quality.assignment) if quality else None,
            "changed": bool(classic and quality and classic.assignment != quality.assignment),
            "changed_slots": _changed_slots(
                dict(classic.assignment) if classic else None,
                dict(quality.assignment) if quality else None,
            ),
            "classic_feasible": bool(classic),
            "quality_feasible": bool(quality and quality.feasible),
            "classic_classes": _class_snapshot(classic),
            "quality_classes": _class_snapshot(quality),
            "band_penalty": quality.quality.vector[0] if quality and quality.quality else None,
            "classic_band_penalty": (
                classic.quality.vector[0] if classic and classic.quality else None
            ),
            "volume_error": quality.components.volume_error if quality else None,
            "classic_volume_error": classic.components.volume_error if classic else None,
            "time_over": quality.components.time_over_minutes if quality else None,
            "warnings": quality.components.warnings if quality else None,
            "classic_warnings": classic.components.warnings if classic else None,
            "top_set": (
                (quality.prescription.notes.get("top_set") or {}).get("status")
                if quality else None
            ),
            "finalists": finalists,
        }
    finally:
        store.close()


def _assignment_text(assignment: dict[str, str] | None, *, roles: dict[str, str] | None = None) -> str:
    if not assignment:
        return "—"
    if roles is None:
        return "; ".join(f"{slot}={exercise}" for slot, exercise in assignment.items())
    by_role: dict[str, list[str]] = {}
    for slot, exercise in assignment.items():
        by_role.setdefault(roles.get(slot, slot), []).append(exercise)
    return "; ".join(
        f"{role}: {', '.join(exercises)}" for role, exercises in by_role.items()
    )


def _class_text(classes: dict[str, list[dict[str, Any]]] | None) -> str:
    if not classes:
        return "—"
    parts = []
    for role in ("secondary", "accessory"):
        for entry in classes.get(role, []):
            values = ", ".join(
                f"{name}={value}" for name, value in entry["classes"].items()
            )
            parts.append(f"{role}/{entry['slot_id']}: {values}")
    return "<br>".join(parts) if parts else "—"


def _classes_for_slot(
    classes: dict[str, list[dict[str, Any]]] | None, slot: str
) -> tuple[str | None, dict[str, Any] | None]:
    for role, entries in (classes or {}).items():
        for entry in entries:
            if entry["slot_id"] == slot:
                return role, dict(entry["classes"])
    return None, None


def _deciding_text(case: dict) -> str:
    """Show the A -> B class change for changed slots; otherwise the B classes."""
    if not case["changed_slots"]:
        return _class_text(case["quality_classes"])
    parts = []
    for slot in case["changed_slots"]:
        role, before = _classes_for_slot(case["classic_classes"], slot)
        _role, after = _classes_for_slot(case["quality_classes"], slot)
        if before == after:
            values = ", ".join(
                f"{name}={value}" for name, value in (after or {}).items()
            )
            parts.append(
                f"{role}/{slot}: classes tie ({values}); deterministic "
                "rank-cost/assignment tie-break"
            )
            continue
        left = ", ".join(f"{name}={value}" for name, value in (before or {}).items())
        right = ", ".join(f"{name}={value}" for name, value in (after or {}).items())
        parts.append(f"{role}/{slot}: A[{left}] -> B[{right}]")
    return "<br>".join(parts)


def _markdown(results: list[dict]) -> str:
    lines = [
        "# Resolver evaluator A/B review (synthetic)",
        "",
        "All rows are synthetic fixtures; none uses real training data. A = pre-WP6 additive "
        "score, B = corrected WP6 lexicographic role-quality hierarchy, over the same "
        "eligible finalists with identical build inputs and hard safety gates.",
        "",
        "| Case | Template | A choice | B choice | Changed | Feasible | Band | Volume error | Time over | Warnings | Top set | Deciding classes | Verdict |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for case in results:
        changed = ", ".join(case["changed_slots"]) or ("yes" if case["changed"] else "no")
        band = (
            "n/a" if case["band_penalty"] is None
            else ("inside" if case["band_penalty"] == 0 else "outside")
        )
        lines.append(
            f"| {case['name']} | {case['template']}"
            f"{' + budget' if case['volume_budget'] else ''} | "
            f"{_assignment_text(case['classic'])} | {_assignment_text(case['quality'])} | "
            f"{changed} | {'yes' if case['quality_feasible'] else 'no'} | {band} | "
            f"{case['volume_error']:.2f} | {case['time_over']:.1f} | "
            f"{case['warnings']} | {case['top_set'] or '—'} | "
            f"{_deciding_text(case)} | pending |"
        )
    lines += [
        "",
        "Verdicts are the owner review: mark each row accept or reject. A rejection reverts or "
        "retunes the hierarchy for that case; no case is marked complete automatically.",
        "",
        "The fixed synthetic histories are small. They demonstrate direction, class semantics and "
        "the exact selection change; they do not claim generalisation to real training data.",
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
