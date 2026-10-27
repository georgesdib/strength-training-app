"""Render the programme summary from configuration.

The strength-programme review and any weekly-volume or spinal-exposure summary must describe
the *current* templates. Hand-written tables drifted once already: the review still named a
single-leg RDL after `DEC-SPINE-05` replaced it with a sumo deadlift. This module renders those
factual tables from `session-types.v1.yaml`, the exercise taxonomy, the volume config and the
spinal rule, so a template change either updates the document or fails its test.

Display grouping is deliberate. The weekly table groups exercise ids into the lift groups a
reader thinks in (squat, bench, trap-bar, sumo, ...), not the raw taxonomy patterns: split
squat belongs to the squat pattern for the volume ledger, but the review reports it on its own
line. Every template exercise must belong to exactly one group; an unknown id raises rather
than being silently dropped.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from strength_coach.prescribe import templates
from strength_coach.rules import load_document
from strength_coach.utils import exercises, paths

BEGIN = "<!-- BEGIN GENERATED PROGRAMME SUMMARY -->"
END = "<!-- END GENERATED PROGRAMME SUMMARY -->"

# The documented balanced six-session cycle: two squat, two hinge, two bench emphasis.
CYCLE: tuple[str, ...] = ("squat", "hinge", "bench_squat", "squat", "hinge", "bench_hinge")

# One display group per exercise a template may prescribe. The label is the review's row name.
LIFT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("squat (SSB main + competition support)", ("ssb_squat", "competition_squat")),
    ("bench (main + support)", ("bench_press", "bench_press_narrow", "bench_press_pause")),
    ("trap-bar deadlift", ("trap_bar_deadlift",)),
    ("sumo deadlift", ("sumo_deadlift",)),
    ("back extension", ("back_extension", "hyperextension")),
    ("horizontal row", ("dumbbell_row",)),
    ("vertical pull", ("pull_up", "lat_pulldown")),
    ("overhead press", ("overhead_press_seated",)),
    ("split squat", ("split_squat",)),
    ("core", ("ab_wheel", "hanging_leg_raise")),
    ("power", ("box_jump",)),
)

class SummaryError(ValueError):
    """The configuration cannot be summarised without guessing."""


@dataclass(frozen=True)
class SessionRow:
    session_type: str
    work: list[str]
    sets: int
    spinal_cost: float


def _exercise_id(slot) -> str:
    exercise = slot.exercise or (slot.variants[0] if slot.variants else None)
    if exercise is None:
        raise SummaryError(f"slot {slot.id!r} has no exercise")
    return str(exercise)


def _display(entity: Mapping[str, object], exercise_id: str) -> str:
    return str(entity.get("display") or exercise_id)


def _rir(slot) -> str:
    if slot.rir_low is None:
        return "no RIR"
    if slot.rir_low == slot.rir_high:
        return f"RIR {slot.rir_low}"
    return f"RIR {slot.rir_low}–{slot.rir_high}"


def _slot_work(slot, entities: Mapping[str, Mapping[str, object]]) -> str:
    if slot.exercise:
        display = _display(entities.get(slot.exercise, {}), slot.exercise)
    else:
        display = " / ".join(
            _display(entities.get(variant, {}), variant) for variant in slot.variants
        )
    # Power is quality-limited. The template's RIR value is a fallback, not the operative
    # instruction (DEC-POWER-02); showing it as an RIR target is the defect being fixed.
    effort = "quality stop" if slot.power else _rir(slot)
    return f"{display} {slot.sets}×{slot.reps_low}–{slot.reps_high} @ {effort}"


def _spinal_costs() -> tuple[dict[str, float], set[str], float]:
    rule = load_document().rule("PRG-SPINE-001")
    params = rule.params
    costs = {str(k): float(v) for k, v in (params.get("costs") or {}).items()}
    excluded = {str(v) for v in (params.get("excluded_patterns") or ())}
    cap = float(params.get("cap", 6))
    return costs, excluded, cap


def _session_spinal_cost(
    slots: Iterable[object],
    entities: Mapping[str, Mapping[str, object]],
    costs: Mapping[str, float],
    excluded: set[str],
) -> float:
    seen: set[str] = set()
    total = 0.0
    for slot in slots:
        exercise_id = _exercise_id(slot)
        if exercise_id in seen:
            continue
        seen.add(exercise_id)
        entity = entities.get(exercise_id, {})
        if not entity.get("high_fatigue_spinal", False):
            continue
        if str(entity.get("pattern")) in excluded:
            continue
        cost = costs.get(exercise_id, entity.get("spinal_cost"))
        if cost is not None:
            total += float(cost)
    return total


def session_rows() -> list[SessionRow]:
    entities = exercises.taxonomy().entities
    costs, excluded, _cap = _spinal_costs()
    rows: list[SessionRow] = []
    for session_type in templates.SESSION_TYPES:
        template = templates.SessionTemplate.load(session_type)
        rows.append(
            SessionRow(
                session_type=session_type,
                work=[_slot_work(slot, entities) for slot in template.slots],
                sets=sum(int(slot.sets) for slot in template.slots),
                spinal_cost=_session_spinal_cost(template.slots, entities, costs, excluded),
            )
        )
    return rows


def group_for(exercise_id: str) -> str | None:
    for label, members in LIFT_GROUPS:
        if exercise_id in members:
            return label
    return None


def weekly_sets() -> dict[str, float]:
    """Sets per week per display group over the six-session cycle."""
    totals: dict[str, float] = {label: 0.0 for label, _members in LIFT_GROUPS}
    for session_type in CYCLE:
        template = templates.SessionTemplate.load(session_type)
        for slot in template.slots:
            exercise_id = _exercise_id(slot)
            label = group_for(exercise_id)
            if label is None:
                raise SummaryError(f"{exercise_id}: no display group for the programme summary")
            totals[label] += float(slot.sets)
    return {label: sets / 2.0 for label, sets in totals.items()}


def _format_sets(value: float) -> str:
    return f"{value:g}"


def source_digest() -> str:
    """A stable fingerprint of every config input the summary reads."""
    sources = (
        paths.session_types_yaml(),
        paths.taxonomy_yaml(),
        paths.volume_yaml(),
        paths.programme_rules_yaml(),
    )
    digest = hashlib.sha256()
    for path in sources:
        digest.update(Path(path).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def render() -> str:
    """The generated block, including its markers and source digest."""
    rows = session_rows()
    sessions = {row.session_type: row for row in rows}
    totals = weekly_sets()
    total_sets = sum(totals.values())
    week_costs = []
    for start in (0, 3):
        week = CYCLE[start:start + 3]
        week_costs.append(sum(sessions[name].spinal_cost for name in week))
    _costs, _excluded, cap = _spinal_costs()

    lines = [
        BEGIN,
        f"<!-- source:sha256:{source_digest()} -->",
        "",
        "| session type | work | sets | spinal cost |",
        "|---|---|---|---:|",
    ]
    for row in rows:
        work = "; ".join(row.work).replace("|", "\\|")
        lines.append(
            f"| **{row.session_type}** | {work} | {row.sets} | {row.spinal_cost:g} |"
        )
    lines.extend([
        "",
        "Over six sessions (two weeks): squat, hinge, bench+squat, squat, hinge, bench+hinge.",
        f"Planned average is **{_format_sets(total_sets)} working sets/week** across three sessions.",
        "",
        "| lift group | sets/week |",
        "|---|---:|",
    ])
    for label, _members in LIFT_GROUPS:
        lines.append(f"| {label} | {_format_sets(totals[label])} |")
    lines.append(f"| **total** | **{_format_sets(total_sets)}** |")
    lines.extend([
        "",
        f"Counted spinal cost: **{week_costs[0]:g}** for the first week "
        f"(squat, hinge, bench+squat) and **{week_costs[1]:g}** for the second "
        f"(squat, hinge, bench+hinge), against a cap of **{cap:g}**.",
        END,
    ])
    return "\n".join(lines)


def extract(text: str) -> str:
    """The block between the markers, markers included."""
    start = text.find(BEGIN)
    end = text.find(END)
    if start < 0 or end < 0 or end < start:
        raise SummaryError("the programme-summary markers are missing from the document")
    return text[start:end + len(END)]


def replace(text: str, block: str) -> str:
    """Replace the marked block, keeping everything around it."""
    old = extract(text)
    return text.replace(old, block, 1)
