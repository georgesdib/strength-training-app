# Monitoring analysis

Read-only exploratory analysis of training dose, lagged associations and calibration
transparency. It is deliberately descriptive. It does not change a prescription, calibration
factor, volume target, or recommendation.

## Entry points

- **Performance -> Monitoring analysis** in the web UI: explicit Run analysis, optional
  as-of date, dose chart, two lagged scatter charts, supporting tables and calibration
  transparency.
- **Settings -> Monitoring & reports**: a collapsed, read-only inventory of effective
  monitoring, calibration, prescription and volume parameters, with search, group filters and
  canonical/local/default/code provenance.
- The standalone CLI is tools/monitoring_analysis.py.
- GET /api/monitoring-analysis?as_of=YYYY-MM-DD.

Both the API and CLI call strength_coach.features.monitoring_analysis.build_analysis. The
HTTP server does not invoke the CLI.

## What it reports

- session-level working sets, hard sets, tonnage and session load where available;
- tonnage is null with an explicit status when no working sets or no tonnage values exist;
  a genuine recorded zero remains 0;
- hard sets and session load versus the next session-best raw e1RM for the same exact exercise;
- sample size and an explicit insufficient or no_variation status when a correlation
  cannot be calculated;
- coverage and missingness counts;
- measured-test calibration observations, prior raw estimates and the factor/CI available as
  of the selected report date, including the calibration context date for every row.

## Configuring relative-strength pairs

The Performance view lists only explicitly configured pairs; it is not an exhaustive lift
catalogue. User changes are written to the git-ignored
`config/strength-relationships.local.yaml` overlay; the canonical YAML remains reviewed and
unchanged. The loader merges local additions, full-object edits and tombstones over the
canonical pairs.

The Performance panel supports add, edit, delete and reset with full server-side validation
against the taxonomy and merged configuration. Edits replace the full local object; membership
is immutable. Every write is atomic and revision-checked, and locally hidden canonical pairs
can be restored from the panel.

A pair is accepted only when:

- numerator and denominator are distinct, known exercises;
- both sides support a formula-derived e1RM;
- the pair is not already configured;
- the relationship type is one of `variant_to_main`, `accessory_to_main`,
  `equipment_variant` or `range_variant`;
- `max_gap_days` is positive;
- `max_age_days` is at least `max_gap_days`;
- `min_observations` is at least 2;
- descriptive-only notes are present.

The config write is atomic. Adding or editing a pair does not change eligibility rules,
calibration, prescriptions or any ratio calculation; it only makes another descriptive pair
visible. Deleting a pair writes a local tombstone when the source is canonical.

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

The analysis endpoint opens a dedicated SQLite connection with mode=ro and query_only=ON.
The response includes the analysis version, seed, selected as_of date and a database
fingerprint. It does not expose a filesystem path. The CLI defaults to
private/docs/MONITORING-ANALYSIS.md; that path is git-ignored and personal output must not be
committed.

## Limitations

- Associations are descriptive, not causal or predictive.
- Small samples and missing feedback often make an association unavailable.
- Calibration factor/CI is current-as-of, not a historical snapshot.
- Protocol/equipment provenance is unavailable.

## Phase 5A and Phase 5B

Phase 5A is the active prospective-validation stage (2026-10-30 to 2027-01-22). It evaluates
the existing system without changing monitoring parameters, calibration, metric definitions or
prescription behaviour. The Today-page follow-up is phase5a_review; completing it requires an
explicit decision.

Phase 5B is gated and not approved or underway. It may begin only after the Phase 5A review and
explicit user approval, and every change must trace to a documented Phase 5A finding.

## Related

- [Training monitoring specification](design/TRAINING-MONITORING-SPEC.md)
- [Web UI](WEB-UI.md)
- [Limitations register](LIMITATIONS-REGISTER.md)
- [Data model](DATA-MODEL.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
