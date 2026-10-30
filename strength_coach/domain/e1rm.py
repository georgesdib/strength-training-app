"""Estimated one-rep-max arithmetic.

Two estimates are provided and they answer different questions:

* `epley` — the standard formula, used on sets with no usable RIR.
* `epley_rir_adjusted` — the same formula with RIR folded into the rep count, i.e.
  "reps left in the tank" are treated as reps that were not performed.

The second is an APPROXIMATION, not a validated equation (ASSUMPTION-03). It is
therefore always tagged with its method name so an e1RM series can be recomputed under
a different convention without silently mixing methods.

Why a rep cap: Epley and Brzycki are accurate at low rep counts and degrade as reps rise
(the comparisons in sportRxiv report ~3-4 kg error for Epley/Brzycki at low reps). Beyond
`MAX_RELIABLE_REPS` an estimate is still returned but marked `degraded`, and beyond
`MAX_USABLE_REPS` it is rejected outright — a 30-rep set is not a strength measurement,
and the log contains a 1015-rep typo.
"""

from __future__ import annotations

from dataclasses import dataclass

# Both are ASSUMPTION-03-adjacent config values; they live here as constants with the
# rationale above so a future config layer can lift them without changing call sites.
MAX_RELIABLE_REPS = 10
MAX_USABLE_REPS = 20
EPLEY_DIVISOR = 30.0

# Version tag for stored or exported observations. Changing the formula or its inputs must
# change this string so a series can be recomputed without silently mixing methods.
E1RM_METHOD_VERSION = "epley_rir_v1"


@dataclass(frozen=True)
class E1RMEstimate:
    """An e1RM with its provenance. Never expose the value without the method."""

    value_kg: float
    method: str
    quality: str          # "ok" | "degraded"
    input_reps: int
    input_load_kg: float
    rir_used: int | None

    @property
    def is_usable(self) -> bool:
        return self.quality in {"ok", "degraded"}


def epley(load_kg: float, reps: int) -> float:
    """Epley: load * (1 + reps/30). Assumes the set was taken to failure."""
    return float(load_kg) * (1.0 + float(reps) / EPLEY_DIVISOR)


def epley_rir_adjusted(load_kg: float, reps: int, rir: int) -> float:
    """Epley with the RIR folded in: load * (1 + (reps + RIR)/30).

    Rationale: a set stopped 2 reps short of failure means 2 more reps were available,
    so the set is treated as reps+2 taken to failure. This is the standard practical
    convention and is an approximation — hence the separate method tag.
    """
    return float(load_kg) * (1.0 + (float(reps) + float(rir)) / EPLEY_DIVISOR)


def estimate_e1rm(
    load_kg: float | None,
    reps: int | None,
    rir: int | None = None,
    *,
    use_rir: bool = True,
) -> E1RMEstimate | None:
    """Estimate e1RM, or return None when the inputs cannot support an estimate.

    Returns None (rather than 0 or NaN) for: missing load, missing reps, non-positive
    load, non-positive reps, or reps beyond `MAX_USABLE_REPS`. Callers must handle the
    None case explicitly, which is the point — a silent 0.0 in an e1RM column is far
    more damaging than a visible gap.
    """
    if load_kg is None or reps is None:
        return None
    if load_kg <= 0 or reps <= 0:
        return None
    if reps > MAX_USABLE_REPS:
        return None

    quality = "ok" if reps <= MAX_RELIABLE_REPS else "degraded"

    # RIR is only used when it is a genuine observation in the allowed window. RIR 6 is
    # excluded upstream as a probable default (DQ-SENT-03); a missing RIR falls back to
    # the plain formula rather than an assumed value.
    if use_rir and rir is not None and 0 <= rir <= 5:
        value = epley_rir_adjusted(load_kg, int(reps), int(rir))
        return E1RMEstimate(
            value_kg=value,
            method="epley_plus_rir",
            quality=quality,
            input_reps=int(reps),
            input_load_kg=float(load_kg),
            rir_used=int(rir),
        )

    value = epley(load_kg, int(reps))
    return E1RMEstimate(
        value_kg=value,
        method="epley",
        quality=quality,
        input_reps=int(reps),
        input_load_kg=float(load_kg),
        rir_used=None,
    )


def load_for_reps(e1rm_kg: float, reps: int, rir: int) -> float:
    """Invert the RIR-adjusted Epley: the load that yields `e1rm` at `reps` left `rir`.

    The prescription engine must not invent arithmetic of its own (AGENTS.md §3.2), so the
    inverse lives next to the forward formula it inverts. It is an APPROXIMATION for the same
    reason the forward form is (ASSUMPTION-03): it assumes the RIR adjustment is linear.
    """
    if e1rm_kg <= 0:
        raise ValueError(f"e1RM must be positive, got {e1rm_kg}")
    return float(e1rm_kg) / (1.0 + (float(reps) + float(rir)) / EPLEY_DIVISOR)


def percent_of_e1rm(load_kg: float, e1rm_kg: float) -> float | None:
    """Load as a fraction of e1RM, or None when e1RM is unusable."""
    if not e1rm_kg or e1rm_kg <= 0:
        return None
    return float(load_kg) / float(e1rm_kg)
