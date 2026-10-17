"""CSV reading that deliberately does NOT interpret the file.

Two non-obvious choices, both load-bearing for correctness:

1. `dtype=str` — if pandas infers types it will happily turn the string "(null)"
   into NaN in one column and keep "0.000000" as a float 0.0 in another, so the
   sentinel policy becomes implicit and column-order dependent. We keep every
   cell as text and let `numeric`/`dates` apply one documented policy each.

2. `keep_default_na=False` — otherwise the empty strings in `Video` and the
   literal "NULL"-like tokens become NaN, which conflates "blank" with "absent".

The raw layer is immutable: cleaning happens in `ingest.clean`, never here.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from strength_coach.utils import paths


def read_raw_csv(path: str | Path) -> pd.DataFrame:
    """Read a raw source CSV preserving every cell verbatim as a string."""
    frame = pd.read_csv(
        Path(path),
        dtype=str,
        keep_default_na=False,  # "(null)" and "" are meaningful, not NaN
        na_filter=False,
    )
    # Strip a BOM and trailing whitespace that sometimes rides along with exports.
    frame.columns = [str(c).strip().lstrip("\ufeff") for c in frame.columns]
    return frame


def read_training_log(path: str | Path | None = None) -> pd.DataFrame:
    return read_raw_csv(path or paths.training_log_csv())


def read_readiness(path: str | Path | None = None) -> pd.DataFrame:
    return read_raw_csv(path or paths.readiness_csv())


def source_row_ids(frame: pd.DataFrame) -> pd.Series:
    """Stable 1-based row id per source row.

    Used to trace any cleaned record back to the exact CSV line an error came
    from, and as the tiebreaker when two rows are otherwise identical.
    """
    return pd.Series(range(1, len(frame) + 1), index=frame.index, name="source_row")
