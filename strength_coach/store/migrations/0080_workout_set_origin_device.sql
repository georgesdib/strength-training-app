-- 0080_workout_set_origin_device — retain where the set was captured.
--
-- The committing credential is the phone (D3); this column records the device that actually
-- captured the set, so sensor-derived watch work stays distinguishable from phone entry. It is
-- provenance, never identity: (workout_id, exercise_id, set_index) stays the set key.

BEGIN IMMEDIATE;

ALTER TABLE workout_set
    ADD COLUMN origin_device_id TEXT REFERENCES ios_device(device_id);

CREATE INDEX idx_workout_set_origin
    ON workout_set(origin_device_id)
    WHERE origin_device_id IS NOT NULL;

COMMIT;
