-- 0039_settings_profile — append-only profile versions and prescription snapshots.
--
-- Step 4: a profile version carries sparse overrides over the existing YAML; the effective
-- settings object is profile > config > default. Each prescription stores the resolved map so
-- a later config/profile change cannot rewrite history. A guarded_safety key is not writable
-- here until step 5 adds the warning + double confirmation.

CREATE TABLE settings_profile (
    profile_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    effective_from  TEXT    NOT NULL,
    overrides_json  TEXT    NOT NULL DEFAULT '{}',
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_settings_profile_effective ON settings_profile(effective_from, profile_id);

CREATE TRIGGER settings_profile_no_update BEFORE UPDATE ON settings_profile
BEGIN SELECT RAISE(ABORT, 'append-only: settings_profile rows cannot be updated'); END;
CREATE TRIGGER settings_profile_no_delete BEFORE DELETE ON settings_profile
BEGIN SELECT RAISE(ABORT, 'append-only: settings_profile rows cannot be deleted'); END;

CREATE TABLE prescription_profile (
    prescription_id TEXT PRIMARY KEY REFERENCES prescription(prescription_id),
    profile_id      INTEGER REFERENCES settings_profile(profile_id),
    settings_json   TEXT NOT NULL,
    config_hash     TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TRIGGER prescription_profile_no_update BEFORE UPDATE ON prescription_profile
BEGIN SELECT RAISE(ABORT, 'append-only: prescription_profile rows cannot be updated'); END;
CREATE TRIGGER prescription_profile_no_delete BEFORE DELETE ON prescription_profile
BEGIN SELECT RAISE(ABORT, 'append-only: prescription_profile rows cannot be deleted'); END;
