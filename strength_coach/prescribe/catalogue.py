"""The load catalogue shipped with an issued plan (WP0 D9).

The phone must be able to substitute an exercise with no connection, and the replacement load is
a training decision. So the server ships the *decision* — one entry per taxonomy exercise, built
by the resolver itself through \`engine.build_item\` — and the phone applies only the deterministic
tail: \`round_down(base / (1 + (reps + rir) / 30), increment)\`.

There is no second implementation of the load rules here. Each entry is the resolver's own output
for that exercise, which is why the parity test can be exact rather than approximate.

Entry shape (\`load-catalogue/v1\`):

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


def _load_source(props: Mapping[str, Any], *, essential: bool) -> str:
    """The source the replacement path would use for this exercise (DEC-RESOLVER-28)."""
    if props.get("bodyweight_type"):
        return "bodyweight"
    return "e1rm" if essential else "double_progression"


def _slot(exercise_id: str, *, essential: bool, props: Mapping[str, Any]) -> templates.Slot:
    return templates.Slot(
        id=f"catalogue-{'e' if essential else 'a'}-{exercise_id}",
        sets=_SETS,
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

    Cost is two \`build_item\` calls per taxonomy exercise against one shared history context, so
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
        exercises[exercise_id] = entry

    return {
        "catalogue_version": CATALOGUE_VERSION,
        "as_of": for_date,
        "exercises": exercises,
    }


def dumps(catalogue: Mapping[str, Any]) -> str:
    """Compact JSON, matching how the plan payload is stored."""
    return json.dumps(catalogue, separators=(",", ":"), default=str)
