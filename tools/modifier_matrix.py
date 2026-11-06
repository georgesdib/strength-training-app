#!/usr/bin/env python
"""Run the W3 modifier interaction matrix against synthetic fixtures.

The matrix is an audit tool, not a product path. It builds every combination of the
core deterministic modifiers, checks structural invariants, and compares paired cases where a
reduction-only modifier is switched on. It writes a Markdown/JSON report; it never changes a
prescription or a policy.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from conftest import make_readiness, make_training  # noqa: E402
from test_prescribe import BASE_HISTORY  # noqa: E402

from strength_coach.features.deload import DeloadDecision  # noqa: E402
from strength_coach.prescribe import build_prescription  # noqa: E402
from strength_coach.store import db, importer, repositories  # noqa: E402

SESSION_TYPES = ("squat", "hinge", "bench_squat", "bench_hinge")
GAPS = (7, 28, 56)
FOR_DATE = {7: "2024-01-08", 28: "2024-01-29", 56: "2024-02-26"}
LOW_READINESS = {
    "Sleep": "1", "Energy": "1", "Mood": "1", "Soreness": "1", "Stress": "1",
}
E1RM = {
    "ssb_squat": 180.0, "trap_bar_deadlift": 190.0, "bench_press": 110.0,
    "competition_squat": 190.0, "sumo_deadlift": 200.0,
    "bench_press_narrow": 105.0, "bench_press_pause": 100.0,
}
# Owner decision (2026-10-31): a 0.5 kg increase is the prescribed increment's rounding
# tolerance, not a policy violation. Larger increases remain failures.
LOAD_ROUNDING_TOLERANCE_KG = 0.5


@dataclass(frozen=True)
class Case:
    readiness: str
    gap: int
    decay: str
    deload: bool
    flare: bool
    minimum: bool
    throttle: bool
    session_type: str

    @property
    def label(self) -> str:
        return (
            f"{self.session_type}/r={self.readiness}/g={self.gap}/d={self.decay}/"
            f"deload={int(self.deload)}/flare={int(self.flare)}/"
            f"min={int(self.minimum)}/tech={int(self.throttle)}"
        )


def _date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def _rows(for_date: str, gap: int) -> list[dict]:
    source = (_date(for_date) - dt.timedelta(days=90)).isoformat()
    marker = (_date(for_date) - dt.timedelta(days=gap)).isoformat()
    rows = [dict(row, Date=source) for row in BASE_HISTORY]
    # Every session type needs a main-lift source; BASE_HISTORY is hinge-focused.
    for name, load in (
        ("Safety Squat Bar", "150"), ("Competition Squat", "150"),
        ("Sumo Deadlift", "180"), ("Competition Bench Press", "90"),
        ("Overhead Press (seated)", "50"),
    ):
        rows.append({"Date": source, "Exercise": name, "Weight_Used": load,
                     "RIR": "2", "Reps_Done": "5"})
    # A non-e1RM marker sets the observed gap without contaminating a main-lift estimate.
    rows.append({
        "Date": marker, "Exercise": "Plank", "Weight_Used": "0",
        "RIR": "2", "Reps_Done": "30",
    })
    return rows


def _build_store(readiness_kind: str, gap: int, decay: str, flare: bool):
    for_date = FOR_DATE[gap]
    readiness = make_readiness([{
        "Date": for_date, "Sleep": "4", "Energy": "4", "Mood": "4",
        "Soreness": "4", "Stress": "4",
    }])
    rows = _rows(for_date, gap)
    if readiness_kind == "low":
        readiness = make_readiness([{ "Date": for_date, **LOW_READINESS }])
    training = make_training(rows)
    store = db.Store(":memory:")
    conn = store.connection
    importer.import_export(
        conn, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    if decay == "fresh":
        fresh_on = (_date(for_date) - dt.timedelta(days=7)).isoformat()
        for exercise_id, value in E1RM.items():
            repositories.append_e1rm_override(
                conn, exercise_id=exercise_id, e1rm_kg=value,
                effective_from=fresh_on, reason="matrix fresh e1RM",
            )
    if flare:
        repositories.append_symptom(
            conn, logged_on=for_date, timing="pre_session", region="low_back",
            level=2, note="matrix flare",
        )
    return store, for_date


def _prescription(conn, case: Case, for_date: str):
    return build_prescription(
        conn, for_date=for_date, session_type=case.session_type,
        minimum_session=case.minimum,
        minimum_target_minutes=30 if case.minimum else None,
        technique_throttle=case.throttle,
        deload_decision=DeloadDecision("audit", "scheduled") if case.deload else None,
    )


def _items(prescription) -> dict[str, Any]:
    out = {}
    for item in prescription.items:
        out[item.exercise_id] = item
    return out


def _case_failures(case: Case, prescription) -> list[dict]:
    found = []
    if not prescription.executable:
        found.append({"case": case.label, "kind": "not_executable", "detail": list(prescription.issues)})
        return found
    items = prescription.items
    if not items:
        found.append({"case": case.label, "kind": "empty", "detail": ""})
    ids = [item.exercise_id for item in items]
    if len(ids) != len(set(ids)):
        found.append({"case": case.label, "kind": "duplicate_item", "detail": ids})
    for item in items:
        if item.sets < 1:
            found.append({"case": case.label, "kind": "sets_below_one", "detail": item.exercise_id})
        if item.load_kg is None:
            found.append({"case": case.label, "kind": "missing_load", "detail": item.exercise_id})
        if item.effort_model == "quality":
            if item.rir_target is not None or not item.quality_stop:
                found.append({"case": case.label, "kind": "power_shape", "detail": item.exercise_id})
        elif (item.essential or "PRG-RIR-001" in item.rationale_refs) and (
            item.rir_target is None or not 1 <= item.rir_target <= 4
        ):
            # PRG-RIR-001 scopes the effort window to primary compounds; accessory
            # deload RIR 5 is allowed and must not fail the matrix.
            found.append({"case": case.label, "kind": "rir_window", "detail": f"{item.exercise_id}:{item.rir_target}"})
        if item.load_kg and item.load_factor < 0.80 - 1e-9:
            found.append({"case": case.label, "kind": "load_floor", "detail": f"{item.exercise_id}:{item.load_factor:.4f}"})
    return found


def _pair_failure(base: Case, variant: Case, a, b, factor: str) -> list[dict]:
    found = []
    ai, bi = _items(a), _items(b)
    if not set(bi).issubset(ai):
        found.append({"case": variant.label, "kind": "added_item", "detail": sorted(set(bi) - set(ai))})
    for exercise_id in set(ai) & set(bi):
        left, right = ai[exercise_id], bi[exercise_id]
        if right.sets > left.sets:
            found.append({"case": variant.label, "kind": f"{factor}_increased_sets",
                          "detail": f"{exercise_id}:{left.sets}->{right.sets}"})
        if (left.load_kg is not None and right.load_kg is not None
                and right.load_kg > left.load_kg + LOAD_ROUNDING_TOLERANCE_KG):
            found.append({"case": variant.label, "kind": f"{factor}_increased_load",
                          "detail": f"{exercise_id}:{left.load_kg}->{right.load_kg}"})
        if (left.effort_model != "quality" and right.effort_model != "quality"
                and left.rir_target is not None and right.rir_target is not None
                and right.rir_target < left.rir_target):
            found.append({"case": variant.label, "kind": f"{factor}_lowered_rir",
                          "detail": f"{exercise_id}:{left.rir_target}->{right.rir_target}"})
    return found


def _all_cases(session_types=SESSION_TYPES) -> list[Case]:
    cases = []
    for readiness, gap, decay, deload, flare, minimum, throttle, session_type in product(
        ("normal", "low"), GAPS, ("fresh", "stale"), (False, True),
        (False, True), (False, True), (False, True), session_types,
    ):
        cases.append(Case(readiness, gap, decay, deload, flare, minimum,
                          throttle, session_type))
    return cases


def _paired(cases: list[Case], built: dict[str, Any]) -> list[dict]:
    failures = []
    for factor in ("readiness", "deload", "flare", "minimum", "throttle"):
        for case in cases:
            if factor == "readiness":
                if case.readiness != "low":
                    continue
                other = Case("normal", case.gap, case.decay, case.deload, case.flare,
                             case.minimum, case.throttle, case.session_type)
            else:
                if not getattr(case, factor):
                    continue
                other = Case(
                    case.readiness, case.gap, case.decay,
                    False if factor == "deload" else case.deload,
                    False if factor == "flare" else case.flare,
                    False if factor == "minimum" else case.minimum,
                    False if factor == "throttle" else case.throttle,
                    case.session_type,
                )
            a, b = built.get(other.label), built.get(case.label)
            if a is None or b is None:
                continue
            failures.extend(_pair_failure(other, case, a, b, factor))
    return failures


def _render(summary: dict, failures: list[dict], errors: list[dict]) -> str:
    lines = [
        "# W3 modifier interaction matrix — 2026-10-31",
        "",
        "**Status:** analysis run; no modifier behaviour was changed.",
        "",
        "## Scope",
        "",
        "Synthetic fixtures, all four session types, and every combination of:",
        "",
        "- readiness: normal / low",
        "- continuity gap: 7 / 28 / 56 days",
        "- e1RM source: fresh / stale",
        "- deload: off / scheduled",
        "- back flare: none / level 2",
        "- minimum session: off / 30 minutes",
        "- technique throttle: off / on",
        "",
        f"Total cases: **{summary['cases']}**; built: **{summary['built']}**; "
        f"build errors: **{summary['errors']}**; invariant violations: **{summary['violations']}**.",
        "",
        "## Invariants checked",
        "",
    ]
    lines.extend(f"- {item}" for item in summary["invariants"])
    lines += ["", "## Findings", ""]
    if not failures and not errors:
        lines.append("No invariant violations or build errors were found.")
    else:
        lines.append("These are findings, not fixes. Behaviour was not changed.")
        lines.append("")
        for failure in failures[:200]:
            lines.append(f"- **{failure['kind']}** {failure['case']}: {failure['detail']}")
        if len(failures) > 200:
            lines.append(f"- ... {len(failures) - 200} more violations")
        for error in errors:
            lines.append(f"- **build error** {error['case']}: {error['error']}")
    lines += [
        "",
        "## Interpretation boundary",
        "",
        "This is an invariant audit, not a claim that every combination is desirable training.",
        "It checks that reduction-only modifiers compose without adding work, breaking the RIR",
        "window, or escaping the automatic load floor. Policy-level interactions still require",
        "review.",
        "",
    ]
    return "\n".join(lines)


def run(report: Path, json_report: Path, session_types=SESSION_TYPES) -> int:
    cases = _all_cases(session_types)
    built = {}
    failures = []
    errors = []
    groups = {}
    for case in cases:
        groups.setdefault((case.readiness, case.gap, case.decay, case.flare), []).append(case)
    for (readiness_kind, gap, decay, flare), group in groups.items():
        try:
            store, for_date = _build_store(readiness_kind, gap, decay, flare)
        except Exception as exc:
            for case in group:
                errors.append({"case": case.label, "error": repr(exc)})
            continue
        try:
            for case in group:
                try:
                    prescription = _prescription(store.connection, case, for_date)
                except Exception as exc:
                    errors.append({"case": case.label, "error": repr(exc)})
                    continue
                built[case.label] = prescription
                failures.extend(_case_failures(case, prescription))
        finally:
            store.close()
    failures.extend(_paired(cases, built))
    summary = {
        "cases": len(cases),
        "built": len(built),
        "errors": len(errors),
        "violations": len(failures),
        "factors": {
            "readiness": ["normal", "low"],
            "gap_days": list(GAPS),
            "e1rm": ["fresh", "stale"],
            "deload": [False, True],
            "flare": [False, True],
            "minimum_session": [False, True],
            "technique_throttle": [False, True],
            "session_types": list(session_types),
        },
        "invariants": [
            "executable and non-empty",
            "no duplicate items",
            "sets >= 1",
            "load present",
            "non-power RIR 1-4",
            "power RIR null and quality stop present",
            "automatic load factor >= 0.80",
            "reduction-only modifiers do not add items",
            "readiness/deload/flare/minimum/throttle do not increase sets or load",
            "readiness/deload/flare/minimum/throttle do not lower a non-power RIR target",
        ],
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(_render(summary, failures, errors), encoding="utf-8")
    json_report.write_text(json.dumps(
        {"summary": summary, "errors": errors, "violations": failures}, indent=2
    ), encoding="utf-8")
    print(f"cases={len(cases)} built={len(built)} errors={len(errors)} violations={len(failures)}")
    return 1 if errors or failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path,
                        default=ROOT / "docs" / "W3-INTERACTION-MATRIX-2026-10-31.md")
    parser.add_argument("--json", type=Path,
                        default=ROOT / "docs" / "W3-INTERACTION-MATRIX-2026-10-31.json")
    parser.add_argument("--session-type", action="append", choices=SESSION_TYPES,
                        help="run one session-type shard; repeat for multiple")
    args = parser.parse_args()
    types = tuple(args.session_type) if args.session_type else SESSION_TYPES
    return run(args.report, args.json, types)


if __name__ == "__main__":
    raise SystemExit(main())
