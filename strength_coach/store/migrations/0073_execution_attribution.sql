-- 0073_execution_attribution — performed-set attribution and idempotent execution changes.
--
-- substitutes_plan_item_index annotates a performed set that replaced a frozen plan item
-- (DEC-RESOLVER-18/19). It is copied to clean_set during materialisation and is nullable, so
-- no existing row is rewritten and no backfill is needed.
--
-- Execution substitutions and additions are append-only workout_event rows. They carry a
-- client-generated client_event_id in payload_json; the unique index makes that identity the
-- idempotency key, so a delayed replay cannot append the same change twice.

BEGIN IMMEDIATE;

ALTER TABLE workout_set ADD COLUMN substitutes_plan_item_index INTEGER;
ALTER TABLE clean_set ADD COLUMN substitutes_plan_item_index INTEGER;

CREATE UNIQUE INDEX idx_workout_event_client_change
    ON workout_event(workout_id, json_extract(payload_json, '$.client_event_id'));

COMMIT;
