-- 0027_prescription_e1rm_coverage — make the e1RM source width visible.
--
-- W2 found that a single set can drive the load with only a warning. The source set count is
-- provenance, not a new load input; it is NULL for manual overrides, last-load fallbacks and
-- non-e1RM items.

ALTER TABLE prescription_item ADD COLUMN e1rm_source_sets INTEGER;
