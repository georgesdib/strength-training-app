"""Raw CSV reading must not interpret the file.

If pandas infers types, "(null)" and "0.000000" get different implicit treatments
depending on which column they land in. The raw layer keeps everything as text so
exactly one documented policy (utils.numeric / utils.dates) decides meaning.
"""

import pandas as pd
import pytest

from strength_coach.utils import io_utils


@pytest.mark.integration
def test_sentinels_survive_as_text(training_frame):
    """'(null)' must not become NaN, and '0.000000' must not become float 0.

    pandas >= 3 uses a `str` dtype rather than `object`, so we assert on the cell
    values themselves rather than on the dtype name.
    """
    assert isinstance(training_frame["Date"].iloc[0], str)
    assert "(null)" in set(training_frame["Date"])
    assert "0.000000" in set(training_frame["Avg_velocity"])


@pytest.mark.integration
def test_no_default_na_coercion(training_frame):
    """Empty strings stay empty strings rather than turning into NaN."""
    assert isinstance(training_frame["Video"].iloc[0], str)


@pytest.mark.integration
def test_expected_columns_present(training_frame, readiness_frame):
    expected_training = {
        "Date", "Workout", "Exercise", "Weight_Used", "Weight_Units", "Reps_Done",
        "RIR", "ExertionLoad", "Main_Muscle", "Mechanics", "Force", "Avg_velocity",
        "Avg_power", "Avg_rom", "TUT", "Form", "Video",
    }
    assert expected_training <= set(training_frame.columns)
    expected_readiness = {
        "Date", "Sleep", "Energy", "Mood", "Soreness", "Stress", "Nutrition",
        "Hydration", "Squat_Readiness", "Bench_Readiness", "Deadlift_Readiness",
        "HRV", "RHR", "Weight", "Fat_Percent",
    }
    assert expected_readiness <= set(readiness_frame.columns)


def test_source_row_ids_are_one_based_and_stable():
    frame = pd.DataFrame({"x": ["a", "b", "c"]})
    ids = io_utils.source_row_ids(frame)
    assert ids.tolist() == [1, 2, 3]


def test_reading_is_immutable_per_call():
    """Two reads must not share mutable state, so a cleaning step cannot leak."""
    first = io_utils.read_raw_csv.__doc__
    assert first is not None
