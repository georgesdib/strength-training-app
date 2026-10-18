"""The deterministic critique rubric.

Six items are measurable from the export; two are not, and they are stored with
`measurable = 0` rather than a guessed score:

* session duration — there are no timestamps (DQ-SESSION-01, OPEN-QUESTIONS Q5);
* within-set velocity loss — the export stores one mean velocity per set (DEC-VELOCITY-01).

Weights are config-free on purpose: they are a product decision, not a measurement, and the
composite is a weighted mean over the items that were actually measurable. An item with
`measurable = 0` never drags the score toward zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import pandas as pd

from strength_coach.critique import facts as facts_mod
from strength_coach.critique.facts import CritiqueFacts
from strength_coach.rules import load_document

# Weights sum to 1.0 across the measurable items. Duration and velocity loss carry 0.0 because
# they cannot contribute a number today.
RUBRIC_WEIGHTS: Mapping[str, float] = {
    "RIR_ADHERENCE": 0.30,
    "PROGRESSION_ADHERENCE": 0.20,
    "WEEKLY_SPINAL_COST": 0.15,
    "ESSENTIAL_WORK": 0.15,
    "REDUNDANCY": 0.10,
    "ROTATION": 0.10,
    "SESSION_DURATION": 0.00,
    "VELOCITY_LOSS": 0.00,
}

APP_ASSIGNED_LABELS = {"Sheiko"}
ROTATION_STABILITY_FLOOR = 0.5


@dataclass(frozen=True)
class RubricItem:
    key: str
    weight: float
    score: float | None
    measurable: bool
    evidence_refs: tuple[str, ...]
    rule_ids: tuple[str, ...]
    detail: str


@dataclass(frozen=True)
class Critique:
    session_id: str
    facts_hash: str
    items: tuple[RubricItem, ...]
    narrative: str

    @property
    def measurable_items(self) -> tuple[RubricItem, ...]:
        return tuple(item for item in self.items if item.measurable)

    @property
    def composite(self) -> float | None:
        """Weighted mean over measurable items; None when nothing could be scored."""
        weighted = [(i.weight, i.score) for i in self.items if i.measurable and i.score is not None]
        total = sum(weight for weight, _ in weighted)
        if not weighted or total <= 0:
            return None
        return sum(weight * score for weight, score in weighted) / total

    def item(self, key: str) -> RubricItem:
        for candidate in self.items:
            if candidate.key == key:
                return candidate
        raise KeyError(f"unknown rubric item {key!r}")

    @property
    def failures(self) -> tuple[RubricItem, ...]:
        return tuple(i for i in self.measurable_items if (i.score or 0) < 1.0)


def score_session(
    conn,
    session_id: str,
    *,
    document=None,
    facts: CritiqueFacts | None = None,
) -> Critique:
    """Score one stored session.

    `facts` is accepted so a caller that already built them (a backtest, or the CLI showing
    both the facts and the score) does not pay for enrichment twice.
    """
    document = document or load_document()
    facts = facts or facts_mod.build_facts(conn, session_id, document=document)

    items = (
        _rir_adherence(facts, document),
        _progression_adherence(facts),
        _weekly_spinal_cost(facts),
        _essential_work(facts),
        _redundancy(facts),
        _rotation(facts),
        _session_duration(facts),
        _velocity_loss(facts),
    )
    critique = Critique(
        session_id=facts.session_id,
        facts_hash=facts.facts_hash(),
        items=items,
        narrative=_narrative(facts, items),
    )
    return critique


# --- individual items ------------------------------------------------------


def _rir_adherence(facts: CritiqueFacts, document) -> RubricItem:
    """Grinding sets: RIR 0-1, or any set below the window, on primary compounds."""
    exercises = set(document.collection("$primary_compounds"))
    sets = facts.sets
    rated = sets[
        sets["exercise_id"].isin(exercises) & sets["is_working_set"] & sets["rir"].notna()
    ]
    if rated.empty:
        return _unmeasurable("RIR_ADHERENCE", ("PRG-RIR-001",),
                             "no RIR-rated working sets on primary compounds")

    params = document.rule("PRG-RIR-001").params
    default = params.get("default_rir") or {"min": 2, "max": 3}
    per_exercise = params.get("per_exercise_rir") or {}

    compliant = 0
    violations: list[str] = []
    for row in rated.itertuples(index=False):
        window = per_exercise.get(str(row.exercise_id)) or default
        low, high = int(window["min"]), int(window["max"])
        if low <= int(row.rir) <= high:
            compliant += 1
        else:
            violations.append(_set_ref(row.session_id, row.set_id))

    score = compliant / len(rated)
    return RubricItem(
        key="RIR_ADHERENCE",
        weight=RUBRIC_WEIGHTS["RIR_ADHERENCE"],
        score=round(score, 4),
        measurable=True,
        evidence_refs=tuple(violations),
        rule_ids=("PRG-RIR-001",),
        detail=f"{compliant}/{len(rated)} rated sets inside the effort window",
    )


def _progression_adherence(facts: CritiqueFacts) -> RubricItem:
    """Did accessories add a step only when the top of the range was reached?"""
    assessed = 0
    correct = 0
    evidence: list[str] = []
    notes: list[str] = []

    for exercise_id, (_low, high) in facts.accessory_ranges.items():
        current = facts.sets[
            (facts.sets["exercise_id"] == exercise_id)
            & facts.sets["is_working_set"]
            & facts.sets["load_kg"].notna()
        ]
        if current.empty:
            continue
        history = facts.prior_sets[
            (facts.prior_sets["exercise_id"] == exercise_id)
            & facts.prior_sets["is_working_set"]
            & facts.prior_sets["load_kg"].notna()
        ]
        if history.empty:
            continue

        previous_session = history.sort_values(["date", "set_id"])["session_id"].iloc[-1]
        previous = history[history["session_id"] == previous_session]
        comparable = previous[
            previous["rir"].notna() & ~previous["flags"].str.contains("REPS_TYPO", na=False)
        ]
        if comparable.empty:
            continue

        top_reached = bool((comparable["reps"] >= int(high)).all())
        effort_ok = bool((comparable["rir"] >= 2).all())
        expected_add = top_reached and effort_ok

        prev_load = float(previous["load_kg"].max())
        current_load = float(current["load_kg"].max())
        progressed = current_load > prev_load
        assessed += 1
        if expected_add == progressed:
            correct += 1
        else:
            evidence.append(_set_ref(
                current.sort_values(["date", "set_id"])["session_id"].iloc[-1],
                current.sort_values(["date", "set_id"])["set_id"].iloc[-1],
            ))
            notes.append(
                f"{exercise_id}: expected {'add' if expected_add else 'hold'}, "
                f"got {prev_load}->{current_load}"
            )

    if not assessed:
        return _unmeasurable("PROGRESSION_ADHERENCE", ("PRG-DP-001",),
                             "no accessory has two comparable sessions yet")
    return RubricItem(
        key="PROGRESSION_ADHERENCE",
        weight=RUBRIC_WEIGHTS["PROGRESSION_ADHERENCE"],
        score=round(correct / assessed, 4),
        measurable=True,
        evidence_refs=tuple(evidence),
        rule_ids=("PRG-DP-001",),
        detail=f"{correct}/{assessed} accessories progressed as double progression prescribes"
        + (f"; {'; '.join(notes)}" if notes else ""),
    )


def _weekly_spinal_cost(facts: CritiqueFacts) -> RubricItem:
    if facts.context.sets.empty:
        return _unmeasurable("WEEKLY_SPINAL_COST", ("PRG-SPINE-001",), "no sets in the week")
    cap = facts.spine_cap
    cost = facts.week_cost
    score = 1.0 if cost <= cap else max(0.0, 1.0 - (cost - cap) / cap)
    return RubricItem(
        key="WEEKLY_SPINAL_COST",
        weight=RUBRIC_WEIGHTS["WEEKLY_SPINAL_COST"],
        score=round(score, 4),
        measurable=True,
        evidence_refs=(f"week:{facts.week}",),
        rule_ids=("PRG-SPINE-001",),
        detail=f"weighted spinal cost {cost:g} against cap {cap:g}",
    )


def _essential_work(facts: CritiqueFacts) -> RubricItem:
    if not facts.has_template:
        # Day A/C have no prescription template yet, so their essential work is genuinely
        # unassessable rather than absent.
        return _unmeasurable(
            "ESSENTIAL_WORK", (), f"no prescription template for day {facts.day!r}"
        )
    present = {str(e) for e in facts.sets["exercise_id"].unique()}
    covered = [slot for slot, exercises in facts.essential_slots if present & set(exercises)]
    total = len(facts.essential_slots)
    return RubricItem(
        key="ESSENTIAL_WORK",
        weight=RUBRIC_WEIGHTS["ESSENTIAL_WORK"],
        score=round(len(covered) / total, 4),
        measurable=True,
        evidence_refs=(f"session:{facts.session_id}",),
        rule_ids=(),
        detail=f"{len(covered)}/{total} essential slots present",
    )


def _redundancy(facts: CritiqueFacts) -> RubricItem:
    """Hinge stacking and hinge-plus-erector work in one session."""
    if facts.sets.empty:
        return _unmeasurable("REDUNDANCY", ("PRG-SCHED-001",), "no sets in the session")

    ids = {str(e) for e in facts.sets["exercise_id"].unique()}
    hinges = [e for e in ids if facts.entity(e).get("pattern") == "hinge"]
    erector = [e for e in ids if facts.entity(e).get("direct_erector", False)]

    violations = 0
    notes = []
    if erector and hinges:
        violations += 1
        notes.append(f"erector work ({', '.join(sorted(erector))}) with a hinge")
    if len(hinges) > 1:
        violations += len(hinges) - 1
        notes.append(f"{len(hinges)} hinge exercises in one session")

    score = max(0.0, 1.0 - 0.5 * violations)
    return RubricItem(
        key="REDUNDANCY",
        weight=RUBRIC_WEIGHTS["REDUNDANCY"],
        score=round(score, 4),
        measurable=True,
        evidence_refs=(f"session:{facts.session_id}",),
        rule_ids=("PRG-SCHED-001",),
        detail="no stacking" if not notes else "; ".join(notes),
    )


def _rotation(facts: CritiqueFacts) -> RubricItem:
    """How much the session's exercise selection moved versus the previous same-label session.

    Split by provenance: the logging app deliberately rotates variations, so rotation is
    expected there and scored neutral; a self-directed session that churns lift selection is
    the failure pattern.
    """
    label = facts.workout_label
    if not label:
        return _unmeasurable("ROTATION", (), "session has no workout label")

    earlier = facts.sessions[
        (facts.sessions["workout_label"] == label)
        & (facts.sessions["session_id"].astype(str) != facts.session_id)
        & (facts.sessions["occurred_on"] <= pd.Timestamp(facts.occurred_on))
    ]
    if earlier.empty:
        return _unmeasurable("ROTATION", (), f"first {label} session in the record")
    previous_id = str(earlier.iloc[-1]["session_id"])

    current_ids = {str(e) for e in facts.sets["exercise_id"].unique()}
    previous_ids = {
        str(e) for e in facts.context.sets[
            facts.context.sets["session_id"].astype(str) == previous_id
        ]["exercise_id"].unique()
    }
    union = current_ids | previous_ids
    if not union:
        return _unmeasurable("ROTATION", (), "no exercises to compare")

    overlap = len(current_ids & previous_ids) / len(union)
    if label in APP_ASSIGNED_LABELS:
        score = 1.0
        detail = f"{label} is app-assigned: rotation expected (overlap {overlap:.2f})"
    else:
        score = min(1.0, overlap / ROTATION_STABILITY_FLOOR)
        detail = f"{label}: exercise overlap {overlap:.2f} vs previous session"

    return RubricItem(
        key="ROTATION",
        weight=RUBRIC_WEIGHTS["ROTATION"],
        score=round(score, 4),
        measurable=True,
        evidence_refs=(f"session:{facts.session_id}", f"session:{previous_id}"),
        rule_ids=(),
        detail=detail,
    )


def _session_duration(facts: CritiqueFacts) -> RubricItem:
    return _unmeasurable(
        "SESSION_DURATION", (), "no timestamps in the export (DQ-SESSION-01, Q5)"
    )


def _velocity_loss(facts: CritiqueFacts) -> RubricItem:
    return _unmeasurable(
        "VELOCITY_LOSS", ("DEC-VELOCITY-01",),
        "one mean velocity per set; within-set loss is not computable",
    )


# --- helpers ---------------------------------------------------------------


def _set_ref(session_id: Any, set_id: Any) -> str:
    return f"set:{session_id}/{int(set_id)}"


def _unmeasurable(key: str, rule_ids: Iterable[str], detail: str) -> RubricItem:
    return RubricItem(
        key=key,
        weight=RUBRIC_WEIGHTS[key],
        score=None,
        measurable=False,
        evidence_refs=(),
        rule_ids=tuple(rule_ids),
        detail=detail,
    )


def _narrative(facts: CritiqueFacts, items: Iterable[RubricItem]) -> str:
    """A deterministic one-paragraph summary; no model involved."""
    composite = None
    weighted = [(i.weight, i.score) for i in items if i.measurable and i.score is not None]
    total = sum(weight for weight, _ in weighted)
    if weighted and total > 0:
        composite = sum(weight * score for weight, score in weighted) / total
    scored = ", ".join(
        f"{i.key.replace('_', ' ').lower()} {i.score:.2f}"
        for i in items
        if i.measurable and i.score is not None
    )
    head = (
        f"Session {facts.session_id} ({facts.occurred_on}, day {facts.day}). "
        f"Composite {composite:.2f}. " if composite is not None else
        f"Session {facts.session_id} ({facts.occurred_on}, day {facts.day}). "
    )
    return head + (f"Measured: {scored}." if scored else "No item was measurable.")


def persist(conn, critique: Critique, *, run_id: str, critique_id: str | None = None) -> str:
    """Write the critique and its scores as append-only rows."""
    import uuid

    from strength_coach.store import repositories as repo

    identifier = critique_id or uuid.uuid4().hex
    repo.append_critique(
        conn,
        critique_id=identifier,
        run_id=run_id,
        session_id=critique.session_id,
        narrative=critique.narrative,
        facts_hash=critique.facts_hash,
    )
    for item in critique.items:
        repo.append_rubric_score(
            conn,
            critique_id=identifier,
            item=item.key,
            score=item.score,
            weight=item.weight,
            evidence_refs=list(item.evidence_refs),
            rule_ids=list(item.rule_ids),
            measurable=item.measurable,
        )
    return identifier
