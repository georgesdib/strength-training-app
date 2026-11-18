-- 0070_drop_sample_kind_index — the kind index loses every read path it was meant to serve.
--
-- `idx_health_sample_kind (kind, sampled_at)` was added speculatively for "heart rate across a time
-- range". EXPLAIN QUERY PLAN on the real corpus shows it is chosen for the per-workout lookup too,
-- where it searches one kind and then filters ~590k rows by workout id — the worst available plan.
-- The workout index `(external_workout_id, sampled_at)` is the one that path needs.
--
-- Dropping it also returns ~31 MB. The aggregate and series paths fall back to the workout index or
-- a table scan, both of which are acceptable at this size.

BEGIN IMMEDIATE;

DROP INDEX IF EXISTS idx_health_sample_kind;

COMMIT;
