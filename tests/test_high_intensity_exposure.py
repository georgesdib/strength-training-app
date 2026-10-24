"""High-intensity exposures are guarded, but never counted as volume."""

from __future__ import annotations

from strength_coach.features import high_intensity_exposure as exposure
from strength_coach.store import db, repositories


def test_upper_test_blocks_only_for_24_hours():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        exposure_id = repositories.append_high_intensity_exposure(
            conn, performed_on="2026-01-01", kind="test", exercise_id="bench_press",
            region_load="upper", intensity_class="near_max", test_type="1RM",
            source="test_record", source_id="test:1",
        )
        same = exposure.status(conn, "2026-01-01")
        assert same.status == "blocked"
        assert same.next_maximal_on == "2026-01-02"
        next_day = exposure.status(conn, "2026-01-02")
        assert next_day.status == "caution"
        assert next_day.next_maximal_on is None
        assert exposure_id in [row["exposure_id"] for row in same.exposures]
    finally:
        store.close()


def test_active_back_symptom_extends_lower_window_to_72_hours():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        repositories.append_high_intensity_exposure(
            conn, performed_on="2026-01-01", kind="test",
            exercise_id="trap_bar_deadlift", region_load="axial",
            intensity_class="near_max", test_type="1RM",
            source="test_record", source_id="test:2",
        )
        repositories.append_symptom(
            conn, logged_on="2026-01-01", timing="pre_session", region="low_back",
            level=2, settled_within_48h=0,
        )
        status = exposure.status(conn, "2026-01-02")
        assert status.active_back_symptom is True
        assert status.status == "blocked"
        assert status.next_maximal_on == "2026-01-04"
    finally:
        store.close()


def test_test_registration_is_idempotent_and_does_not_touch_volume():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        before = conn.execute("SELECT COUNT(*) AS n FROM clean_set").fetchone()["n"]
        first = exposure.register_test(
            conn, override_id=42, exercise_id="bench_press",
            performed_on="2026-01-01", test_type="3RM",
        )
        second = exposure.register_test(
            conn, override_id=42, exercise_id="bench_press",
            performed_on="2026-01-01", test_type="3RM",
        )
        after = conn.execute("SELECT COUNT(*) AS n FROM clean_set").fetchone()["n"]
        rows = conn.execute("SELECT * FROM high_intensity_exposure").fetchall()
        assert first == second
        assert len(rows) == 1
        assert after == before
        assert rows[0]["source"] == "test_record"
        assert rows[0]["source_id"] == "e1rm_override:42"
    finally:
        store.close()


def test_manual_test_is_rejected():
    store = db.Store(":memory:")
    try:
        try:
            exposure.log_manual(
                store.connection, performed_on="2026-01-01", kind="test",
                region_load="upper",
            )
        except ValueError as exc:
            assert "test path" in str(exc)
        else:
            raise AssertionError("manual test exposure should be rejected")
    finally:
        store.close()


def test_recent_exposure_adds_a_prescription_warning_without_changing_loads():
    from strength_coach.prescribe import build_prescription

    store = db.Store(":memory:")
    try:
        conn = store.connection
        repositories.append_high_intensity_exposure(
            conn, performed_on="2026-01-01", kind="test",
            exercise_id="trap_bar_deadlift", region_load="axial",
            intensity_class="near_max", test_type="1RM",
            source="test_record", source_id="test:3",
        )
        prescription = build_prescription(
            conn, for_date="2026-01-01", session_type="hinge"
        )
        assert any("high-intensity exposure" in warning for warning in prescription.warnings)
        assert prescription.notes["high_intensity_exposure"]["status"] == "blocked"
    finally:
        store.close()
