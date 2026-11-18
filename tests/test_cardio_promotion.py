"""Export promotion: counts, idempotency, and the retention rule that drops background samples."""

from __future__ import annotations

import textwrap

import pytest

from strength_coach.store import cardio, db
from tools.cardio_import import promote

EXPORT = textwrap.dedent(
    """    <?xml version="1.0" encoding="UTF-8"?>
    <HealthData locale="en_GB">
      <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Watch"
              unit="count/min" startDate="2026-11-10 08:10:00 +0000"
              endDate="2026-11-10 08:10:00 +0000" value="142"/>
      <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Watch"
              unit="count/min" startDate="2026-11-10 08:45:00 +0000"
              endDate="2026-11-10 08:45:00 +0000" value="121"/>
      <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Watch"
              unit="count/min" startDate="2026-11-10 14:00:00 +0000"
              endDate="2026-11-10 14:00:00 +0000" value="68"/>
      <Record type="HKQuantityTypeIdentifierVO2Max" sourceName="Watch"
              unit="ml/min·kg" startDate="2026-11-11 09:00:00 +0000"
              endDate="2026-11-11 09:00:00 +0000" value="51.3"/>
      <Workout workoutActivityType="HKWorkoutActivityTypeRunning"
               duration="40.5" durationUnit="min" sourceName="Watch"
               startDate="2026-11-10 08:00:00 +0000" endDate="2026-11-10 08:40:00 +0000">
        <MetadataEntry key="HKAverageMETs" value="9.8 kcal/hr·kg"/>
        <MetadataEntry key="HKTimeZone" value="Europe/London"/>
        <WorkoutStatistics type="HKQuantityTypeIdentifierHeartRate" average="151"
                           maximum="178" unit="count/min"/>
        <WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned" sum="420"
                           unit="kcal"/>
        <WorkoutStatistics type="HKQuantityTypeIdentifierDistanceWalkingRunning" sum="7.1"
                           unit="km"/>
      </Workout>
      <Workout workoutActivityType="HKWorkoutActivityTypeTraditionalStrengthTraining"
               duration="55" durationUnit="min" sourceName="Watch"
               startDate="2026-11-11 18:00:00 +0000" endDate="2026-11-11 18:55:00 +0000"/>
    </HealthData>
    """
)


@pytest.fixture()
def conn(tmp_path):
    connection = db.connect(tmp_path / "coach.db")
    db.migrate(connection)
    yield connection
    connection.close()


def _promote(conn, tmp_path):
    path = tmp_path / "export.xml"
    path.write_text(EXPORT)
    return promote(export_path=path, conn=conn)


def test_promotion_counts_and_retention(conn, tmp_path):
    report = _promote(conn, tmp_path)
    assert report["workouts"] == 2
    assert report["workouts_created"] == 2
    # Two heart rates inside the run, one inside the 10-minute tail; the 14:00 sample is dropped.
    assert report["samples_workout"] == 1
    assert report["samples_tail"] == 1
    assert report["vo2max_seen"] == 1
    assert report["vo2max_created"] == 1
    assert report["history_cutoff"] == "2026-11-11T09:00:00+00:00"
    assert conn.execute("SELECT COUNT(*) FROM health_sample").fetchone()[0] == 2
    running = conn.execute(
        "SELECT * FROM external_workout WHERE activity_type LIKE '%Running%'"
    ).fetchone()
    assert running["duration_s"] == 2430
    assert running["avg_mets"] == pytest.approx(9.8)
    assert running["avg_heart_rate"] == 151
    assert running["max_heart_rate"] == 178
    assert running["active_energy_kj"] == pytest.approx(420 * 4.184)
    assert running["distance_m"] == pytest.approx(7100.0)
    assert running["timezone"] == "Europe/London"
    assert cardio.get_sync_state(conn, "history_cutoff") == "2026-11-11T09:00:00+00:00"


def test_second_run_is_a_noop(conn, tmp_path):
    _promote(conn, tmp_path)
    before = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("external_workout", "health_sample", "measurement")
    }
    again = _promote(conn, tmp_path)
    assert again["workouts_created"] == 0
    assert again["samples_created"] == 0
    assert again["vo2max_created"] == 0
    after = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in before
    }
    assert before == after


def test_sample_key_distinguishes_same_second_values():
    base = dict(
        kind="heart_rate", sampled_at="2026-11-10T08:10:00+00:00", unit="count/min",
        source_bundle_id="Watch",
    )
    assert cardio.sample_content_key(value=142.0, **base) == cardio.sample_content_key(
        value=142.0, **base
    )
    assert cardio.sample_content_key(value=142.0, **base) != cardio.sample_content_key(
        value=143.0, **base
    )


def test_background_samples_are_not_stored(conn, tmp_path):
    _promote(conn, tmp_path)
    stored = conn.execute(
        "SELECT sampled_at FROM health_sample ORDER BY sampled_at"
    ).fetchall()
    assert [row["sampled_at"] for row in stored] == [
        "2026-11-10T08:10:00+00:00",
        "2026-11-10T08:45:00+00:00",
    ]
