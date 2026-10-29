#!/usr/bin/env python
"""Render the worked example in docs/WORKOUT-GENERATION.md from a synthetic fixture.

    python tools/workout_generation_example.py            # print the block
    python tools/workout_generation_example.py --check    # exit 1 when the document is stale
    python tools/workout_generation_example.py --write    # replace the marked block

The example is an engine output, not a hand-computed illustration. It imports the same
raw-shaped synthetic rows as tests/test_prescribe.py::BASE_HISTORY (the test asserts the two
stay equal), runs build_prescription twice, and renders every displayed number from the
result. A template, threshold or engine change therefore either updates the document or fails
tests/test_workout_generation_doc.py.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import math
import re
import sys
from contextlib import contextmanager
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from conftest import make_readiness, make_training  # noqa: E402

from strength_coach.domain import e1rm as e1rm_mod  # noqa: E402
from strength_coach.prescribe import build_prescription, loads  # noqa: E402
from strength_coach.store import db, importer  # noqa: E402
from strength_coach.utils import exercises, paths  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "workout_generation_example.yaml"
DOC = ROOT / "docs" / "WORKOUT-GENERATION.md"
BEGIN = "<!-- BEGIN GENERATED WORKOUT EXAMPLE -->"
END = "<!-- END GENERATED WORKOUT EXAMPLE -->"
STALE_HINT = "run: python tools/workout_generation_example.py --write"


class ExampleError(ValueError):
    """The fixture or engine output cannot be rendered without guessing."""


def load_fixture(path: Path = FIXTURE) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@contextmanager
def _store(rows: list[dict], readiness_rows: list[dict]):
    training = make_training(rows)
    readiness = make_readiness(readiness_rows or [{}])
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection,
            training,
            readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        yield store.connection
    finally:
        store.close()


def build(fixture: dict | None = None) -> tuple[object, object]:
    """Return the normal and poor-readiness prescriptions for the fixture."""
    data = fixture or load_fixture()
    for_date = str(data["for_date"])
    session_type = str(data["session_type"])
    with _store(data["history"], data.get("readiness") or []) as conn:
        normal = build_prescription(conn, for_date=for_date, session_type=session_type)
    with _store(data["history"], data.get("poor_readiness") or []) as conn:
        poor = build_prescription(conn, for_date=for_date, session_type=session_type)
    return normal, poor


def source_digest(fixture: dict | None = None) -> str:
    sources = (
        FIXTURE,
        paths.session_types_yaml(),
        paths.taxonomy_yaml(),
        paths.thresholds_yaml(),
        paths.programme_rules_yaml(),
        paths.readiness_yaml(),
        paths.volume_yaml(),
        paths.config_dir("warmup.v1.yaml"),
    )
    digest = hashlib.sha256()
    for path in sources:
        digest.update(Path(path).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def _display(exercise_id: str) -> str:
    entity = exercises.taxonomy().entities.get(exercise_id, {})
    return str(entity.get("display") or exercise_id)


def _input_load(value: str) -> str:
    if str(value) in ("0", "0.0"):
        return "bodyweight"
    return f"{float(value):g} kg"


def _basis_label(item) -> str:
    if item.load_basis == "bodyweight_total":
        return "Bodyweight"
    if "PRG-RIR-001" in item.rationale_refs:
        return "e1RM"
    if "PRG-DP-001" in item.rationale_refs:
        return "Double progression"
    return item.load_basis


def _effort(item) -> str:
    if item.effort_model != "rir":
        return "quality stop"
    if item.rir_target is None:
        return "—"
    return f"RIR {item.rir_target}"


def _load(item) -> str:
    if item.load_kg is None:
        return "unknown"
    if item.load_basis == "bodyweight_total":
        return f"bodyweight ({item.load_kg:g} kg external)"
    return f"{item.load_kg:g} kg"


def _warmup(item) -> str:
    if not item.warmup:
        return "—"
    return "; ".join(f"{w.load_kg:g} kg × {w.reps}" for w in item.warmup)


def _refs(item) -> str:
    return ", ".join(item.rationale_refs) if item.rationale_refs else "—"


def _source_row(history: list[dict], item, for_date: str) -> dict:
    matches = [
        row for row in history
        if str(row.get("Date", "")) <= for_date
        and exercises.canonical_id(str(row["Exercise"]), for_date) == item.exercise_id
    ]
    if len(matches) != 1:
        raise ExampleError(
            f"{item.exercise_id}: expected exactly one fixture source row, found {len(matches)}"
        )
    return matches[0]


def _load_arithmetic(history: list[dict], item, for_date: str) -> list[str]:
    if item.load_kg is None or item.load_basis == "bodyweight_total":
        return []
    if "PRG-RIR-001" not in item.rationale_refs:
        return []
    row = _source_row(history, item, for_date)
    weight = float(row["Weight_Used"])
    reps = int(row["Reps_Done"])
    rir = int(row["RIR"])
    e1rm = e1rm_mod.epley_rir_adjusted(weight, reps, rir)
    raw = e1rm_mod.load_for_reps(e1rm, item.reps_low, item.rir_target)
    rounded = loads.round_down(raw, item.rounding_increment_kg)
    if not math.isclose(rounded, item.load_kg, abs_tol=1e-9):
        raise ExampleError(
            f"{item.exercise_id}: rendered arithmetic ({rounded}) != engine load ({item.load_kg})"
        )
    return [
        f"- **{_display(item.exercise_id)}:** "
        f"e1RM = {weight:g} × (1 + ({reps} + {rir}) / 30) = **{e1rm:g} kg**; "
        f"load = {e1rm:g} / (1 + ({item.reps_low} + {item.rir_target}) / 30) "
        f"= {raw:.2f} kg → **{item.load_kg:g} kg** "
        f"(round down to {item.rounding_increment_kg:g} kg)."
    ]


def render(fixture: dict | None = None) -> str:
    data = fixture or load_fixture()
    normal, poor = build(data)
    for_date = str(data["for_date"])
    history = data["history"]

    lines = [
        BEGIN,
        f"<!-- source:sha256:{source_digest(data)} -->",
        "",
        "### 12.1 Inputs",
        "",
        f"- **Prescription date:** `{for_date}`",
        f"- **Requested session:** `{normal.session_type}`",
        "- **Readiness fields considered:** "
        f"{', '.join(normal.notes.get('readiness_fields') or []) or 'none'}. There is no "
        "readiness row for this date, so the engine reports readiness unknown and applies no "
        "fatigue modifier.",
        "- **Load increment:** 0.5 kg; loads are rounded down.",
        "- **History available:** only rows dated on or before the prescription date.",
        "",
        "| Exercise in import | Load | Reps | RIR | Date |",
        "|---|---:|---:|---:|---|",
    ]
    for row in history:
        lines.append(
            f"| {row['Exercise']} | {_input_load(row['Weight_Used'])} | "
            f"{row['Reps_Done']} | {row['RIR']} | {row['Date']} |"
        )
    lines.extend([
        "",
        "The Lateral Raise row is part of the shared fixture but has no slot in the `hinge` "
        "template, so it does not enter this session. Its presence also shows that the engine "
        "selects by template rather than prescribing every recorded exercise.",
    ])

    arithmetic = [
        line
        for item in normal.items
        for line in _load_arithmetic(history, item, for_date)
    ]
    lines.extend(["", "### 12.2 Solved loads", ""])
    lines.extend(arithmetic or ["No e1RM-based load needed a derivation in this run."])

    lines.extend([
        "",
        "### 12.3 Resulting prescription",
        "",
        "| Order | Exercise selected | Sets | Reps | Target effort | Load | Load basis | Rest | Warm-up | Provenance |",
        "|---:|---|---:|---:|---|---:|---|---:|---|---|",
    ])
    for item in normal.items:
        lines.append(
            f"| {item.order_index + 1} | {_display(item.exercise_id)} | {item.sets} | "
            f"{item.reps_low}–{item.reps_high} | {_effort(item)} | {_load(item)} | "
            f"{_basis_label(item)} | {item.rest_s} s | {_warmup(item)} | {_refs(item)} |"
        )
    session_time = normal.notes.get("session_time") or {}
    spinal = normal.notes.get("spinal_cap") or {}
    lines.append("")
    if normal.time_cap_s is not None:
        lines.append(
            f"Time cap: **{normal.time_cap_s:,} s** ({normal.time_cap_s // 60} min). "
            f"Engine estimate: **{session_time.get('estimated_minutes', 'unknown')} min**. "
            "The cap is a planning ceiling, not a measured duration."
        )
    if spinal:
        lines.append(
            f"Spinal cost: **{spinal.get('cost')}** against a cap of **{spinal.get('cap')}** "
            f"(week {spinal.get('week')})."
        )
    lines.extend([
        "",
        f"Executable: **{normal.executable}**. Issues: "
        f"{', '.join(normal.issues) if normal.issues else 'none'}.",
        "",
        "Engine warnings:",
        "",
    ])
    lines.extend(f"- {warning}" for warning in normal.warnings)
    if not normal.warnings:
        lines.append("- none")

    score_match = re.search(
        r"MOD-FAT-001: readiness score ([0-9.]+)", "\n".join(poor.warnings)
    )
    score = score_match.group(1) if score_match else "unknown"
    lines.extend([
        "",
        "### 12.4 Poor-readiness comparison",
        "",
        f"The same fixture with a readiness row for `{for_date}` and `Sleep = 2` produces "
        f"fallback level `{poor.fallback_level}` (readiness score {score}). This is the "
        "implemented policy path, not evidence that the threshold is a validated individual "
        "fatigue threshold.",
        "",
        "| Exercise | Sets | Reps | Load | Target effort | Provenance |",
        "|---|---:|---:|---:|---|---|",
    ])
    for item in poor.items:
        lines.append(
            f"| {_display(item.exercise_id)} | {item.sets} | {item.reps_low}–{item.reps_high} | "
            f"{_load(item)} | {_effort(item)} | {_refs(item)} |"
        )
    lines.extend(["", "Readiness warnings:", ""])
    lines.extend(
        f"- {warning}" for warning in poor.warnings if "MOD-FAT-001" in warning
    )
    lines.append(END)
    return "\n".join(lines)


def extract(text: str) -> str:
    start = text.find(BEGIN)
    end = text.find(END)
    if start < 0 or end < 0 or end < start:
        raise ExampleError("the workout-example markers are missing from the document")
    return text[start:end + len(END)]


def replace(text: str, block: str) -> str:
    old = extract(text)
    return text.replace(old, block, 1)


def check(doc: Path = DOC) -> int:
    text = doc.read_text(encoding="utf-8")
    current = extract(text)
    rendered = render()
    if current == rendered:
        print("workout example is current")
        return 0
    print(
        "\n".join(
            difflib.unified_diff(
                current.splitlines(),
                rendered.splitlines(),
                fromfile=str(doc),
                tofile="generated",
                lineterm="",
            )
        )
    )
    print(STALE_HINT)
    return 1


def write(doc: Path = DOC) -> int:
    text = doc.read_text(encoding="utf-8")
    rendered = render()
    if extract(text) == rendered:
        print("workout example is already current")
        return 0
    doc.write_text(replace(text, rendered), encoding="utf-8")
    print(f"updated {doc}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="fail when the document is stale")
    group.add_argument("--write", action="store_true", help="replace the marked block")
    args = parser.parse_args(argv)
    if args.check:
        return check()
    if args.write:
        return write()
    print(render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
