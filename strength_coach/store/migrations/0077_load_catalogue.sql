-- 0077_load_catalogue — the issued plan carries the offline substitution loads.
--
-- The phone substitutes an exercise with no connection, and the replacement load is a training
-- decision. The catalogue is the resolver's own output for every taxonomy exercise, shipped with
-- the plan so the phone applies the decision instead of making one. Additive only: legacy rows
-- stay NULL and a client that never reads the column behaves exactly as before.

BEGIN IMMEDIATE;

ALTER TABLE ios_issued_plan ADD COLUMN load_catalogue_json TEXT;

COMMIT;
