-- 0044_drop_unused_profile_fields — retire the profile fields that never drove a decision.
--
-- primary_goal, goal_rank and focus_lifts were stored, validated and rendered, but no rule,
-- feature, prescription or rubric read them (DEC-STATE-02). Keeping them implied the system
-- used a goal or a lift preference to choose work when it does not. The columns held no
-- behavioural data, so dropping them removes a false promise rather than losing an input.
--
-- SQLite 3.35+ supports DROP COLUMN; this project requires 3.45 via its bundled Python.

ALTER TABLE athlete_profile DROP COLUMN focus_lifts;
ALTER TABLE athlete_profile DROP COLUMN goal_rank;
ALTER TABLE athlete_profile DROP COLUMN primary_goal;
