-- 0043_exposure_trim_flag — the opt-in switch for the exposure-ratio accessory trim.
--
-- Off by default (DEC-EXPOSURE-01). The ratio is an ACWR-shaped, contested heuristic, so the
-- athlete turns it on explicitly and can turn it off again; nothing enables it automatically.

ALTER TABLE athlete_profile ADD COLUMN exposure_trim_enabled INTEGER NOT NULL DEFAULT 0
    CHECK (exposure_trim_enabled IN (0, 1));
