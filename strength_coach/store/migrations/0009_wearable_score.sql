-- Optional device-computed readiness score (0-100), e.g. Bevel.
-- It is a context input, not a measurement of a physiological quantity; blank means absent.
ALTER TABLE readiness_day ADD COLUMN wearable_score REAL;
