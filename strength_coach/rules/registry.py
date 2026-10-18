"""The predicates the constitution names, implemented once each.

A predicate answers one question about a *context* (stored sets, sessions, taxonomy) and
returns an `Evaluation` with evidence. It never mutates and never decides policy: severity
and the veto/downgrade effect belong to `policy`.

The `unknown` verdict is the point of this module. A rule whose inputs do not exist returns
`unknown` with the exact missing input named, never `pass` -- an unassessable rule must not
be silently counted as compliance (AGENTS.md invariant 12).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping

import pandas as pd

from strength_coach.utils import exercises as exercises_mod

if TYPE_CHECKING:  # avoids a runtime import cycle: loader validates against this module
    from strength_coach.rules.context import RuleContext
    from strength_coach.rules.loader import Rule, RuleDocument

PASS = "pass"
FAIL = "fail"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Evidence:
    """A citable fact. `ref` must resolve (docs/RULES-FORMAT.md §3)."""

    ref: str
    detail: str
    value: float | None = None


@dataclass(frozen=True)
class Evaluation:
    verdict: str
    code: str | None = None
    evidence: tuple[Evidence, ...] = ()
    missing_inputs: tuple[str, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return self.verdict == FAIL

    @property
    def unknown(self) -> bool:
        return self.verdict == UNKNOWN


Predicate = Callable[["RuleDocument", "Rule", "RuleContext"], Evaluation]

_REGISTRY: dict[str, Predicate] = {}


def predicate(name: str) -> Callable[[Predicate], Predicate]:
    """Register a predicate under the name a rule document's `check.fn` uses."""

    def register(fn: Predicate) -> Predicate:
        if name in _REGISTRY:
            raise RuntimeError(f"duplicate predicate registration: {name}")
        _REGISTRY[name] = fn
        return fn

    return register


def get(name: str) -> Predicate:
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"unknown check.fn {name!r}; known: {sorted(_REGISTRY)}") from exc


def registered() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


# --- helpers ---------------------------------------------------------------


def _set_ref(session_id: str, set_id: int) -> str:
    return f"set:{session_id}/{set_id}"


def iso_week(value: Any) -> str:
    stamp = pd.Timestamp(value).date().isocalendar()
    return f"{stamp.year}-W{stamp.week:02d}"


def _window(params: Mapping[str, Any], exercise_id: str) -> tuple[int, int]:
    default = params.get("default_rir") or {"min": 2, "max": 3}
    override = (params.get("per_exercise_rir") or {}).get(exercise_id) or default
    return int(override["min"]), int(override["max"])


def _unknown(missing: Iterable[str], reason: str, **details: Any) -> Evaluation:
    return Evaluation(
        UNKNOWN,
        code=None,
        missing_inputs=tuple(missing),
        details={"reason": reason, **details},
    )


# --- PRG-RIR-001 -----------------------------------------------------------


@predicate("primary_compound_rir_window")
def primary_compound_rir_window(
    document: "RuleDocument", rule: "Rule", context: "RuleContext"
) -> Evaluation:
    """Effort window on primary compounds: no RIR below the floor, no max singles.

    The floor is the veto (the constitution says "no RIR 0-1 sets"); a set *above* the
    window is easier than prescribed, not dangerous, so it is counted and reported but does
    not fail the rule. That reading is recorded as OPEN-QUESTIONS Q7 rather than left
    implicit.
    """
    exercises = document.scope_exercises(rule.scope)
    sets = context.sets
    if sets.empty:
        return _unknown(["set.rir"], "no clean sets in the window")

    scoped = sets[sets["exercise_id"].isin(exercises)] if exercises else sets
    rated = scoped[scoped["is_working_set"] & scoped["rir"].notna()]
    if rated.empty:
        return _unknown(
            ["set.rir"],
            "no RIR-rated working sets on primary compounds",
            scope_size=len(exercises or ()),
        )

    params = rule.params
    suspect = {int(v) for v in (params.get("suspect_rir_values") or ())}
    forbid_single = bool(params.get("forbid_max_single", False))
    single_pct = float(params.get("max_single_pct_e1rm", 0.90))

    evidence: list[Evidence] = []
    below = above = 0
    for row in rated.itertuples(index=False):
        low, high = _window(params, str(row.exercise_id))
        value = int(row.rir)
        if value < low or value in suspect:
            below += 1
            evidence.append(
                Evidence(
                    ref=_set_ref(str(row.session_id), int(row.set_id)),
                    detail=f"{row.exercise_id} at RIR {value}, window {low}-{high}",
                    value=float(value),
                )
            )
        elif value > high:
            above += 1

    singles = 0
    reference = _e1rm_reference(scoped)
    if forbid_single and reference:
        # A single is compared against the lift's best e1RM from *multi-rep* sets. Judging
        # it against its own e1RM would flag every single, since a single trivially equals
        # ~97% of the e1RM extrapolated from itself.
        for row in scoped.itertuples(index=False):
            reps = getattr(row, "reps", None)
            if reps is None or pd.isna(reps) or int(reps) != 1:
                continue
            reference_e1rm = reference.get(str(row.exercise_id))
            load = getattr(row, "e1rm_load_kg", None)
            if reference_e1rm is None or load is None or pd.isna(load):
                continue
            if float(load) >= single_pct * reference_e1rm:
                singles += 1
                evidence.append(
                    Evidence(
                        ref=_set_ref(str(row.session_id), int(row.set_id)),
                        detail=(
                            f"single at {float(load):.1f} kg = "
                            f"{float(load) / reference_e1rm:.0%} of {reference_e1rm:.1f} kg e1RM"
                        ),
                        value=float(load),
                    )
                )

    details = {
        "rated_sets": int(len(rated)),
        "below_floor": below,
        "above_ceiling": above,
        "max_singles": singles,
    }
    if below or singles:
        return Evaluation(FAIL, rule.fail_code, tuple(evidence), (), details)
    return Evaluation(PASS, None, (), (), details)


def _e1rm_reference(scoped: pd.DataFrame) -> dict[str, float]:
    """Best e1RM per lift from multi-rep sets: the honest yardstick for a single."""
    if scoped.empty or "e1rm_kg" not in scoped:
        return {}
    usable = scoped[scoped["reps"].between(2, 8) & scoped["e1rm_kg"].notna()]
    if usable.empty:
        return {}
    return {str(k): float(v) for k, v in usable.groupby("exercise_id")["e1rm_kg"].max().items()}


# --- PRG-SPINE-001 ---------------------------------------------------------


@predicate("weekly_spinal_cap")
def weekly_spinal_cap(
    document: "RuleDocument", rule: "Rule", context: "RuleContext"
) -> Evaluation:
    """Weighted sum of spinal cost per ISO week, capped.

    "Exposures" is ambiguous in the constitution; the weighted reading is ASSUMPTION-02 and
    is recorded in the rule's notes. Costs come from the rule document, falling back to the
    taxonomy's ordinal `spinal_cost` so a new exercise is covered by its own properties.
    """
    params = rule.params
    cap = float(params.get("cap", 3))

    sets = context.sets
    if sets.empty:
        return _unknown(["week.iso_week"], "no clean sets in the window")
    working = sets[sets["is_working_set"]]
    if working.empty:
        return _unknown(["set.is_working_set"], "no working sets in the window")

    per_week = weekly_spinal_costs(rule, context)

    if not per_week:
        # Complete input, zero exposure: that is a genuine pass, not an unknown.
        return Evaluation(PASS, None, (), (), {"weeks_with_spinal_work": 0, "cap": cap})

    evidence = []
    for week, data in sorted(per_week.items()):
        if data["cost"] > cap:
            breakdown = ", ".join(f"{ex} x{n}" for ex, n in sorted(data["exercises"].items()))
            evidence.append(
                Evidence(
                    ref=f"week:{week}",
                    detail=f"weighted spinal cost {data['cost']:g} > cap {cap:g} ({breakdown})",
                    value=float(data["cost"]),
                )
            )

    details = {
        "weeks_with_spinal_work": len(per_week),
        "cap": cap,
        "weighted_costs": {week: round(data["cost"], 2) for week, data in sorted(per_week.items())},
    }
    if evidence:
        return Evaluation(FAIL, rule.fail_code, tuple(evidence), (), details)
    return Evaluation(PASS, None, (), (), details)


# --- PRG-SCHED-001 ---------------------------------------------------------


@predicate("direct_erector_scheduling")
def direct_erector_scheduling(
    document: "RuleDocument", rule: "Rule", context: "RuleContext"
) -> Evaluation:
    """Direct erector work off the hinge day and never stacked with a hinge."""
    sets = context.sets
    if sets.empty:
        return _unknown(["session.day"], "no clean sets in the window")

    params = rule.params
    allowed_days = {str(d) for d in (params.get("allowed_days") or ("A", "C"))}
    forbidden_patterns = {
        str(p) for p in (params.get("forbid_same_session_as_patterns") or ("hinge",))
    }
    day_of: dict[str, str] = {}
    if not context.sessions.empty:
        day_of = {
            str(row.session_id): str(row.day_guess)
            for row in context.sessions.itertuples(index=False)
        }

    evidence: list[Evidence] = []
    with_erector = 0
    for session_id, group in sets.groupby("session_id", sort=True):
        ids = [str(value) for value in group["exercise_id"].unique()]
        erector = [i for i in ids if context.entity(i).get("direct_erector", False)]
        if not erector:
            continue
        with_erector += 1
        hinged = [
            i for i in ids if context.entity(i).get("pattern") in forbidden_patterns
        ]
        day = day_of.get(str(session_id), "unknown")
        if hinged:
            evidence.append(
                Evidence(
                    ref=f"session:{session_id}",
                    detail=(
                        f"direct erector work ({', '.join(erector)}) stacked with a hinge "
                        f"({', '.join(hinged)})"
                    ),
                )
            )
        elif day not in allowed_days and day != "unknown":
            evidence.append(
                Evidence(
                    ref=f"session:{session_id}",
                    detail=f"direct erector work ({', '.join(erector)}) on day {day}, allowed {sorted(allowed_days)}",
                )
            )

    details = {"sessions_with_erector": with_erector, "violations": len(evidence)}
    if evidence:
        return Evaluation(FAIL, rule.fail_code, tuple(evidence), (), details)
    return Evaluation(PASS, None, (), (), details)


# --- PRG-EREC-001 ----------------------------------------------------------


@predicate("erector_dose_ramp")
def erector_dose_ramp(
    document: "RuleDocument", rule: "Rule", context: "RuleContext"
) -> Evaluation:
    """Dose ramp gated on two stable sessions with no symptom flare.

    Two inputs do not exist in the source data, so the honest answer is `unknown` with both
    named. The ramp logic below is complete and will run once the anchor (Q3) and the manual
    symptom input (Q4) are supplied.
    """
    params = rule.params
    missing: list[str] = []
    if context.symptom_flare is None:
        missing.append("symptom.flare")
    if context.block_week_index is None:
        missing.append("block.week_index")
    if missing:
        return _unknown(
            missing,
            "the erector ramp needs a block anchor and a symptom input, neither of which "
            "exists in the export",
        )

    week = int(context.block_week_index)
    phase = _ramp_phase(params, week)
    if phase is None:
        return _unknown(
            ["block.week_index"],
            f"week {week} is outside the configured ramp",
        )

    sessions = context.sessions
    required = int(params.get("stability_sessions_required", 2))
    if len(sessions) < required:
        return _unknown(
            ["session.sets"],
            f"need {required} consecutive sessions to judge stability, have {len(sessions)}",
        )

    erector = context.sets[
        context.sets["exercise_id"].map(
            lambda e: context.entity(str(e)).get("direct_erector", False)
        )
    ]
    if len(erector) == 0:
        return _unknown(["session.sets"], "no direct erector history to ramp from")

    recent = (
        erector.sort_values("date").groupby("session_id")["reps"].sum().tail(required)
    )
    stability_ok = len(recent) >= required and (recent.max() - recent.min()) <= 1
    details = {
        "week": week,
        "phase": phase.get("label"),
        "added_kg": phase.get("added_kg"),
        "set_delta": phase.get("set_delta"),
        "stability_sessions": int(len(recent)),
        "stable": bool(stability_ok),
        "symptom_flare": bool(context.symptom_flare),
    }
    evidence: tuple[Evidence, ...] = ()
    if context.symptom_on:
        evidence = (
            Evidence(
                ref=f"symptom:{context.symptom_on}",
                detail=f"pre-session back level {context.symptom_level}",
                value=float(context.symptom_level) if context.symptom_level is not None else None,
            ),
        )
    if context.symptom_flare or not stability_ok:
        return Evaluation(FAIL, rule.fail_code, evidence, (), details)
    return Evaluation(PASS, None, evidence, (), details)


def spinal_exposures(
    rule: "Rule",
    context: "RuleContext",
    extra: Iterable[tuple[str, str, Any]] = (),
) -> dict[str, dict[tuple[str, str], float]]:
    """week -> {(session_id, exercise_id): spinal_cost} for performed and proposed work.

    `extra` lets the prescription engine cost a *proposed* session with the same function
    that judges performed ones, so the engine cannot drift from the rule it must satisfy.
    """
    params = rule.params
    costs = dict(params.get("costs") or {})
    excluded = {str(p) for p in (params.get("excluded_patterns") or ())}

    # An "exposure" is one exercise in one session, weighted by its spinal cost. Counting
    # per set would make a 12-set trap-bar session equal to twelve exposures and fire the cap
    # every week, which the constitution's own notes warn against; counting per week would
    # almost never fire. The unit is recorded as OPEN-QUESTIONS Q8.
    exposures: dict[str, dict[tuple[str, str], float]] = defaultdict(dict)

    def add(session_id: str, exercise_id: str, when: Any) -> None:
        entity = context.entity(exercise_id)
        if not entity.get("high_fatigue_spinal", False):
            return
        if entity.get("pattern") in excluded:
            return
        cost = costs.get(exercise_id, entity.get("spinal_cost"))
        if cost is None:
            return
        exposures[iso_week(when)][(session_id, exercise_id)] = float(cost)

    working = context.sets[context.sets["is_working_set"]]
    for row in working.itertuples(index=False):
        add(str(row.session_id), str(row.exercise_id), row.date)
    for session_id, exercise_id, when in extra:
        add(str(session_id), str(exercise_id), when)
    return exposures


def weekly_spinal_costs(
    rule: "Rule",
    context: "RuleContext",
    extra: Iterable[tuple[str, str, Any]] = (),
) -> dict[str, dict[str, Any]]:
    """Per-week weighted cost and exercise mix, optionally including a proposed session."""
    return {
        week: {
            "cost": sum(items.values()),
            "exercises": Counter(exercise for (_session, exercise) in items),
        }
        for week, items in spinal_exposures(rule, context, extra).items()
    }


def _ramp_phase(params: Mapping[str, Any], week: int) -> Mapping[str, Any] | None:
    for phase in params.get("phases") or ():
        low, high = (int(v) for v in phase.get("weeks", (0, -1)))
        if low <= week <= high:
            return phase
    return None


# --- PRG-DP-001 ------------------------------------------------------------


@predicate("double_progression_decision")
def double_progression_decision(
    document: "RuleDocument", rule: "Rule", context: "RuleContext"
) -> Evaluation:
    """Hold the load until every comparable set reaches the top of its rep range.

    The decision needs a rep range per exercise, which lives with the day templates and is
    supplied by the prescription engine (phase 5). Until a range is present the rule is
    `unknown` rather than assuming one -- guessing "top of range" would invent a load.
    """
    exercises = document.scope_exercises(rule.scope) or ()
    params = rule.params
    window_sessions = int(rule.check_args.get("window_sessions", 4))
    min_rir = int(params.get("min_rir_at_top", 2))
    increments = params.get("increment_kg") or {}
    default_increment = float(increments.get("default", 2.5))
    per_exercise = increments.get("per_exercise") or {}

    if not context.rep_ranges:
        return _unknown(
            [f"rep_range.{e}" for e in exercises] or ["rep_range"],
            "no rep-range configuration is available; the prescription engine supplies it",
        )

    sets = context.sets
    if sets.empty:
        return _unknown(["set.reps"], "no clean sets in the window")

    decisions: dict[str, Any] = {}
    missing: list[str] = []
    for exercise_id in exercises:
        rep_range = context.rep_ranges.get(exercise_id)
        if rep_range is None:
            missing.append(f"rep_range.{exercise_id}")
            continue
        top = int(rep_range[1])
        history = sets[
            sets["exercise_id"].isin(exercises_mod.history_equivalents(exercise_id))
        ].sort_values(["date", "set_id"])
        if history.empty:
            missing.append(f"set.reps.{exercise_id}")
            continue
        # The decision looks at the last N sessions that actually contain the lift, so an
        # unchanged top set is not washed out by unrelated accessory days in between.
        session_order = list(dict.fromkeys(history["session_id"].astype(str)))
        recent_sessions = set(session_order[-window_sessions:])
        recent = history[history["session_id"].astype(str).isin(recent_sessions)]
        comparable = recent[
            recent["is_working_set"]
            & recent["rir"].notna()
            & ~recent["flags"].str.contains("REPS_TYPO", na=False)
        ]
        if comparable.empty:
            missing.append(f"set.reps.{exercise_id}")
            continue
        at_top = bool((comparable["reps"] >= top).all())
        effort_ok = bool((comparable["rir"] >= min_rir).all())
        increment = float(per_exercise.get(exercise_id, default_increment))
        decisions[exercise_id] = {
            "decision": "add_increment" if (at_top and effort_ok) else "hold_load",
            "increment_kg": increment,
            "sessions_considered": int(comparable["session_id"].nunique()),
        }

    if missing:
        return _unknown(missing, "rep range or comparable sets are missing", decisions=decisions)
    return Evaluation(PASS, None, (), (), {"decisions": decisions})
