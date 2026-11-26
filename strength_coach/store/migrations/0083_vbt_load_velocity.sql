-- 0083_vbt_load_velocity — an optional fitted load-velocity line per target.
--
-- The robust median band (velocity_median/low/high) stays the fallback and the shape every
-- historical row has. These additive columns describe a fit of mean velocity on load and RIR;
-- a NULL fit_method means the row predates the line and is read as the median target only.

ALTER TABLE vbt_calibration ADD COLUMN velocity_slope REAL;
ALTER TABLE vbt_calibration ADD COLUMN velocity_intercept REAL;
ALTER TABLE vbt_calibration ADD COLUMN velocity_rir_coef REAL;
ALTER TABLE vbt_calibration ADD COLUMN velocity_residual_mad REAL;
ALTER TABLE vbt_calibration ADD COLUMN load_min REAL;
ALTER TABLE vbt_calibration ADD COLUMN load_max REAL;
ALTER TABLE vbt_calibration ADD COLUMN fit_method TEXT;
