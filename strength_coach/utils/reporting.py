"""Small table printers, shared by the CLI and tools/profile_data.py.

Kept deliberately dumb: formatting only, no computation, so the numbers on screen
are always the numbers the analysis produced.
"""

from __future__ import annotations

import pandas as pd


def count_table(series: pd.Series, *, label: str = "value", top: int | None = None) -> pd.DataFrame:
    """Frequency table of a categorical column, descending by count."""
    counts = series.value_counts(dropna=False)
    if top is not None:
        counts = counts.head(top)
    return counts.rename_axis(label).reset_index(name="count")


def with_percent(frame: pd.DataFrame, count_col: str = "count") -> pd.DataFrame:
    out = frame.copy()
    total = out[count_col].sum()
    out["pct"] = (out[count_col] / total * 100).round(1) if total else 0.0
    return out


def crosstab(left: pd.Series, right: pd.Series, *, left_name: str, right_name: str) -> pd.DataFrame:
    table = pd.crosstab(left, right)
    table.index.name = left_name
    table.columns.name = right_name
    return table


def format_table(frame: pd.DataFrame, *, index: bool = False) -> str:
    return frame.to_string(index=index)


def section(title: str) -> str:
    """A banner line so long profile output stays readable in a terminal."""
    return f"\n{'=' * 3} {title} {'=' * max(3, 70 - len(title))}"
