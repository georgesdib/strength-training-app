"""Quick readiness presets and context flags."""

from __future__ import annotations

from strength_coach.features import readiness, readiness_score
from strength_coach.store import db, queries


def test_preset_writes_ordinary_fields_with_source_preset():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        written = readiness.record_preset(conn, "2026-01-01", "good_to_train")
        assert written == 4
        rows = conn.execute(
            "SELECT field, value, source FROM readiness_entry WHERE on_date = '2026-01-01'"
        ).fetchall()
        assert len(rows) == 4
        assert {row["source"] for row in rows} == {"preset"}
        score = readiness_score.compute(conn, "2026-01-01")
        assert score.status == "ready"
        assert score.score is not None
    finally:
        store.close()


def test_context_is_separate_and_does_not_change_score_by_default():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        readiness.record_preset(conn, "2026-01-01", "good_to_train")
        before = readiness_score.compute(conn, "2026-01-01").score
        readiness.record_context(conn, "2026-01-01", ["travel", "alcohol"])
        after = readiness_score.compute(conn, "2026-01-01").score
        assert after == before
        assert set(queries.readiness_context(conn, "2026-01-01")) == {"travel", "alcohol"}
        assert set(readiness_score.compute(conn, "2026-01-01").context_flags) == {
            "travel", "alcohol",
        }
    finally:
        store.close()


def test_device_suppression_is_explicit_config():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        readiness.record_preset(conn, "2026-01-01", "high_stress")
        readiness.record_context(conn, "2026-01-01", ["illness"])
        cfg = readiness.ReadinessConfig.load()
        cfg = readiness.ReadinessConfig(
            **{**cfg.__dict__, "device_suppression_flags": ("illness",)}
        )
        assessment = readiness_score.compute(conn, "2026-01-01", cfg)
        assert assessment.device_suppressed is True
        assert not any(c.field in {"hrv_ms", "rhr_bpm"} for c in assessment.components)
    finally:
        store.close()
