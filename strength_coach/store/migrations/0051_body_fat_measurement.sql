-- Move body fat from readiness to the periodic measurement log (DEC-MEASURE-02).
--
-- Fat_Percent was a readiness device field but never entered the readiness score or a load;
-- it is a periodic outcome, so it now lives in measurement. The readiness_day.fat_pct column
-- is kept for provenance (like nutrition/hydration/grip) but is no longer imported or
-- accepted; the importer writes future Fat_Percent values into measurement idempotently.
--
-- The definition must match config/measurements.v1.yaml; a test asserts the match. OR IGNORE
-- keeps the migration safe if a row was somehow declared first.
INSERT OR IGNORE INTO metric_definition (
    metric_key, label, scale_min, scale_max, higher_is_better, aggregation, unit, source,
    active_from
)
VALUES ('body_fat_pct', 'Body fat', 3, 70, 0, 'last', '%', 'config', NULL);

INSERT INTO measurement (measurement_id, metric_key, measured_on, value, method, source, note)
SELECT lower(hex(randomblob(16))), 'body_fat_pct', on_date, fat_pct,
       'imported from readiness Fat_Percent', 'device', NULL
  FROM readiness_day
 WHERE fat_pct IS NOT NULL AND fat_pct > 0;
