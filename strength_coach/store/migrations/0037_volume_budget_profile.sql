-- 0037_volume_budget_profile — opt-in weekly volume budget and strength-preserving policy.
--
-- The budget changes accessory sets only and is off by default. The policy is athlete state:
-- preserve (default) keeps main lifts at template sets even when the group quota is full;
-- reduce/drop are explicit opt-ins for a volume-first mode (DEC-VOLUME-08).

ALTER TABLE athlete_profile ADD COLUMN volume_budget_enabled INTEGER NOT NULL DEFAULT 0
    CHECK (volume_budget_enabled IN (0, 1));
ALTER TABLE athlete_profile ADD COLUMN main_lift_policy TEXT NOT NULL DEFAULT 'preserve'
    CHECK (main_lift_policy IN ('preserve', 'reduce', 'drop'));
