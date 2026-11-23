"""The load catalogue shipped with an issued plan (WP0 D9).

The phone must be able to substitute an exercise with no connection, and the replacement load is
a training decision. So the server ships the *decision* — one entry per taxonomy exercise, built
by the resolver itself through `engine.build_item` — and the phone applies only the deterministic
tail: `round_down(base / (1 + (reps + rir) / 30), increment)`.

There is no second implementation of the load rules here. Each entry is the resolver's own output
for that exercise, which is why the parity test can be exact rather than approximate.

Entry shape (`load-catalogue/v1`):

    {
      "load_source": "e1rm" | "double_progression" | "bodyweight" | "power",
      "base_load_kg": float | None,        # e1RM load base, already decayed and calibrated
      "accessory_load_kg": float | None,   # held double-progression load
      "increment_kg": float,
      "bodyweight": bool,
      "power": bool
    }
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from strength_coach.prescribe import config as config_mod
from strength_coach.prescribe import engine, loads, templates
from strength_coach.utils import exercises as exercises_mod

CATALOGUE_VERSION = "load-catalogue/v1"

# A neutral slot shape: the catalogue records the load *base* and the held accessory load, never
# a per-rep target. The client supplies the reps and RIR of the slot it is substituting into.
_SETS = 3
_REPS = 5
_RIR = 2
_REST_S = 120
# Above any configured back-flare erector ceiling, so the dose probe reports the ceiling itself.
_DOSE_PROBE_SETS = 20


def _load_source(props: Mapping[str, Any], *, essential: bool) -> str:
    """The source the replacement path would use for this exercise (DEC-RESOLVER-28)."""
    if props.get("bodyweight_type"):
        return "bodyweight"
    return "e1rm" if essential else "double_progression"


def _slot(
    exercise_id: str, *, essential: bool, props: Mapping[str, Any], sets: int = _SETS
) -> templates.Slot:
    return templates.Slot(
        id=f"catalogue-{'e' if essential else 'a'}-{exercise_id}",
        sets=sets,
        reps_low=_REPS,
        reps_high=_REPS,
        rir_low=_RIR,
        rir_high=_RIR,
        rest_s=_REST_S,
        essential=essential,
        load_source=_load_source(props, essential=essential),
        exercise=exercise_id,
    )


def _entry(
    item,
    *,
    essential: bool,
    increment_kg: float,
    bodyweight: bool,
    power: bool,
    load_source: str,
) -> dict[str, Any]:
    return {
        "load_source": load_source,
        "base_load_kg": item.e1rm_kg if essential else None,
        "accessory_load_kg": None if essential else item.load_kg,
        "increment_kg": float(increment_kg),
        "bodyweight": bool(bodyweight),
        "power": bool(power),
        # A live back flare replaces an erector load outright and caps its sets, which the e1RM
        # tail cannot express. Both are computed through the session's own dose modifier below.
        "dose_load_kg": None,
        "dose_sets_cap": None,
    }


def build_catalogue(
    conn,
    *,
    for_date: str,
    session_type: str,
    thresholds: config_mod.Thresholds | None = None,
    calibration_factors: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build every entry the phone may need to substitute offline.

    Cost is two `build_item` calls per taxonomy exercise against one shared history context, so
    it stays a single pass over the same facts the plan build already loaded.
    """
    resolved = thresholds or config_mod.Thresholds.load()
    template = templates.SessionTemplate.load(session_type)
    from strength_coach.rules import RuleContext

    context = RuleContext.from_store(conn, end=for_date, rep_ranges=template.rep_ranges())
    if calibration_factors is None:
        from strength_coach.features import e1rm_calibration as calibration_feature

        calibration_factors = calibration_feature.factors(
            conn, for_date, window_days=resolved.e1rm_window_days
        )

    exercises: dict[str, Any] = {}
    history = context.sets
    for position, exercise_id in enumerate(sorted(exercises_mod.taxonomy().entities)):
        props = context.entity(exercise_id)
        bodyweight = bool(props.get("bodyweight_type", False))
        power = str(props.get("pattern")) == "power_jump"
        increment = resolved.increment_for(exercise_id)
        source = "power" if power else _load_source(props, essential=True)

        equivalents = exercises_mod.history_equivalents(exercise_id)
        has_history = (
            not history.empty
            and bool(history["exercise_id"].isin(equivalents).any())
        )
        if not has_history and not bodyweight and not power:
            # No stored set can produce a base or a held load. The phone reads the null and asks
            # the athlete for the weight instead of being given an invented one.
            exercises[exercise_id] = {
                "load_source": source,
                "base_load_kg": None,
                "accessory_load_kg": None,
                "increment_kg": float(increment),
                "bodyweight": False,
                "power": False,
            }
            continue

        essential_item, _ = engine.build_item(
            conn, context, _slot(exercise_id, essential=True, props=props),
            position, resolved, for_date, {}, template,
            calibration_factors=calibration_factors, exercise_id=exercise_id,
        )
        entry = _entry(
            essential_item,
            essential=not bodyweight and not power,
            increment_kg=increment,
            bodyweight=bodyweight,
            power=power,
            load_source=source,
        )
        if not bodyweight and not power:
            # The accessory path holds the last working load; reuse the resolver's own helper
            # rather than re-deriving it here (the double-progression decision for a replacement
            # is always hold_load).
            found = engine._last_working_set(context, exercise_id)
            entry["accessory_load_kg"] = (
                loads.round_down(found[0], increment) if found is not None else None
            )
        if context.symptom_flare is True and props.get("direct_erector", False):
            # Ask the session's own dose modifier, with a set count above any cap, so the answer
            # is the cap itself rather than a capped copy of the probe's shape.
            probe, _ = engine.build_item(
                conn, context,
                _slot(exercise_id, essential=False, props=props, sets=_DOSE_PROBE_SETS),
                position, resolved, for_date, {}, template,
                calibration_factors=calibration_factors, exercise_id=exercise_id,
            )
            dosed, _ = engine._apply_back_flare_dose((probe,), context, resolved)
            entry["dose_load_kg"] = dosed[0].load_kg
            entry["dose_sets_cap"] = int(dosed[0].sets)
        exercises[exercise_id] = entry

    return {
        "catalogue_version": CATALOGUE_VERSION,
        "as_of": for_date,
        "exercises": exercises,
    }


def prescription_from_catalogue(
    shipped: Mapping[str, Any] | None,
    *,
    exercise_id: str,
    essential: bool,
    reps_low: int,
    rir: int | None,
    sets: int,
) -> dict[str, Any]:
    """The replacement prescription the phone should have shown, from the shipped catalogue.

    This is the server's verification of a client-applied replacement, and the same function the
    client implements in the deterministic tail. It returns the load, the set count (capped by a
    live erector dose), the source that produced it and a reason when it could not. It never
    consults history: the catalogue is the decision, and a missing base is reported rather than
    re-solved (D9, DEC-RESOLVER-23).
    """
    base = {
        "load_kg": None,
        "sets": int(sets),
        "prefill_source": "none",
        "reason": None,
    }
    if not shipped:
        base["reason"] = "catalogue_unavailable"
        return base
    entry = (shipped.get("exercises") or {}).get(exercise_id)
    if not isinstance(entry, Mapping):
        base["reason"] = "no_catalogue_entry"
        return base
    # A live erector dose overrides every other load, including bodyweight work, and caps sets.
    if entry.get("dose_load_kg") is not None:
        cap = entry.get("dose_sets_cap")
        base.update(
            load_kg=float(entry["dose_load_kg"]),
            sets=min(int(sets), int(cap)) if cap else int(sets),
            prefill_source="flare_dose",
        )
        return base
    if entry.get("bodyweight"):
        base.update(load_kg=0.0, prefill_source="bodyweight")
        return base
    if entry.get("power"):
        base.update(prefill_source="power", reason="power_work")
        return base
    increment = float(entry.get("increment_kg") or 0)
    if increment <= 0:
        base["reason"] = "no_increment"
        return base
    if essential:
        e1rm_base = entry.get("base_load_kg")
        if e1rm_base is None:
            base["reason"] = "no_catalogue_base"
            return base
        divisor = 1 + (float(reps_low) + float(rir or 0)) / 30
        base.update(
            load_kg=loads.round_down(float(e1rm_base) / divisor, increment),
            prefill_source="catalogue_e1rm",
        )
        return base
    held = entry.get("accessory_load_kg")
    if held is None:
        base["reason"] = "no_catalogue_working_load"
        return base
    base.update(
        load_kg=loads.round_down(float(held), increment),
        prefill_source="catalogue_double_progression",
    )
    return base


def prefill_from_catalogue(
    shipped: Mapping[str, Any] | None,
    *,
    exercise_id: str,
    essential: bool,
    reps_low: int,
    rir: int | None,
) -> tuple[float | None, str]:
    """The load only, for callers that do not need the set count (kept for compatibility)."""
    resolved = prescription_from_catalogue(
        shipped,
        exercise_id=exercise_id,
        essential=essential,
        reps_low=reps_low,
        rir=rir,
        sets=1,
    )
    return resolved["load_kg"], resolved["prefill_source"] if resolved["load_kg"] is not None         else str(resolved["reason"] or "none")


def dumps(catalogue: Mapping[str, Any]) -> str:
    """Compact JSON, matching how the plan payload is stored."""
    return json.dumps(catalogue, separators=(",", ":"), default=str)
