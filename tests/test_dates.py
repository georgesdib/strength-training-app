"""Date parsing: strict, sentinel-aware, no fuzzy inference."""

import pandas as pd
import pytest

from strength_coach.utils import dates


@pytest.mark.parametrize("token", ["(null)", "", "0", "null", "NULL", "None", "nan", "-"])
def test_known_null_tokens_become_nat(token):
    assert pd.isna(dates.parse_date(token))


def test_valid_iso_date_parses():
    parsed = dates.parse_date("2021-08-08")
    assert parsed.year == 2021
    assert parsed.month == 8
    assert parsed.day == 8


def test_no_fuzzy_inference():
    """A non-ISO string must be rejected, not guessed.

    Rationale: a shifted date silently corrupts session reconstruction and every
    rolling window downstream, so an unparseable date must surface as missing.
    """
    assert pd.isna(dates.parse_date("08/09/2021"))
    assert pd.isna(dates.parse_date("2021-13-45"))
    assert pd.isna(dates.parse_date("yesterday"))


def test_parse_dates_vectorised_marks_sentinels():
    series = pd.Series(["2024-03-04", "(null)", "2025-11-30", ""])
    parsed = dates.parse_dates(series)
    assert parsed.notna().tolist() == [True, False, True, False]


def test_null_date_rows_mask():
    series = pd.Series(["2021-08-08", "(null)"])
    assert dates.null_date_rows(series).tolist() == [False, True]


def test_add_iso_week_uses_iso_calendar():
    """ISO weeks (Mon-Sun) so "3 sessions per week" is stable across year ends."""
    frame = pd.DataFrame({"Date": ["2021-01-04", "2021-01-10"]})  # Mon, Sun same ISO week
    out = dates.add_iso_week(frame, "Date")
    assert out["iso_week"].nunique() == 1
    assert out["iso_week"].iloc[0].startswith("2021-W01")
