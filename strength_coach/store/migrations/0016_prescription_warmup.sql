-- 0016_prescription_warmup — standardised main-lift ramp sets.
--
-- Warm-ups are separate from working sets; this column stores the generated ramp as JSON
-- so a persisted prescription shows the same 50/70/85 loads the athlete saw.
ALTER TABLE prescription_item ADD COLUMN warmup_json TEXT NOT NULL DEFAULT '[]';
