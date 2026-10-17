"""Permanent, dependency-light helpers shared by ingestion, features, prescription,
critique, the policy engine and the eval harness.

Rule of this package: if a computation is needed in more than one place, it lives
here and is imported. Nothing in `utils` may import from `ingest`, `features`,
`prescribe`, `critique` or `agents` — the arrow only points down.

Submodules
----------
paths       repo-relative config/data locations (no more hard-coded strings)
io_utils    raw CSV reading that preserves sentinels
dates       strict date parsing with the known null tokens
numeric     numeric coercion with an explicit missing-value policy
stats       robust statistics (median/MAD) for noisy training data
exercises   exercise taxonomy resolution: raw log string -> canonical id
reporting   small table printers used by CLI and the profile tool
"""

from strength_coach.utils import (
    dates,
    exercises,
    io_utils,
    numeric,
    paths,
    reporting,
    stats,
)

__all__ = [
    "dates",
    "exercises",
    "io_utils",
    "numeric",
    "paths",
    "reporting",
    "stats",
]
