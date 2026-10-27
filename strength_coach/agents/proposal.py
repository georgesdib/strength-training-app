"""A structured proposal the model may make, and the policy check that decides it.

The model never writes a prescription. It proposes a small set of structural edits -- swap an
accessory, change set counts, drop a non-essential item, reorder -- and Python rebuilds the
affected item with the same load solver the deterministic path uses. Anything the model could
express as a number (load, RIR, velocity) is rejected before it can reach an artifact, because
"never let the LLM do arithmetic" is a structural rule, not a trust relationship.

The proposal is only attempted on a deterministic session that no safety modifier has already
changed. If a fatigue or back-flare modifier fired, the session is not open to model edits: the
safety decision outranks any convenience.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from strength_coach.domain import e1rm as e1rm_mod
from strength_coach.prescribe import constraints, engine, loads, schemes as schemes_mod, templates
from strength_coach.store import queries
from strength_coach.prescribe.config import Thresholds
from strength_coach.prescribe.models import Prescription, PrescriptionItem

SYSTEM = (
    "You are a strength coach proposing at most one structural change to a session. "
    "Return ONLY a JSON object matching the schema. Never include a load, weight, RIR, "
    "percentage or velocity: those are computed by the system and any number you write "
    "will be rejected."
)

ACTIONS = ("substitute", "set_sets", "drop", "reorder", "choose", "set_scheme")
REQUIRED_KEYS = {
    "substitute": {"action", "exercise", "with"},
    "set_sets": {"action", "exercise", "sets"},
    "drop": {"action", "exercise"},
    "reorder": {"action", "order"},
    # A menu choice is still a choice, not an arithmetic: the model names an option that
    # Python computed, so the number on the bar never comes from the model.
    "choose": {"action", "exercise", "option"},
    "set_scheme": {"action", "exercise", "scheme"},
}
OPTIONS = ("keep", "easier", "harder", "heavier", "lighter")
TOP_KEYS = {"summary", "changes"}
# A proposal may not carry a computed number, however it is spelled.
FORBIDDEN_KEYS = {
    "load", "load_kg", "weight", "weight_kg", "rir", "rir_target", "velocity",
    "velocity_target", "percent", "percentage", "kg", "lbs",
}


class ProposalError(ValueError):
    """The model's proposal is not a valid proposal. The caller keeps the deterministic one."""


@dataclass(frozen=True)
class Change:
    action: str
    exercise: str | None = None
    replacement: str | None = None
    sets: int | None = None
    order: tuple[str, ...] = ()
    option: str | None = None
    scheme: str | None = None


@dataclass(frozen=True)
class Proposal:
    summary: str
    changes: tuple[Change, ...]
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class Outcome:
    accepted: bool
    prescription: Prescription | None
    reasons: tuple[str, ...] = ()
    summary: str = ""


def _reject_forbidden(payload: Any, path: str = "") -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            lowered = str(key).strip().lower()
            if lowered in FORBIDDEN_KEYS:
                raise ProposalError(
                    f"{path or 'proposal'} contains {key!r}: the model may not supply computed "
                    "numbers"
                )
            _reject_forbidden(value, f"{path}.{key}" if path else str(key))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            _reject_forbidden(value, f"{path}[{index}]")


def _load(raw: str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(raw, Mapping):
        payload: Any = raw
    else:
        text = str(raw).strip()
        if text.startswith("```"):
            lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProposalError(f"not valid JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ProposalError("proposal must be a JSON object")
    return payload


def parse(raw: str | Mapping[str, Any]) -> Proposal:
    """Validate the shape and reject anything that carries a computed number."""
    payload = _load(raw)
    _reject_forbidden(payload)

    extra = set(payload) - TOP_KEYS
    if extra:
        raise ProposalError(f"unknown top-level keys: {sorted(extra)}")

    changes_raw = payload.get("changes")
    if not isinstance(changes_raw, list) or not changes_raw:
        raise ProposalError("changes must be a non-empty list")

    changes: list[Change] = []
    for index, entry in enumerate(changes_raw):
        where = f"changes[{index}]"
        if not isinstance(entry, Mapping):
            raise ProposalError(f"{where} must be an object")
        action = str(entry.get("action", ""))
        if action not in ACTIONS:
            raise ProposalError(f"{where}.action must be one of {ACTIONS}")
        allowed = REQUIRED_KEYS[action]
        missing = allowed - set(entry)
        extra_keys = set(entry) - allowed
        if missing:
            raise ProposalError(f"{where} missing {sorted(missing)}")
        if extra_keys:
            raise ProposalError(f"{where} has unexpected keys {sorted(extra_keys)}")

        if action == "reorder":
            order = entry["order"]
            if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
                raise ProposalError(f"{where}.order must be a list of exercise ids")
            changes.append(Change(action=action, order=tuple(order)))
            continue

        exercise = entry["exercise"]
        if not isinstance(exercise, str) or not exercise:
            raise ProposalError(f"{where}.exercise must be a non-empty exercise id")
        if action == "substitute":
            replacement = entry["with"]
            if not isinstance(replacement, str) or not replacement:
                raise ProposalError(f"{where}.with must be a non-empty exercise id")
            changes.append(Change(action=action, exercise=exercise, replacement=replacement))
        elif action == "set_scheme":
            scheme = entry["scheme"]
            if not isinstance(scheme, str) or not scheme:
                raise ProposalError(f"{where}.scheme must be a non-empty scheme name")
            changes.append(Change(action=action, exercise=exercise, scheme=scheme))
        elif action == "choose":
            option = entry["option"]
            if option not in OPTIONS:
                raise ProposalError(f"{where}.option must be one of {OPTIONS}")
            changes.append(Change(action=action, exercise=exercise, option=option))
        elif action == "set_sets":
            sets = entry["sets"]
            if not isinstance(sets, int) or isinstance(sets, bool):
                raise ProposalError(f"{where}.sets must be an integer")
            changes.append(Change(action=action, exercise=exercise, sets=sets))
        else:
            changes.append(Change(action=action, exercise=exercise))

    return Proposal(summary=str(payload.get("summary", "")).strip(),
                    changes=tuple(changes), raw=payload)


def describe(proposal: Proposal) -> str:
    lines = []
    for change in proposal.changes:
        if change.action == "substitute":
            lines.append(f"substitute {change.exercise} -> {change.replacement}")
        elif change.action == "set_sets":
            lines.append(f"set {change.exercise} to {change.sets} sets")
        elif change.action == "drop":
            lines.append(f"drop {change.exercise}")
        else:
            lines.append(f"reorder to {', '.join(change.order)}")
    return "; ".join(lines)


def menu(prescription: Prescription, document) -> dict[str, dict[str, dict[str, float | int | None]]]:
    """Python-computed options per item. The model may name one; it may never write one.

    The RIR options are bounded by PRG-RIR-001's window, so relaxing that rule (with evidence)
    widens the menu automatically instead of requiring a code change. A load option is always
    a real increment; an RIR option is re-solved from the same e1RM, so the pair stays coherent.
    """
    rule = document.rule("PRG-RIR-001")
    params = rule.params or {}
    default_window = params.get("default_rir") or {}
    per_exercise = params.get("per_exercise_rir") or {}

    menus: dict[str, dict[str, dict[str, float | int | None]]] = {}
    for item in prescription.items:
        options: dict[str, dict[str, float | int | None]] = {
            "keep": {"load_kg": item.load_kg, "rir_target": item.rir_target},
        }
        if item.effort_model == "quality":
            # Quality work has no RIR/load menu; the stop rule is the instruction.
            menus[item.exercise_id] = options
            continue
        increment = item.rounding_increment_kg
        if item.load_kg is not None and item.load_kg > 0:
            options["heavier"] = {
                "load_kg": item.load_kg + increment,
                "rir_target": item.rir_target,
            }
            if item.load_kg - increment > 0:
                options["lighter"] = {
                    "load_kg": item.load_kg - increment,
                    "rir_target": item.rir_target,
                }
            window = per_exercise.get(item.exercise_id, default_window)
            if window:
                low, high = int(window["min"]), int(window["max"])
                e1rm = e1rm_mod.epley_rir_adjusted(
                    item.load_kg, item.reps_low, item.rir_target
                )
                for name, delta in (("harder", -1), ("easier", 1)):
                    rir = item.rir_target + delta
                    if low <= rir <= high:
                        solved = loads.solve_load(e1rm, item.reps_low, rir, increment)
                        if solved > 0:
                            options[name] = {"load_kg": solved, "rir_target": rir}
        menus[item.exercise_id] = options
    return menus


def allowed_substitutes(conn, context, prescription: Prescription) -> dict[str, list[str]]:
    """Same-pattern alternatives that the stored constraints do not veto.

    Narrow on purpose: a swap that changes the movement pattern is not a substitution, it is a
    different session, and only the deterministic engine may design one.
    """
    current = {item.exercise_id for item in prescription.items}
    candidates = [eid for eid in context.entities if eid not in current]
    report = constraints.evaluate(conn, candidates)
    vetoed = {exercise_id for exercise_id, _ in report.vetoes}
    ratings = queries.exercise_suitability(conn)

    def usable(eid: str, pattern: str, essential: bool) -> bool:
        entity = context.entity(eid)
        if entity.get("pattern") != pattern or eid in vetoed:
            return False
        if not essential:
            return True
        # A main-lift swap is a programme change: the athlete must have rated the replacement.
        rating = ratings.get(eid)
        return bool(
            rating
            and rating["can_do"] and rating["will_do"] and not rating["feels_bad"]
            and entity.get("primary_compound")
        )

    options: dict[str, list[str]] = {}
    for item in prescription.items:
        pattern = context.entity(item.exercise_id).get("pattern")
        if not pattern:
            continue
        options[item.exercise_id] = [
            eid for eid in candidates if usable(eid, pattern, item.essential)
        ]
    return options


def _last_main_substitution(conn) -> str | None:
    """Date of the most recent accepted main-lift swap, from the run trace."""
    row = conn.execute(
        "SELECT created_at FROM run_event WHERE kind = 'policy_verdict' "
        "AND payload LIKE ? ORDER BY rowid DESC LIMIT 1",
        ('%"main_substitution": true%',),
    ).fetchone()
    return str(row["created_at"])[:10] if row is not None else None


def scheme_options(prescription: Prescription, schemes: schemes_mod.Schemes) -> dict[str, list[str]]:
    """Rep schemes each item may use. Main lifts get strength schemes; accessories get volume."""
    return {
        item.exercise_id: (
            [] if item.effort_model == "quality" else [
                name for name in schemes.schemes
                if schemes.applicable(name, exercise_id=item.exercise_id,
                                      essential=item.essential)
            ]
        )
        for item in prescription.items
    }


def prompt_for(
    prescription: Prescription,
    allowed: Mapping[str, Iterable[str]],
    options: Mapping[str, Mapping[str, object]] | None = None,
    reps: Mapping[str, Iterable[str]] | None = None,
) -> str:
    items = []
    for item in prescription.items:
        effort = (
            f"quality stop: {item.quality_stop}"
            if item.effort_model == "quality"
            else f"@ RIR {item.rir_target}"
        )
        line = (
            f"- {item.exercise_id}: {item.sets} x {item.reps_low}-{item.reps_high} "
            f"{effort}{' (essential)' if item.essential else ''}"
        )
        if item.exercise_id in allowed:
            alternatives = list(allowed[item.exercise_id])
            if alternatives:
                label = "main-lift alternatives" if item.essential else "same-pattern alternatives"
                line += f" | {label}: {', '.join(alternatives)}"
        if options and item.exercise_id in options:
            offered = [name for name in options[item.exercise_id] if name != "keep"]
            if offered:
                line += f" | menu: {', '.join(offered)}"
        if reps and item.exercise_id in reps and reps[item.exercise_id]:
            line += f" | rep schemes: {', '.join(reps[item.exercise_id])}"
        items.append(line)

    return (
        "Current deterministic session for "
        f"{prescription.for_date} ({prescription.session_type}):\n"
        + "\n".join(items)
        + "\n\nPropose at most one structural change. Allowed actions:\n"
        "- substitute: replace a NON-essential item with a same-pattern alternative\n"
        "- set_sets: change an item's set count (small change only)\n"
        "- drop: remove a non-essential item\n"
        "- reorder: permute all exercise ids\n"
        "- choose: pick one of an item's menu options (easier, harder, heavier, lighter)\n"
        "- set_scheme: change an item's rep scheme to one listed for it\n\n"
        "Return JSON only, exactly this shape:\n"
        '{"summary": "<one sentence>", '
        '"changes": [{"action": "substitute", "exercise": "<id>", "with": "<id>"}]}\n'
        "Do not include loads, RIR, percentages or velocity."
    )


def assess(
    conn,
    prescription: Prescription,
    proposal: Proposal,
    *,
    context,
    document,
    thresholds: Thresholds,
    decisions: Mapping[str, Any],
) -> Outcome:
    """Apply the proposal and judge the result with the same validators as the engine."""
    reasons: list[str] = []
    if prescription.fallback_level != "full" or context.symptom_flare:
        return Outcome(
            accepted=False,
            prescription=None,
            reasons=("the session was already modified by a safety rule; proposals are not "
                     "applied to a downgraded session",),
            summary=proposal.summary,
        )

    menus = menu(prescription, document)
    main_substitutions = 0
    schemes = schemes_mod.Schemes.load()
    template = templates.SessionTemplate.load(prescription.session_type)
    items = list(prescription.items)
    by_id = {item.exercise_id: item for item in items}

    for change in proposal.changes:
        if change.action == "reorder":
            current = [item.exercise_id for item in items]
            if sorted(change.order) != sorted(current):
                reasons.append("reorder must list every current exercise exactly once")
            else:
                position = {eid: idx for idx, eid in enumerate(change.order)}
                items = sorted(items, key=lambda item: position[item.exercise_id])
                for index, item in enumerate(items):
                    items[index] = replace(item, order_index=index)
            continue

        item = by_id.get(change.exercise or "")
        if item is None:
            reasons.append(f"unknown exercise {change.exercise!r} in the prescription")
            continue
        if item.effort_model == "quality" and change.action != "keep":
            reasons.append(
                f"{item.exercise_id}: power work is quality-limited; no load, RIR or scheme change"
            )
            continue

        if change.action == "substitute":
            if item.essential:
                if main_substitutions >= 1:
                    reasons.append("at most one main-lift substitution per proposal")
                    continue
                rating = queries.exercise_suitability(conn).get(change.replacement or "")
                if not (
                    rating and rating["can_do"] and rating["will_do"]
                    and not rating["feels_bad"]
                ):
                    reasons.append(
                        f"{change.replacement}: an essential lift needs a recorded "
                        "can-do / will-do rating with no 'feels bad'"
                    )
                    continue
                if not context.entity(change.replacement or "").get("primary_compound"):
                    reasons.append(f"{change.replacement}: not a primary compound")
                    continue
                last = _last_main_substitution(conn)
                if last is not None:
                    days = (
                        datetime.date.fromisoformat(prescription.for_date)
                        - datetime.date.fromisoformat(last)
                    ).days
                    if days < thresholds.proposal_main_substitution_min_interval_days:
                        reasons.append(
                            "a main lift was substituted "
                            f"{days} days ago; the minimum interval is "
                            f"{thresholds.proposal_main_substitution_min_interval_days}"
                        )
                        continue
                main_substitutions += 1
            old_pattern = context.entity(item.exercise_id).get("pattern")
            new_pattern = context.entity(change.replacement or "").get("pattern")
            if not new_pattern:
                reasons.append(f"{change.replacement}: not a known exercise")
                continue
            if change.replacement in by_id:
                reasons.append(f"{change.replacement}: already in the session")
                continue
            if new_pattern != old_pattern:
                reasons.append(
                    f"{change.replacement}: pattern {new_pattern!r} does not match "
                    f"{old_pattern!r}"
                )
                continue
            slot = templates.Slot(
                id=f"proposal:{item.exercise_id}",
                sets=item.sets,
                reps_low=item.reps_low,
                reps_high=item.reps_high,
                rir_low=item.rir_target,
                rir_high=item.rir_target,
                rest_s=item.rest_s,
                essential=item.essential,
                load_source="e1rm" if item.essential else "double_progression",
                exercise=change.replacement,
            )
            new_item, _ = engine.build_item(
                conn, context, slot, item.order_index, thresholds,
                prescription.for_date, decisions, template if item.essential else None,
            )
            index = items.index(item)
            items[index] = new_item
            by_id.pop(item.exercise_id, None)
            by_id[new_item.exercise_id] = new_item

        elif change.action == "choose":
            table = menus.get(item.exercise_id, {})
            chosen = table.get(change.option or "")
            if chosen is None:
                reasons.append(
                    f"{item.exercise_id}: option {change.option!r} is not offered"
                )
                continue
            index = items.index(item)
            items[index] = replace(
                item, load_kg=chosen["load_kg"], rir_target=chosen["rir_target"]
            )
            by_id[item.exercise_id] = items[index]

        elif change.action == "set_scheme":
            try:
                scheme = schemes.get(change.scheme or "")
            except schemes_mod.SchemeError:
                reasons.append(f"{change.exercise}: unknown rep scheme {change.scheme!r}")
                continue
            if not schemes.applicable(change.scheme or "",
                                      exercise_id=item.exercise_id,
                                      essential=item.essential):
                reasons.append(
                    f"{item.exercise_id}: scheme {change.scheme!r} is not allowed for this item"
                )
                continue
            slot = templates.Slot(
                id=f"scheme:{item.exercise_id}",
                sets=item.sets,
                reps_low=scheme.reps_low,
                reps_high=scheme.reps_high,
                rir_low=item.rir_target,
                rir_high=item.rir_target,
                rest_s=item.rest_s,
                essential=item.essential,
                load_source="e1rm" if item.essential else "double_progression",
                exercise=item.exercise_id,
            )
            rebuilt, _ = engine.build_item(
                conn, context, slot, item.order_index, thresholds,
                prescription.for_date, decisions, template,
            )
            index = items.index(item)
            items[index] = rebuilt
            by_id[item.exercise_id] = rebuilt

        elif change.action == "set_sets":
            if item.essential:
                reasons.append(f"{change.exercise}: essential set counts are not open to change")
                continue
            sets = int(change.sets or 0)
            if sets < 1 or sets > thresholds.proposal_max_sets:
                reasons.append(
                    f"{change.exercise}: {sets} sets is outside 1..{thresholds.proposal_max_sets}"
                )
                continue
            if abs(sets - item.sets) > thresholds.proposal_max_set_change:
                reasons.append(
                    f"{change.exercise}: change of {abs(sets - item.sets)} sets exceeds "
                    f"{thresholds.proposal_max_set_change}"
                )
                continue
            index = items.index(item)
            items[index] = replace(item, sets=sets)
            by_id[item.exercise_id] = items[index]

        elif change.action == "drop":
            if item.essential:
                reasons.append(f"{change.exercise}: an essential lift cannot be dropped")
                continue
            items.remove(item)
            by_id.pop(item.exercise_id, None)

    if not items:
        reasons.append("a proposal may not leave the session empty")

    if not reasons:
        issues = engine.validate_prescription(
            tuple(items), context, document, prescription.session_type, prescription.for_date
        )
        report = constraints.evaluate(conn, [item.exercise_id for item in items])
        issues += [f"CONSTRAINT_VETO:{eid}:{why}" for eid, why in report.vetoes]
        reasons.extend(issues)

    if reasons:
        return Outcome(accepted=False, prescription=None, reasons=tuple(reasons),
                       summary=proposal.summary)

    updated = replace(
        prescription,
        items=tuple(items),
        warnings=prescription.warnings + (f"LLM proposal accepted: {proposal.summary}",),
        notes={**prescription.notes, "proposal": proposal.summary,
               "proposal_changes": describe(proposal)},
    )
    return Outcome(accepted=True, prescription=updated, summary=proposal.summary)
