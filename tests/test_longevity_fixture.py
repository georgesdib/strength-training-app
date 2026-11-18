"""The canonical longevity assessment against its cross-platform fixture."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from strength_coach.features import cardio_metrics as metrics
from strength_coach.store import cardio, db

FIXTURE = Path(__file__).resolve().parent / "fixtures/intelligence/longevity_assessment.ok.json"
RUN = "HKWorkoutActivityTypeRunning"


def _workout(conn, start, minutes, *, mets=None):
    end = (dt.datetime.fromisoformat(start) + dt.timedelta(minutes=minutes)).isoformat()
    cardio.record_workout(
        conn,
        external_key=cardio.content_key(
            activity_type=RUN, started_at=start, ended_at=end, duration_s=minutes * 60
        ),
        origin="export",
        activity_type=RUN,
        started_at=start,
        ended_at=end,
        duration_s=minutes * 60,
        source_name="Watch",
        avg_mets=mets,
        avg_heart_rate=None,
        imported_at="2026-11-17T18:00:00+00:00",
    )


def test_canonical_assessment_matches_the_cross_platform_fixture(tmp_path):
    conn = db.connect(tmp_path / "coach.db")
    db.migrate(conn)
    try:
        _workout(conn, "2026-11-10T08:00:00+00:00", 60, mets=4.0)
        _workout(conn, "2026-11-12T08:00:00+00:00", 40, mets=9.0)
        _workout(conn, "2026-11-17T08:00:00+00:00", 30, mets=4.0)
        cardio.record_vo2max(
            conn,
            external_id="vo2-2026-11-12",
            measured_at="2026-11-12T08:00:00+00:00",
            value=48.0,
            method="Apple Watch",
            noted_at="2026-11-12T08:00:00+00:00",
        )
        actual = metrics.assessment(conn, as_of="2026-11-18")
    finally:
        conn.close()

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert actual == fixture

    # The fixture is the same contract both clients read: relation, coverage and provenance.
    assert actual["last_week"]["relation"] == "below"
    assert actual["last_week"]["remaining_minutes"] == 10.0
    assert actual["last_week"]["classified_share"] == 1.0
    assert actual["current_week"]["days_remaining"] == 4
    assert actual["vo2max"] == {
        "status": "current",
        "value": 48.0,
        "unit": "ml/kg/min",
        "measured_on": "2026-11-12",
        "source": "device",
        "method": "Apple Watch",
        "age_days": 6,
    }
