"""Local reactive deload: region-scoped, dormant by default, never compounding."""

from __future__ import annotations

from contextlib import contextmanager

from conftest import make_readiness, make_training

from strength_coach.features import deload, injury_signal
from strength_coach.prescribe import deload as prescribe_deload
from strength_coach.prescribe.models import PrescriptionItem
from strength_coach.store import db, importer, repositories

SQUAT = {"Exercise": "Safety Squat Bar", "Weight_Used": "100", "RIR": "2", "Reps_Done": "5"}
BENCH = {"Exercise": "Bench Press", "Weight_Used": "80", "RIR": "2", "Reps_Done": "5"}


def rows(*entries):
    return [{**row, "Date": day} for day, row in entries]


@contextmanager
def store_with(training_rows):
    training = make_training(rows(*training_rows))
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        yield store
    finally:
        store.close()


def config_file(tmp_path, regions=("knee",)):
    patterns = {"knee": "[squat, knee_extension]", "shoulder": "[horizontal_push]"}
    labels = {"knee": "Knee", "shoulder": "Shoulder"}
    blocks = [
        f'  {region}:\n'
        f'    label: "{labels[region]}"\n'
        f'    policy: {{signal: false, deload: true}}\n'
        f'    links:\n'
        f'      direct: {{patterns: {patterns[region]}}}\n'
        for region in regions
    ]
    path = tmp_path / "injuries.v1.yaml"
    path.write_text("regions:\n" + "".join(blocks), encoding="utf-8")
    return injury_signal.InjuryConfig.load(path)


def log(conn, day, level, *, region="knee", settled=None):
    repositories.append_symptom(
        conn, logged_on=day, timing="pre_session", region=region,
        level=level, settled_within_48h=settled,
    )


def decision(store, injury_config, as_of="2024-01-12"):
    return deload.local_decision(
        store.connection, as_of,
        config=deload.DeloadConfig(), injury_config=injury_config,
    )


def item(exercise_id, *, sets=4, load=100.0, rir=2, essential=False):
    return PrescriptionItem(
        order_index=0, exercise_id=exercise_id, sets=sets, reps_low=5, reps_high=5,
        load_kg=load, load_basis="e1rm", rounding_increment_kg=2.5, rir_target=rir,
        rest_s=120, essential=essential,
    )


# --- trigger ---------------------------------------------------------------


def test_two_relevant_flaring_exposures_trigger_a_scoped_decision(tmp_path):
    config = config_file(tmp_path)
    with store_with([("2024-01-04", SQUAT), ("2024-01-08", SQUAT)]) as store:
        log(store.connection, "2024-01-04", 2)
        log(store.connection, "2024-01-08", 3)
        found = decision(store, config)

    assert found is not None
    assert found.scope == "local"
    assert found.trigger == "reactive_local"
    assert found.regions == ("knee",)
    assert "ssb_squat" in found.exercise_ids
    assert "2024-01-04 level 2" in found.reason
    assert len(found.evidence[0]["exposures"]) == 2


def test_sessions_without_relevant_exposure_do_not_count(tmp_path):
    config = config_file(tmp_path)
    with store_with([("2024-01-04", BENCH), ("2024-01-08", BENCH)]) as store:
        log(store.connection, "2024-01-04", 3)
        log(store.connection, "2024-01-08", 3)
        assert decision(store, config) is None


def test_an_unrelated_session_neither_counts_nor_resets(tmp_path):
    config = config_file(tmp_path)
    with store_with([
        ("2024-01-04", SQUAT), ("2024-01-06", BENCH), ("2024-01-08", SQUAT),
    ]) as store:
        log(store.connection, "2024-01-04", 2)
        log(store.connection, "2024-01-08", 3)
        found = decision(store, config)

    # The bench day is not a knee exposure, so the two squat days are consecutive as far as
    # this region is concerned.
    assert found is not None
    assert [row["exposure_on"] for row in found.evidence[0]["exposures"]] == [
        "2024-01-08", "2024-01-04",
    ]


def test_a_clear_reading_resets_the_sequence(tmp_path):
    config = config_file(tmp_path)
    with store_with([("2024-01-04", SQUAT), ("2024-01-08", SQUAT)]) as store:
        log(store.connection, "2024-01-04", 2)
        log(store.connection, "2024-01-08", 0)
        assert decision(store, config) is None


def test_a_clear_reading_after_the_last_exposure_ends_it(tmp_path):
    config = config_file(tmp_path)
    with store_with([("2024-01-04", SQUAT), ("2024-01-08", SQUAT)]) as store:
        log(store.connection, "2024-01-04", 2)
        log(store.connection, "2024-01-08", 3)
        assert decision(store, config) is not None
        log(store.connection, "2024-01-10", 0)
        assert decision(store, config) is None


def test_a_missing_observation_is_skipped_not_counted(tmp_path):
    config = config_file(tmp_path)
    with store_with([("2024-01-04", SQUAT), ("2024-01-08", SQUAT)]) as store:
        log(store.connection, "2024-01-08", 3)   # nothing at or before the first exposure
        assert decision(store, config) is None


def test_stale_evidence_keeps_the_deload_and_says_so(tmp_path):
    config = config_file(tmp_path)
    with store_with([("2024-01-04", SQUAT), ("2024-01-08", SQUAT)]) as store:
        log(store.connection, "2024-01-04", 2)
        log(store.connection, "2024-01-08", 3)
        stale = decision(store, config, as_of="2024-01-23")

    assert stale is not None
    assert stale.evidence[0]["stale"] is True
    assert "stale" in stale.reason and "clear" in stale.reason


def test_a_long_layoff_ends_the_sequence(tmp_path):
    config = config_file(tmp_path)
    with store_with([("2024-01-04", SQUAT), ("2024-01-08", SQUAT)]) as store:
        log(store.connection, "2024-01-04", 2)
        log(store.connection, "2024-01-08", 3)
        # 21-day lookback: by February no relevant exposure is in the window at all.
        assert decision(store, config, as_of="2024-02-15") is None


# --- scope -----------------------------------------------------------------


def test_a_local_decision_leaves_unrelated_items_untouched():
    bench = item("bench_press", load=80.0)
    squat = item("ssb_squat", load=100.0)
    decision_ = deload.DeloadDecision(
        "local reactive deload -- Knee", "reactive_local",
        scope="local", regions=("knee",), exercise_ids=("ssb_squat",),
    )
    out, warning, note, _fallback = prescribe_deload.apply_items(
        (bench, squat), decision_, config=deload.DeloadConfig(),
    )

    assert out[0] is bench                      # untouched, not merely equal
    assert out[1].sets == 3
    assert out[1].load_kg == 90.0
    assert out[1].rir_target == 3
    assert "Knee" in warning and "unrelated patterns unchanged" in warning
    assert note["scope"] == "local"
    assert note["regions"] == ["knee"]


def test_two_regions_merge_into_one_modifier_application(tmp_path):
    config = config_file(tmp_path, regions=("knee", "shoulder"))
    with store_with([
        ("2024-01-04", SQUAT), ("2024-01-04", BENCH),
        ("2024-01-08", SQUAT), ("2024-01-08", BENCH),
    ]) as store:
        log(store.connection, "2024-01-04", 2)
        log(store.connection, "2024-01-08", 2)
        log(store.connection, "2024-01-04", 2, region="shoulder")
        log(store.connection, "2024-01-08", 2, region="shoulder")
        found = decision(store, config)

    assert found is not None
    assert set(found.regions) == {"knee", "shoulder"}
    out, _warning, _note, _fallback = prescribe_deload.apply_items(
        (item("ssb_squat"), item("bench_press", load=80.0)), found,
        config=deload.DeloadConfig(),
    )
    # One modifier, applied once: a second regional deload must not cut the same item again.
    assert [row.sets for row in out] == [3, 3]
    # 80 x 0.9 = 72, rounded down to the item's 2.5 kg increment.
    assert [row.load_kg for row in out] == [90.0, 70.0]


def test_a_full_decision_wins_and_the_regional_policy_is_not_evaluated(monkeypatch):
    calls = []

    def local_spy(*args, **kwargs):
        calls.append(True)
        return None

    monkeypatch.setattr(deload, "reactive_reason", lambda *a, **k: "two consecutive weeks over the spinal cap")
    monkeypatch.setattr(deload, "local_decision", local_spy)
    with store_with([("2024-01-04", SQUAT), ("2024-01-08", SQUAT)]) as store:
        found = deload.reactive_decision(store.connection, "2024-01-12")

    assert found is not None
    assert found.trigger == "reactive"
    assert found.scope == "full"
    assert calls == []


# --- dormancy --------------------------------------------------------------


def test_the_shipped_config_never_deloads_locally():
    """Every shipped region has policy.deload false, so the mechanism stays dormant."""
    shipped = injury_signal.InjuryConfig.load()
    assert all(not rule.deload_enabled for rule in shipped.regions.values())
    with store_with([("2024-01-04", SQUAT), ("2024-01-08", SQUAT)]) as store:
        log(store.connection, "2024-01-04", 3)
        log(store.connection, "2024-01-08", 3)
        assert deload.local_deloads(store.connection, "2024-01-12") == []
