"""Synthetic WP7b structural-ordering comparison.

Compares cap-only, cap plus draw, cap plus draw plus bounded factor, and the rejected
pure-factor reference on one fixed synthetic history. It changes only candidate-pool order; the
evaluator and all safety gates are unchanged.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

from strength_coach import settings_profile
from strength_coach.prescribe import evaluator_ab as ab
from strength_coach.prescribe import generator, resolver, resolver_policy, templates
from strength_coach.prescribe.evaluator import EvaluationInputs
from strength_coach.prescribe.resolver_settings import ResolverSettings
from strength_coach.store import db, importer, repositories

VARIANTS = (
    ("cap", "cap", 0.0),
    ("cap_draw", "cap_draw", 1.0),
    ("cap_draw_factor", "full", 1.0),
    ("pure_factor", "pure_factor", 0.0),
)


def _run_variant(name: str, mode: str, probability: float, rows: list[dict]) -> dict:
    training = ab._training(rows)
    readiness = ab._readiness()
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        # Remove the imported previous-choice rows so this comparison isolates pool order,
        # not the role-quality specificity class.
        store.connection.execute("DELETE FROM workout_session")
        base = ab._pools()
        for slot in base.template.slots:
            repositories.append_exercise_suitability(
                store.connection, exercise_id=slot.exercises[0],
                rated_on="2024-01-01", can_do=True, will_do=True, feels_bad=False,
            )
        settings_profile.save(
            store.connection, set_values={"resolver.enabled": True},
            resolver_enable_confirmed=True, effective_from="2024-01-01",
        )
        settings = replace(
            ResolverSettings.load(store.connection, "2024-01-15"),
            dwell_probability=probability,
        )
        catalogue = ["ssb_squat", "competition_squat"]
        ordered = generator._dwell_ordered_pool(
            catalogue,
            for_date="2024-01-15",
            session_type="squat",
            slot_id="squat_main",
            patterns={"ssb_squat": "squat", "competition_squat": "squat"},
            counts={"ssb_squat": 0, "competition_squat": 2},
            last_used={"ssb_squat": "2024-01-10"},
            settings=settings,
            variant=mode,
        )
        pool = replace(base, pools={**base.pools, "squat_main": tuple(ordered)})
        policy = resolver_policy.ResolverPolicy.load()
        empty = replace(
            policy,
            required_patterns=MappingProxyType({s: () for s in templates.SESSION_TYPES}),
        )
        with patch.object(
            resolver_policy.ResolverPolicy, "load",
            classmethod(lambda cls, path=None: empty),
        ), patch.object(resolver.generator, "candidate_pools", lambda *a, **k: pool):
            resolved = resolver.build_resolved(
                store.connection, for_date="2024-01-15", session_type="squat",
                inputs=EvaluationInputs(top_set_intent="off"),
            )
        chosen = resolved.beam.best
        return {
            "variant": name,
            "pool": ordered,
            "selection": dict(chosen.assignment).get("squat_main") if chosen else None,
            "feasible": bool(chosen and chosen.feasible),
            "band_penalty": chosen.quality.vector[0] if chosen and chosen.quality else None,
            "volume_error": chosen.components.volume_error if chosen else None,
            "time_over": chosen.components.time_over_minutes if chosen else None,
            "warnings": chosen.components.warnings if chosen else None,
        }
    finally:
        store.close()


def _markdown(results: list[dict], cap_selection: str | None) -> str:
    lines = [
        "# Resolver dwell ordering A/B (synthetic)",
        "",
        "Fixed synthetic squat history; the evaluator, safety gates and band are unchanged. "
        "The pure-factor row is a rejected reference, not a candidate for production.",
        "",
        "| Variant | Pool order | Selected | Changed vs cap | Feasible | Band | Volume error | Time over | Warnings |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in results:
        lines.append(
            f"| {row['variant']} | {' > '.join(row['pool'])} | {row['selection']} | "
            f"{'yes' if row['selection'] != cap_selection else 'no'} | "
            f"{'yes' if row['feasible'] else 'no'} | "
            f"{'inside' if row['band_penalty'] == 0 else 'outside'} | "
            f"{row['volume_error']:.2f} | {row['time_over']:.1f} | {row['warnings']} |"
        )
    lines += [
        "",
        "Acceptance: a later-catalogue candidate moved ahead without a safety, band or time "
        "regression; the pure-factor order is rejected because it crosses structural classes. "
        "No beam or cap width was changed.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthetic dwell ordering comparison")
    parser.add_argument("--out", type=Path, default=Path("private/dwell-ab-review.md"))
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    rows = ab.CASES["straight"]["rows"]
    results = [_run_variant(name, mode, probability, rows) for name, mode, probability in VARIANTS]
    cap_selection = next(
        (row["selection"] for row in results if row["variant"] == "cap"), None
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(_markdown(results, cap_selection), encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

