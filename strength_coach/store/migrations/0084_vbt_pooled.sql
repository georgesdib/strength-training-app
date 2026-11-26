-- 0084_vbt_pooled -- the pooled rep-count fallback target.
--
-- A per-rep-count line is preferred. When a lift has no line at a prescribed rep count, a
-- pooled fit of mean velocity on load, reps and RIR can issue a labelled fallback. These
-- columns carry the rep term and the observed rep range so the target says whether the
-- prediction is an extrapolation. Additive: pre-0084 rows are line/median only.

ALTER TABLE vbt_calibration ADD COLUMN velocity_rep_coef REAL;
ALTER TABLE vbt_calibration ADD COLUMN reps_min INTEGER;
ALTER TABLE vbt_calibration ADD COLUMN reps_max INTEGER;
