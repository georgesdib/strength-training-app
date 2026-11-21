-- 0072_exercise_dwell_state — mutable done-exposure counter for the resolver dwell model.
--
-- The resolver keeps one cycle counter per exercise: how many *completed* exposures of that
-- lift (distinct training days with at least one working set) the athlete has logged since the
-- cycle started. The counter drives the dwell factor and the hard cap. See
-- docs/DWELL-AND-ROTATION.md and DEC-RESOLVER-15.
--
-- This table is deliberately mutable, unlike the append-only prescription and workout tables:
-- it is a cycle state, not a record. The audit trail for a change is updated_at; the counter
-- itself can be corrected from the Settings -> Resolver dwell counters, which is the documented
-- escape hatch for a counter that has drifted from what was actually done. The resolver only
-- reads it; completion, the settings reconcile pass and that panel write it.
--
-- Roll back by dropping the table; the resolver treats a missing row as a fresh cycle.

CREATE TABLE exercise_dwell_state (
    exercise_id TEXT PRIMARY KEY,
    done_count  INTEGER NOT NULL DEFAULT 0 CHECK (done_count >= 0),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
