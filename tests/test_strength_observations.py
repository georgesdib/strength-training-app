"""Tests for the raw monitoring observation module."""

from __future__ import annotations

import pandas as pd

from strength_coach.features import strength_observations as obs

PROPS = {"e1rm_applicable": True, "loadable": True, "bodyweight_type": False, "time_based": False}


def base_row(**overrides):
    row = {
        "set_id": 1,
        "session_id": "s1",
        "date": "2026-01-01",
        "exercise_id": "squat",
        "load_kg": 100.0,
        "load_basis": "external",
        "total_load_kg": 100.0,
        "reps": 5,
        "reps_unit": "reps",
        "rir": 2,
        "is_working_set": True,
        "flags": "",
    }
    row.update(overrides)
    return row


def test_raw_set_uses_epley_rir_without_decay_or_calibration():
    result = obs.raw_set_e1rm(base_row(), PROPS)

    assert isinstance(result, obs.RawEstimate)
    assert result.method == "epley_plus_rir"
    assert result.quality == "ok"
    assert result.kg == 100.0 * (1.0 + 7.0 / 30.0)


def test_rir_zero_is_valid_and_flagged_suspect():
    result = obs.raw_set_e1rm(base_row(rir=0, flags="SUSPECT_RIR"), PROPS)

    assert isinstance(result, obs.RawEstimate)
    assert result.rir == 0
    assert result.flags == ("SUSPECT_RIR",)


def test_missing_rir_is_unavailable():
    result = obs.raw_set_e1rm(base_row(rir=None), PROPS)

    assert isinstance(result, obs.Unavailable)
    assert result.status == "invalid"


def test_warmup_rir_six_is_unavailable():
    result = obs.raw_set_e1rm(base_row(rir=6), PROPS)

    assert isinstance(result, obs.Unavailable)
    assert result.status == "invalid"


def test_warmup_flag_is_unavailable():
    result = obs.raw_set_e1rm(base_row(flags="WARMUP"), PROPS)

    assert isinstance(result, obs.Unavailable)
    assert result.status == "invalid"


def test_not_applicable_exercise_is_unavailable():
    result = obs.raw_set_e1rm(base_row(), {"e1rm_applicable": False})

    assert isinstance(result, obs.Unavailable)
    assert result.status == "not_applicable"


def test_reps_plus_rir_cap_is_invalid():
    result = obs.raw_set_e1rm(base_row(reps=20, rir=1), PROPS)

    assert isinstance(result, obs.Unavailable)
    assert "reps + RIR" in result.reason


def test_high_reps_are_degraded_not_invalid():
    result = obs.raw_set_e1rm(base_row(reps=11, rir=2), PROPS)

    assert isinstance(result, obs.RawEstimate)
    assert result.quality == "degraded"


def test_added_load_requires_resolved_total_mass():
    unresolved = obs.raw_set_e1rm(
        base_row(load_basis="added", load_kg=20.0, total_load_kg=20.0), PROPS
    )
    resolved = obs.raw_set_e1rm(
        base_row(load_basis="added", load_kg=20.0, total_load_kg=100.0), PROPS
    )

    assert isinstance(unresolved, obs.Unavailable)
    assert unresolved.status == "unavailable"
    assert isinstance(resolved, obs.RawEstimate)
    assert resolved.total_load_kg == 100.0


def test_bodyweight_total_uses_logged_total():
    result = obs.raw_set_e1rm(
        base_row(load_basis="bodyweight_total", load_kg=80.0, total_load_kg=80.0), PROPS
    )

    assert isinstance(result, obs.RawEstimate)
    assert result.total_load_kg == 80.0



def test_quality_uses_reps_and_rir_thresholds():
    cases = [
        (5, 3, "ok"),
        (5, 4, "degraded"),
        (5, 5, "degraded"),
        (11, 2, "degraded"),
    ]
    for reps, rir, expected in cases:
        result = obs.raw_set_e1rm(base_row(reps=reps, rir=rir), PROPS)
        assert isinstance(result, obs.RawEstimate)
        assert result.quality == expected, (reps, rir, result.quality)


def test_power_classified_exercise_is_explicitly_excluded():
    result = obs.raw_set_e1rm(base_row(exercise_id="jump_squats"), {"pattern": "power_jump"})

    assert isinstance(result, obs.Unavailable)
    assert result.reason == obs.REASON_POWER
    assert result.status == "invalid"


def test_set_linked_to_high_intensity_exposure_is_explicitly_excluded():
    result = obs.raw_set_e1rm(
        base_row(set_id=99),
        PROPS,
        excluded_set_kinds={99: "test"},
    )

    assert isinstance(result, obs.Unavailable)
    assert result.reason == f"{obs.REASON_EXPOSURE_PREFIX}test"
    assert result.status == "invalid"


def test_session_best_honours_excluded_sets():
    frame = pd.DataFrame(
        [
            base_row(set_id=1, load_kg=200.0),
            base_row(set_id=2, load_kg=100.0),
        ]
    )

    best = obs.session_best(frame, "s1", "squat", PROPS, excluded_set_kinds={1: "max_attempt"})

    assert isinstance(best, obs.RawEstimate)
    assert best.set_id == 2


def test_session_best_picks_highest_ok_and_excludes_degraded():
    frame = pd.DataFrame(
        [
            base_row(set_id=1, load_kg=100.0, reps=5, rir=2),
            base_row(set_id=2, load_kg=120.0, reps=5, rir=2),
            base_row(set_id=3, load_kg=200.0, reps=11, rir=2),
        ]
    )

    best = obs.session_best(frame, "s1", "squat", PROPS)

    assert isinstance(best, obs.RawEstimate)
    assert best.set_id == 2


def test_session_best_with_only_degraded_is_unavailable():
    frame = pd.DataFrame([base_row(set_id=1, reps=11, rir=2)])

    best = obs.session_best(frame, "s1", "squat", PROPS)

    assert isinstance(best, obs.Unavailable)
    assert "degraded" in best.reason


def test_session_observations_use_strict_date_and_exact_exercise():
    frame = pd.DataFrame(
        [
            base_row(set_id=1, session_id="s1", date="2026-01-01"),
            base_row(set_id=2, session_id="s2", date="2026-01-02"),
            base_row(set_id=3, session_id="s3", date="2026-01-02", exercise_id="squat_variant"),
            base_row(set_id=4, session_id="s4", date="2026-01-09"),
        ]
    )

    result = obs.session_observations(frame, "squat", "2026-01-09", cutoff_session_id="s4")

    assert [item.session_id for item in result] == ["s1", "s2"]
    assert all(item.exercise_id == "squat" for item in result)


def test_recent_reference_statuses_and_median():
    observations = [
        obs.SessionObservation("squat", f"s{i}", f"2026-01-{i:02d}", _estimate(100 + i))
        for i in range(1, 4)
    ]

    reference = obs.recent_reference(observations, n=3, max_age_days=84, as_of="2026-01-31")

    assert isinstance(reference, obs.Reference)
    assert reference.n == 3
    assert reference.status == "descriptive"
    assert reference.kg == 102.0

    limited = obs.recent_reference(observations[:2], as_of="2026-01-31")
    single = obs.recent_reference(observations[:1], as_of="2026-01-31")
    empty = obs.recent_reference([], as_of="2026-01-31")

    assert isinstance(limited, obs.Reference) and limited.status == "limited"
    assert isinstance(single, obs.Reference) and single.status == "single_prior"
    assert isinstance(empty, obs.Unavailable)


def test_recent_reference_excludes_old_observations():
    observations = [
        obs.SessionObservation("squat", "old", "2025-01-01", _estimate(100)),
        obs.SessionObservation("squat", "new", "2026-01-01", _estimate(110)),
    ]

    reference = obs.recent_reference(observations, as_of="2026-01-31")

    assert isinstance(reference, obs.Reference)
    assert reference.n == 1
    assert reference.kg == 110.0


def test_best_recent_and_personal_best():
    observations = [
        obs.SessionObservation("squat", "old", "2025-01-01", _estimate(200)),
        obs.SessionObservation("squat", "new", "2026-01-01", _estimate(110)),
    ]

    recent = obs.best_recent(observations, as_of="2026-01-31")
    all_time = obs.personal_best(observations)

    assert isinstance(recent, obs.RawEstimate) and recent.kg == 110.0
    assert isinstance(all_time, obs.RawEstimate) and all_time.kg == 200.0


def test_difference_requires_two_prior_observations():
    reference_one = reference([100], as_of="2026-01-31")
    reference_two = reference([100, 102], as_of="2026-01-31")
    post = _estimate(105)

    single = obs.difference_vs_recent(post, reference_one)
    limited = obs.difference_vs_recent(post, reference_two)

    assert single.status == "single_prior"
    assert single.kg is None
    assert limited.status == "limited"
    assert limited.kg == 4.0


def test_difference_rejects_degraded_post():
    post = _estimate(105, quality="degraded")
    recent = reference([100, 102], as_of="2026-01-31")

    result = obs.difference_vs_recent(post, recent)

    assert result.status == "insufficient_quality"
    assert result.kg is None


def _estimate(kg: float, quality: str = "ok") -> obs.RawEstimate:
    return obs.RawEstimate(
        kg=kg,
        method="epley_plus_rir",
        quality=quality,
        session_id="s",
        occurred_on="2026-01-01",
        exercise_id="squat",
        set_id=1,
        load_kg=kg,
        total_load_kg=kg,
        reps=5,
        rir=2,
        flags=(),
    )


def reference(values, as_of):
    observations = [
        obs.SessionObservation("squat", f"s{i}", f"2026-01-{i + 1:02d}", _estimate(value))
        for i, value in enumerate(values)
    ]
    return obs.recent_reference(observations, as_of=as_of)
