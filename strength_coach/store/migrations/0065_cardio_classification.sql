-- 0065_cardio_classification — cached per-workout classification for the dashboard.
--
-- Why a cache and not a view: classifying a workout falls back to the mean of its heart-rate series
-- when Apple supplied no average, and that scan over ~600k samples takes seconds. The dashboard reads
-- this table instead, so a page load is an index scan rather than a sample scan.
--
-- The rows are disposable: they are rebuilt from external_workout and health_sample at any time, so
-- there are no append-only triggers here. A cache that cannot be rewritten is a second source of
-- truth, which is exactly what this must not become.

BEGIN IMMEDIATE;

CREATE TABLE cardio_classification (
    external_workout_id TEXT PRIMARY KEY REFERENCES external_workout(external_workout_id),
    zone                TEXT CHECK (zone IS NULL OR zone IN ('light', 'moderate', 'vigorous')),
    tier                TEXT CHECK (tier IS NULL OR tier IN ('met', 'hr')),
    is_resistance       INTEGER NOT NULL CHECK (is_resistance IN (0, 1)),
    minutes             REAL NOT NULL CHECK (minutes > 0),
    started_at          TEXT NOT NULL,
    ended_at            TEXT NOT NULL,
    built_at            TEXT NOT NULL
);

CREATE INDEX idx_cardio_classification_started ON cardio_classification(started_at);

CREATE TABLE cardio_cache_state (
    name       TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

COMMIT;
