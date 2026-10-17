"""Strict date parsing with the sentinel tokens this export actually uses.

The log's `Date` column contains exactly two shapes: `YYYY-MM-DD` and the literal
string `(null)`. We parse strictly rather than with inference because
`dateutil`-style guessing silently accepts nonsense (e.g. a row where the month
field shifted) and a shifted date would silently corrupt session reconstruction
and every rolling window downstream.
"""

from __future__ import annotations

import pandas as pd

# Observed plus defensively expected placeholders. Ordered most specific first.
NULL_DATE_TOKENS: frozenset[str] = frozenset(
    {"(null)", "", "0", "null", "NULL", "None", "none", "NaN", "nan", "-"}
)

ISO_DATE_FORMAT = "%Y-%m-%d"


def parse_date(value: str | None) -> pd.Timestamp:
    """Parse one cell. Returns `pd.NaT` for a known null token or unparseable text."""
    if value is None:
        return pd.NaT
    text = str(value).strip()
    if text in NULL_DATE_TOKENS:
        return pd.NaT
    try:
        # Strict: no dayfirst/monthfirst guessing.
        return pd.Timestamp(pd.to_datetime(text, format=ISO_DATE_FORMAT))
    except (ValueError, TypeError):
        return pd.NaT


def parse_dates(series: pd.Series) -> pd.Series:
    """Vectorised strict parse. Result dtype is datetime64[ns], NaT for sentinels."""
    text = series.astype(str).str.strip()
    parsed = pd.to_datetime(
        text.where(~text.isin(NULL_DATE_TOKENS)),
        format=ISO_DATE_FORMAT,
        errors="coerce",
    )
    return parsed


def null_date_rows(series: pd.Series) -> pd.Series:
    """Boolean mask of rows whose date is a sentinel or unparseable."""
    return parse_dates(series).isna()


def add_iso_week(frame: pd.DataFrame, date_column: str) -> pd.DataFrame:
    """Attach ISO year-week, the unit the constitutional weekly rules operate on.

    ISO weeks (Mon-Sun) rather than calendar weeks so "3 sessions per week" means
    the same thing regardless of the year boundary.
    """
    parsed = parse_dates(frame[date_column])
    out = frame.copy()
    out["iso_week"] = parsed.dt.strftime("%G-W%V")
    out["iso_year"] = parsed.dt.isocalendar().year.astype("Int64")
    return out
