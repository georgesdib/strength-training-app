# Monitoring analysis

Read-only exploratory analysis of training dose, lagged associations and calibration
transparency. It is deliberately descriptive. It does not change a prescription, calibration
factor, volume target, or recommendation.

## Entry points

- **Performance -> Monitoring analysis** in the web UI.
- The standalone CLI is tools/monitoring_analysis.py.
- GET /api/monitoring-analysis?as_of=YYYY-MM-DD.

Both the API and CLI call strength_coach.features.monitoring_analysis.build_analysis. The
HTTP server does not invoke the CLI.

## What it reports

- session-level working sets, hard sets, tonnage and session load where available;
- hard sets and session load versus the next session-best raw e1RM for the same exact exercise;
- sample size and an explicit insufficient or no_variation status when a correlation
  cannot be calculated;
- coverage and missingness counts;
- measured-test calibration observations, prior raw estimates and the factor/CI available as
  of the selected report date.

## Interpretation

These are exploratory observational associations. They do not establish causation, validate a
predictive model, or identify an optimal training prescription. Training dose and performance
are affected by confounding factors, and historical associations are not validated individual
response estimates.

The analysis does not influence normal application behaviour, prescriptions, calibration or
volume policy.

## Calibration semantics

A measured-test row describes the historical test and its strictly prior raw formula estimate.
The calibration factor and confidence interval shown on that row are the state available as of
the report's selected date, not necessarily the state that existed on the test date. Historical
factor snapshots are not reconstructed; the response says this explicitly.

Protocol and equipment are reported as unknown because the current tables do not store them.

## Reproducibility and privacy

The response includes the analysis version, seed, selected as_of date and a database
fingerprint. It does not expose a filesystem path. The CLI defaults to
private/docs/MONITORING-ANALYSIS.md; that path is git-ignored and personal output must not be
committed.

## Limitations

- Associations are descriptive, not causal or predictive.
- Small samples and missing feedback often make an association unavailable.
- Calibration factor/CI is current-as-of, not a historical snapshot.
- Protocol/equipment provenance is unavailable.

## Related

- [Training monitoring specification](design/TRAINING-MONITORING-SPEC.md)
- [Web UI](WEB-UI.md)
- [Limitations register](LIMITATIONS-REGISTER.md)
- [Data model](DATA-MODEL.md)
