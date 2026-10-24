-- 0025_prescription_modifier — durable provenance for prescription modifiers.
--
-- Prescription items name their modifier refs, but the old/new detail and the reason were not
-- stored in a queryable form. The outcome review needs to know when readiness, continuity,
-- deload, volume or selection changed a prescription. This is provenance only: it does not
-- change any prescription.

CREATE TABLE prescription_modifier (
    modifier_id     TEXT PRIMARY KEY,
    prescription_id TEXT NOT NULL REFERENCES prescription(prescription_id),
    modifier_key    TEXT NOT NULL,
    applied_on      TEXT NOT NULL,
    detail_json     TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_prescription_modifier_prescription
    ON prescription_modifier(prescription_id, modifier_key);
CREATE INDEX idx_prescription_modifier_date
    ON prescription_modifier(applied_on, modifier_key);

CREATE TRIGGER prescription_modifier_no_update BEFORE UPDATE ON prescription_modifier
BEGIN SELECT RAISE(ABORT, 'append-only: prescription_modifier rows cannot be updated'); END;
CREATE TRIGGER prescription_modifier_no_delete BEFORE DELETE ON prescription_modifier
BEGIN SELECT RAISE(ABORT, 'append-only: prescription_modifier rows cannot be deleted'); END;
