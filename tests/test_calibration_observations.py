"""Read-only calibration observation tests."""

from __future__ import annotations

from conftest import make_readiness, make_training

from strength_coach.features import calibration_observations, high_intensity_exposure
from strength_coach.store import db, importer, repositories


def _store():
    rows = []
    for day, load in (("2024-01-01", "100"), ("2024-01-08", "105"),
                      ("2024-01-15", "110")):
        rows.append({"Date": day, "Exercise": "Safety Squat Bar",
                     "Weight_Used": load, "RIR": "2", "Reps_Done": "5"})
    training = make_training(rows)
    readiness = make_readiness([{"Date": day} for day in ("2024-01-01", "2024-01-08",
                                                           "2024-01-15")])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store


def test_measured_test_links_prior_raw_and_existing_factor_is_read_only():
    with _store() as store:
        conn = store.connection
        override_id = repositories.append_e1rm_override(
            conn, exercise_id="ssb_squat", e1rm_kg=150.0,
            effective_from="2024-02-01", source="measured",
        )
        high_intensity_exposure.register_test(
            conn, override_id=override_id, exercise_id="ssb_squat",
            performed_on="2024-02-01", test_type="3RM",
        )
        values = calibration_observations.observations(conn, to_date="2024-02-01")

    assert len(values) == 1
    value = values[0]
    assert value.observation_id == f"e1rm_override:{override_id}"
    assert value.test_type == "3RM"
    assert value.prior_raw_e1rm_kg is not None
    assert value.prior_raw_method == "epley_plus_rir"
    assert value.prior_raw_method_version == "epley_rir_v1"
    assert value.prior_raw_observed_on == "2024-01-15"
    assert value.protocol == "unknown" and value.equipment == "unknown"
    assert value.eligibility == "eligible"
    assert value.linked_exposure_id
    assert value.existing_calibration_factor == 1.0
    assert value.existing_factor_applied is False
    assert value.calibration_context_as_of == "2024-02-01"
    assert value.historical_calibration_available is False


def test_test_without_prior_raw_estimate_is_explicitly_excluded():
    with _store() as store:
        conn = store.connection
        override_id = repositories.append_e1rm_override(
            conn, exercise_id="ssb_squat", e1rm_kg=150.0,
            effective_from="2023-12-01", source="measured",
        )
        high_intensity_exposure.register_test(
            conn, override_id=override_id, exercise_id="ssb_squat",
            performed_on="2023-12-01", test_type="3RM",
        )
        values = calibration_observations.observations(conn)

    assert values[0].eligibility == "excluded"
    assert "no prior raw" in values[0].exclusion_reason
    assert values[0].existing_calibration_factor == 1.0


def test_ordinary_sets_are_not_treated_as_measured_tests():
    with _store() as store:
        assert calibration_observations.observations(store.connection) == []
