-- 0023_session_type_cleanup — replace the legacy A/B/C day field with the four canonical
-- session types.
--
-- This is a one-way cleanup of derived metadata. Imported sessions are reconstructed from raw
-- rows; the old C label cannot distinguish bench+squat from bench+hinge, so it is resolved from
-- the actual exercise composition and left `unknown` when the evidence does not distinguish it.
-- Prescriptions and workouts are app artifacts; their type is inferred from their items. No
-- training row or original payload is changed.

ALTER TABLE session ADD COLUMN session_type TEXT NOT NULL DEFAULT 'unknown'
    CHECK (session_type IN ('squat', 'hinge', 'bench_squat', 'bench_hinge', 'unknown'));

UPDATE session SET session_type = CASE
    WHEN day_guess = 'A' THEN 'squat'
    WHEN day_guess = 'B' THEN 'hinge'
    WHEN day_guess = 'C' AND EXISTS (
        SELECT 1 FROM clean_set cs
         WHERE cs.session_id = session.session_id
           AND cs.exercise_id = 'single_leg_db_rdl'
    ) AND NOT EXISTS (
        SELECT 1 FROM clean_set cs
         WHERE cs.session_id = session.session_id
           AND cs.exercise_id IN ('ssb_squat', 'competition_squat', 'front_squat',
                                  'high_bar_squat', 'hack_squat', 'belt_squat',
                                  'landmine_squat')
    ) THEN 'bench_hinge'
    WHEN day_guess = 'C' AND EXISTS (
        SELECT 1 FROM clean_set cs
         WHERE cs.session_id = session.session_id
           AND cs.exercise_id IN ('ssb_squat', 'competition_squat', 'front_squat',
                                  'high_bar_squat', 'hack_squat', 'belt_squat',
                                  'landmine_squat')
    ) AND NOT EXISTS (
        SELECT 1 FROM clean_set cs
         WHERE cs.session_id = session.session_id
           AND cs.exercise_id = 'single_leg_db_rdl'
    ) THEN 'bench_squat'
    ELSE 'unknown'
END;

ALTER TABLE session DROP COLUMN day_guess;
ALTER TABLE session DROP COLUMN day_confidence;
ALTER TABLE session DROP COLUMN day_reason;
CREATE INDEX idx_session_type ON session(session_type);

ALTER TABLE prescription ADD COLUMN session_type TEXT NOT NULL DEFAULT 'unknown'
    CHECK (session_type IN ('squat', 'hinge', 'bench_squat', 'bench_hinge', 'unknown'));

DROP TRIGGER prescription_no_update;
UPDATE prescription SET session_type = CASE
    WHEN session_day = 'A' THEN 'squat'
    WHEN session_day = 'B' THEN 'hinge'
    WHEN session_day = 'C' AND EXISTS (
        SELECT 1 FROM prescription_item pi
         WHERE pi.prescription_id = prescription.prescription_id
           AND pi.exercise_id = 'single_leg_db_rdl'
    ) AND NOT EXISTS (
        SELECT 1 FROM prescription_item pi
         WHERE pi.prescription_id = prescription.prescription_id
           AND pi.exercise_id IN ('ssb_squat', 'competition_squat', 'front_squat',
                                  'high_bar_squat', 'hack_squat', 'belt_squat',
                                  'landmine_squat')
    ) THEN 'bench_hinge'
    WHEN session_day = 'C' AND EXISTS (
        SELECT 1 FROM prescription_item pi
         WHERE pi.prescription_id = prescription.prescription_id
           AND pi.exercise_id IN ('ssb_squat', 'competition_squat', 'front_squat',
                                  'high_bar_squat', 'hack_squat', 'belt_squat',
                                  'landmine_squat')
    ) THEN 'bench_squat'
    ELSE 'unknown'
END;
ALTER TABLE prescription DROP COLUMN session_day;
CREATE TRIGGER prescription_no_update BEFORE UPDATE ON prescription
BEGIN SELECT RAISE(ABORT, 'append-only: prescription rows cannot be updated'); END;

UPDATE workout_session SET session_type = COALESCE(session_type, CASE
    WHEN session_day = 'A' THEN 'squat'
    WHEN session_day = 'B' THEN 'hinge'
    ELSE 'unknown'
END);
ALTER TABLE workout_session DROP COLUMN session_day;
