-- 0047_symptom_attribution — optional, non-causal link from a symptom to one completed session.
--
-- All fields are nullable so historical rows stay untouched. The signal and every prescription
-- path ignore these columns; they are display and review only (DEC-INJURY-06). Validation of
-- the cross-field rules lives in store/symptom_attribution.py because SQLite cannot express a
-- CHECK that references another column on ALTER TABLE ADD COLUMN.

ALTER TABLE symptom_log ADD COLUMN attributed_session_id TEXT;
ALTER TABLE symptom_log ADD COLUMN attributed_exercise_id TEXT;
ALTER TABLE symptom_log ADD COLUMN onset_on TEXT;
ALTER TABLE symptom_log ADD COLUMN attribution_confidence TEXT
    CHECK (attribution_confidence IN ('possible', 'likely', 'strong'));

CREATE INDEX IF NOT EXISTS idx_symptom_attributed_session
    ON symptom_log(attributed_session_id);
