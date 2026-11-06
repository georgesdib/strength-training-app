-- Remove readiness_day.composite / composite_basis (task 4 cleanup).
--
-- The pair was created for an imported 0-1 readiness score that the importer deliberately
-- never fills (OPEN-QUESTIONS Q6): no export column maps to it, no rule reads it, and the
-- app computes its own non-authoritative score. The table is derived state, rebuilt from
-- raw_row on every import, so dropping the columns loses no source data.
--
-- SQLite cannot drop a column with a dependent object in older versions; this table has no
-- indexes or triggers, so a full rebuild is the portable form used by 0007/0029.

CREATE TABLE readiness_day_new (
    on_date            TEXT PRIMARY KEY,
    sleep              INTEGER,
    energy             INTEGER,
    mood               INTEGER,
    soreness           INTEGER,
    stress             INTEGER,
    nutrition          INTEGER,
    hydration          INTEGER,
    squat_readiness    INTEGER,
    bench_readiness    INTEGER,
    deadlift_readiness INTEGER,
    hrv_ms             REAL,
    rhr_bpm            REAL,
    bodyweight_kg      REAL,
    fat_pct            REAL,
    merge_note         TEXT,
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    grip_strength_kg   REAL,
    wearable_score     REAL
);

INSERT INTO readiness_day_new (
    on_date, sleep, energy, mood, soreness, stress, nutrition, hydration,
    squat_readiness, bench_readiness, deadlift_readiness, hrv_ms, rhr_bpm,
    bodyweight_kg, fat_pct, merge_note, created_at, grip_strength_kg, wearable_score
)
SELECT on_date, sleep, energy, mood, soreness, stress, nutrition, hydration,
       squat_readiness, bench_readiness, deadlift_readiness, hrv_ms, rhr_bpm,
       bodyweight_kg, fat_pct, merge_note, created_at, grip_strength_kg, wearable_score
  FROM readiness_day;

DROP TABLE readiness_day;
ALTER TABLE readiness_day_new RENAME TO readiness_day;
