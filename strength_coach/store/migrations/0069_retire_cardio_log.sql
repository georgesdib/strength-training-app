-- 0069_retire_cardio_log — one activity history, no manual entry.
--
-- `cardio_log` held a hand-entered cardio session. It never held a row on this instance, and with
-- the imported corpus in place it was a second, weaker history: no heart rate, no identity with
-- HealthKit, and no way for the longevity review to see imported minutes at all.
--
-- The table is dropped rather than kept empty. Its write paths (the web form, `POST /api/cardio`,
-- the `cardio` CLI command and `append_cardio`) are removed in the same change, so nothing can
-- reach it; an empty table that no code can write to is not history, it is a landmark.
--
-- Migration 0011 stays in the ledger: the schema it created existed, and history is not rewritten.
-- What changes is that the corpus is now the only activity record.

BEGIN IMMEDIATE;

DROP TRIGGER cardio_log_no_update;
DROP TRIGGER cardio_log_no_delete;
DROP TABLE cardio_log;

COMMIT;
