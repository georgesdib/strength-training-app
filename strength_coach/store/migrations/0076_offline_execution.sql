-- 0076_offline_execution — an issued plan names the execution it will become.
--
-- The phone starts a workout offline from a downloaded plan, so the execution identity must exist
-- before the start reaches the server: the first starter claims it and every device adopts it.
-- Additive only. Legacy rows stay NULL and the start path mints one on first use, so no existing
-- plan or workout is rewritten.

BEGIN IMMEDIATE;

ALTER TABLE ios_issued_plan ADD COLUMN execution_id TEXT;

-- One plan per execution. A duplicate would let two plans claim the same workout.
CREATE UNIQUE INDEX idx_ios_issued_plan_execution
    ON ios_issued_plan(execution_id)
    WHERE execution_id IS NOT NULL;

COMMIT;
