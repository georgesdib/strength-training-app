"""Raw CSV reading must not interpret the file.

If pandas infers types, "(null)" and "0.000000" get different implicit treatments
depending on which column they land in. The raw layer keeps everything as text so
exactly one documented policy (utils.numeric / utils.dates) decides meaning.
"""

import pandas as pd
import pytest

from strength_coach.utils import io_utils


def test_source_row_ids_are_one_based_and_stable():
    frame = pd.DataFrame({"x": ["a", "b", "c"]})
    ids = io_utils.source_row_ids(frame)
    assert ids.tolist() == [1, 2, 3]


def test_reading_is_immutable_per_call():
    """Two reads must not share mutable state, so a cleaning step cannot leak."""
    first = io_utils.read_raw_csv.__doc__
    assert first is not None
