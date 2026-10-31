-- 0046_drop_profile_effective_to — remove the unused profile end date.
--
-- effective_to was never written or read: athlete_profile is append-only and the current
-- state is the latest row by effective_from, so a version ends when the next one starts.
-- Storing an explicit end date duplicated that fact and could disagree with it. History is
-- preserved by the rows themselves; amending state appends a new row.
--
-- SQLite 3.35+ supports DROP COLUMN; this project requires 3.45 via its bundled Python.

ALTER TABLE athlete_profile DROP COLUMN effective_to;
