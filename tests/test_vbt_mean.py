"""Effective set velocity: stored mean, set-mean override, or the mean of the per-rep rows."""

import pytest
from conftest import make_readiness, make_training

from strength_coach.store import db, importer, queries


@pytest.fixture
def store():
    store = db.Store(":memory:")
    training = make_training([{
        "Date": "2024-01-01", "Exercise": "Competition Bench Press",
        "Weight_Used": "100", "Reps_Done": "3", "RIR": "2", "Avg_velocity": "0.000000",
    }])
    readiness = make_readiness([{"Date": "2024-01-01"}])
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    try:
        yield store
    finally:
        store.close()


def _set(store):
    return store.connection.execute(
        "SELECT set_id, session_id FROM clean_set"
    ).fetchone()


def test_a_missing_mean_is_derived_from_the_rep_series(store):
    set_id, _ = _set(store)
    for index, velocity in enumerate((0.60, 0.55, 0.50), start=1):
        store.connection.execute(
            "INSERT INTO clean_rep (clean_set_id, rep_index, velocity_mps, source) "
            "VALUES (?, ?, ?, 'device')",
            (int(set_id), index, velocity),
        )
    row = queries.clean_sets(store.connection).iloc[0]
    assert row["velocity_source"] == "rep_mean"
    assert row["velocity_mps"] == pytest.approx(0.55)
    assert bool(row["velocity_present"]) is True


def test_history_revision_changes_when_a_rep_is_inserted(store):
    from strength_coach.features import vbt_profile

    before = vbt_profile._history_revision(store.connection)
    set_id, _ = _set(store)
    store.connection.execute(
        "INSERT INTO clean_rep (clean_set_id, rep_index, velocity_mps, source) "
        "VALUES (?, 1, 0.5, 'device')",
        (int(set_id),),
    )
    assert vbt_profile._history_revision(store.connection) != before


def test_the_profile_is_cached_until_history_changes(store):
    from strength_coach.features import vbt_profile

    first = vbt_profile.build_for(store.connection, "bench_press")
    second = vbt_profile.build_for(store.connection, "bench_press")
    assert first is second
    set_id, _ = _set(store)
    store.connection.execute(
        "INSERT INTO clean_rep (clean_set_id, rep_index, velocity_mps, source) "
        "VALUES (?, 1, 0.5, 'device')",
        (int(set_id),),
    )
    third = vbt_profile.build_for(store.connection, "bench_press")
    assert third is not first


def test_a_set_mean_override_wins_over_the_rep_mean(store):
    set_id, session_id = _set(store)
    for index, velocity in enumerate((0.60, 0.55, 0.50), start=1):
        store.connection.execute(
            "INSERT INTO clean_rep (clean_set_id, rep_index, velocity_mps, source) "
            "VALUES (?, ?, ?, 'device')",
            (int(set_id), index, velocity),
        )
    store.connection.execute(
        "INSERT INTO vbt_override (session_id, set_id, rep_index, velocity_mps, source) "
        "VALUES (?, ?, NULL, 0.70, 'manual')",
        (str(session_id), int(set_id)),
    )
    row = queries.clean_sets(store.connection).iloc[0]
    assert row["velocity_source"] == "override"
    assert row["velocity_mps"] == pytest.approx(0.70)


def test_a_stored_mean_still_wins_over_the_rep_mean():
    seeded = db.Store(":memory:")
    try:
        training = make_training([{
            "Date": "2024-01-01", "Exercise": "Competition Bench Press",
            "Weight_Used": "100", "Reps_Done": "3", "RIR": "2", "Avg_velocity": "0.440000",
        }])
        readiness = make_readiness([{"Date": "2024-01-01"}])
        importer.import_export(
            seeded.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        set_id = seeded.connection.execute("SELECT set_id FROM clean_set").fetchone()[0]
        for index, velocity in enumerate((0.60, 0.55, 0.50), start=1):
            seeded.connection.execute(
                "INSERT INTO clean_rep (clean_set_id, rep_index, velocity_mps, source) "
                "VALUES (?, ?, ?, 'device')",
                (int(set_id), index, velocity),
            )
        row = queries.clean_sets(seeded.connection).iloc[0]
        assert row["velocity_source"] == "stored"
        assert row["velocity_mps"] == pytest.approx(0.44)
    finally:
        seeded.close()
