"""DoD 10: prescription and load logic never reads the health corpus.

A static import scan rather than a behavioural test: the guarantee is about which modules may
reference the tables, and it should fail the moment somebody joins cardio data into a prescription.
"""

from __future__ import annotations

import pathlib
import re

PRESCRIPTION_MODULES = (
    "strength_coach/prescribe",
    "strength_coach/rules",
    "strength_coach/domain",
)

FORBIDDEN = re.compile(r"\b(external_workout|health_sample|cardio_classification|cardio_exclusion)\b")


def test_prescription_code_does_not_reference_the_health_corpus():
    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for module in PRESCRIPTION_MODULES:
        for path in (root / module).rglob("*.py"):
            if FORBIDDEN.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(root)))
    assert offenders == []
