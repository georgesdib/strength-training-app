-- Power work is quality-limited, not RIR-limited (DEC-POWER-02).
--
-- `effort_model` distinguishes a normal RIR target from a quality stop rule; `quality_stop`
-- stores the operative instruction on the item so a stored prescription remains self-contained.
-- Existing rows keep the historical meaning ('rir'), including old box-jump rows that recorded
-- RIR 4; those snapshots are not rewritten.
ALTER TABLE prescription_item ADD COLUMN effort_model TEXT NOT NULL DEFAULT 'rir';
ALTER TABLE prescription_item ADD COLUMN quality_stop TEXT;
