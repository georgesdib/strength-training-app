"""Symptom thresholds: what counts as a flare.

This lives in `domain` rather than in `rules` because the rule context, the back-signal
feature and the prescription engine all need the same answer, and a feature may not import
`rules` (AGENTS.md §4). One definition, imported everywhere (DEC-SYMPTOM-02).
"""

from __future__ import annotations


def flare_from(level: int | None, settled_within_48h: int | None) -> bool | None:
    """Whether a symptom reading counts as a flare.

    `level` is the agreed 0-3 scale. A level of 2 or more is a flare; a level of 1 is a flare
    unless it is *recorded* as having settled within 48 hours, which is the constitution's
    wording. With no reading at all the answer is None -- unknown, never "no flare"
    (DEC-SYMPTOM-02).

    An unrecorded settle answer counts as not settled (DEC-SYMPTOM-04, closing Q25): "did not
    settle" is an observation, and a missing observation is not evidence that it settled.
    AGENTS invariant 12 says an incomplete input must not pass a safety gate, so the default
    fails safe and a level-1 reading needs an explicit `yes` to be dismissed.
    """
    if level is None:
        return None
    if level >= 2:
        return True
    if level == 1:
        # True == 1 in Python, so a recorded "settled" (1/True) is the only value that clears it.
        return settled_within_48h != 1
    return False
