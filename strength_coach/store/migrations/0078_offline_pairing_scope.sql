-- 0078_offline_pairing_scope — an issued plan belongs to the pairing, not a target device.
--
-- S5 removes the execution target and the ownership gate. A plan requested by either device is
-- scoped to the pairing's phone, so the phone and its active watch read the same live plan and
-- either may start it. target_device_id/execution_target stay as legacy, unused columns for
-- rollback; pairing_device_id is the new scope.
--
-- Additive and backfilled. Duplicate live rows for one pairing are superseded (not deleted) before
-- the unique index is replaced, because the old target-scoped index allowed two.

BEGIN IMMEDIATE;

ALTER TABLE ios_issued_plan
    ADD COLUMN pairing_device_id TEXT REFERENCES ios_device(device_id);

UPDATE ios_issued_plan
SET pairing_device_id = COALESCE(
    (SELECT parent_device_id FROM ios_device
     WHERE device_id = ios_issued_plan.device_id),
    device_id
);

-- One live row per pairing. Keep the newest; timestamp the older duplicates as superseded.
UPDATE ios_issued_plan
SET superseded_at = created_at
WHERE consumed_at IS NULL
  AND superseded_at IS NULL
  AND issued_plan_id NOT IN (
      SELECT issued_plan_id FROM (
          SELECT issued_plan_id,
                 ROW_NUMBER() OVER (
                     PARTITION BY pairing_device_id
                     ORDER BY created_at DESC, issued_plan_id DESC
                 ) AS row_number
          FROM ios_issued_plan
          WHERE consumed_at IS NULL AND superseded_at IS NULL
      )
      WHERE row_number = 1
  );

DROP INDEX idx_ios_issued_plan_live;
CREATE UNIQUE INDEX idx_ios_issued_plan_live
    ON ios_issued_plan(pairing_device_id)
    WHERE consumed_at IS NULL AND superseded_at IS NULL;
CREATE INDEX idx_ios_issued_plan_pairing
    ON ios_issued_plan(pairing_device_id);

COMMIT;
