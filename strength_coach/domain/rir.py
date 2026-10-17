"""RIR semantics — the single source of truth for what an RIR value means.

Two recorded decisions drive this module:

**DEC-RIR-01 (RIR 6 = warmup).** The user confirmed that `RIR = 6` marks a *warm-up set*.
That is a much stronger statement than "unknown", and it changes what the value is
allowed to influence:

  * a warm-up set is not evidence of effort, so it must not enter RIR compliance scoring;
  * it must not contribute an RIR adjustment to e1RM (a warm-up extrapolated to a max is
    meaningless);
  * it must not count toward working-set volume, spinal dose, or progression decisions;
  * but it MUST still be visible — a large warm-up fraction is itself a coaching signal.

So `RIR 6` is reclassified from "suspect default" to a first-class `warmup` class, not
deleted.

**The remaining ambiguity is RIR 0–1.** Those stay `effort` class and are flagged as
suspect, because the hard "no RIR 0–1 on main lifts" rule needs to see them. They are
reported separately from clean effort rather than discarded.

`RIR 5` is treated as a genuine effort rating (an easy working set), because nothing
indicates otherwise. That is an assumption, and it is the least consequential one here.
"""

from __future__ import annotations

from dataclasses import dataclass

# DEC-RIR-01: this value labels a warm-up, not an effort level.
WARMUP_RIR: int = 6

# Genuine effort observations. RIR 4 does not occur in the reference export at all, but it
# is a legitimate value on the scale and must not be special-cased.
EFFORT_RIR_VALUES: frozenset[int] = frozenset({0, 1, 2, 3, 4, 5})

# Logged effort that should be surfaced as a potential rule violation rather than trusted
# silently. The constitution forbids RIR 0-1 on main lifts.
SUSPECT_EFFORT_RIR: frozenset[int] = frozenset({0, 1})

RIR_CLASSES = ("missing", "warmup", "effort")

# Default effort window: RIR 2-3, applied to every primary compound.
DEFAULT_RIR_TARGET: tuple[int, int] = (2, 3)

# DEC-WINDOW-01: the trap-bar deadlift originally carried its own tighter window (RIR 3-4) as
# extra spinal-fatigue caution. In practice the athlete trains it at ~RIR 2, which made the
# rule fire on 43% of trap-bar sets purely because of the window rather than the effort. The
# window is therefore amended to the default. The override *mechanism* is kept (empty) so a
# per-lift window remains a one-line config change rather than a code change.
PER_EXERCISE_RIR_TARGET: dict[str, tuple[int, int]] = {}


@dataclass(frozen=True)
class RirReading:
    """A classified RIR value. `value` is preserved even when the class is not 'effort'."""

    value: int | None
    klass: str          # "missing" | "warmup" | "effort"
    suspect: bool       # effort but outside the trusted band (RIR 0-1)
    source: str         # "logged" | "logged_warmup" | "missing"


def classify(value: int | float | None) -> RirReading:
    """Classify one RIR cell. Accepts None, floats and strings-with-numbers via float()."""
    if value is None:
        return RirReading(None, "missing", False, "missing")
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return RirReading(None, "missing", False, "missing")
    if numeric != numeric:  # NaN
        return RirReading(None, "missing", False, "missing")

    rounded = int(round(numeric))
    if rounded == WARMUP_RIR:
        # DEC-RIR-01. Warm-up, not effort.
        return RirReading(rounded, "warmup", False, "logged_warmup")
    if rounded in EFFORT_RIR_VALUES:
        return RirReading(
            rounded, "effort", rounded in SUSPECT_EFFORT_RIR, "logged"
        )
    # Off-scale values (negative, 7+) are treated as unusable rather than guessed.
    return RirReading(None, "missing", False, "missing")


def is_warmup(value: int | float | None) -> bool:
    """True only for a confirmed warm-up marker (DEC-RIR-01)."""
    return classify(value).klass == "warmup"


def is_working_set(value: int | float | None) -> bool:
    """A set counts as working unless it is explicitly a warm-up or has no RIR.

    Note the asymmetry: a missing RIR does NOT make a set a warm-up. Assisting accessories
    are often logged without RIR and are still real work, so they remain working sets while
    being excluded from *effort* statistics.
    """
    return not is_warmup(value)


def is_effort(value: int | float | None) -> bool:
    return classify(value).klass == "effort"


def within_window(value: int | float | None, low: int, high: int) -> bool:
    """Whether a set sits inside a target window. Warm-ups and missing values never do."""
    reading = classify(value)
    if reading.klass != "effort":
        return False
    return low <= int(reading.value) <= high


def target_for(exercise_id: str) -> tuple[int, int]:
    """The RIR window for a lift: a per-lift override if configured, else the default (2-3).

    Kept aligned with `config/rules/programme.v1.yaml` -> PRG-RIR-001.params. This function is
    the single code-level source; the rule document declares the same numbers, and a test
    diffs the two so they cannot drift apart.
    """
    return PER_EXERCISE_RIR_TARGET.get(str(exercise_id), DEFAULT_RIR_TARGET)


def warmup_fraction(values) -> float:
    """Share of sets labelled warm-up. A coaching signal, not an error rate."""
    total = 0
    warmups = 0
    for value in values:
        total += 1
        if is_warmup(value):
            warmups += 1
    return warmups / total if total else 0.0
