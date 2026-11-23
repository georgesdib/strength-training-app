-- 0079_drop_execution_target — S5 removed the target-scoped plan.
--
-- 0078 made pairing_device_id authoritative and backfilled every row. The old target columns
-- are now unused; dropping them removes the last compatibility surface rather than leaving a
-- second, misleading plan scope in the schema.

BEGIN IMMEDIATE;

DROP INDEX IF EXISTS idx_ios_issued_plan_pairing;
DROP INDEX IF EXISTS idx_ios_issued_plan_live;

ALTER TABLE ios_issued_plan DROP COLUMN target_device_id;
ALTER TABLE ios_issued_plan DROP COLUMN execution_target;

CREATE UNIQUE INDEX idx_ios_issued_plan_live
    ON ios_issued_plan(pairing_device_id)
    WHERE consumed_at IS NULL AND superseded_at IS NULL;
CREATE INDEX idx_ios_issued_plan_pairing
    ON ios_issued_plan(pairing_device_id);

COMMIT;
