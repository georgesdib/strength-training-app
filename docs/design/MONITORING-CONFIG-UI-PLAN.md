# Monitoring configuration and report-control UI plan

**Status:** Steps 1–5 implemented and reviewed. Step 4 includes revision hardening and one-click conflict recovery; Step 5 adds the LIM-27 point 3 report/window controls, calibration/coverage previews, top-10 symptom history with Show all, and test-cadence status. Step 6 remains pending.

**Scope:** read-only parameter inventory visible on the home LAN; loopback-only writes; relative-strength pair CRUD; LIM-27 point 3 report/window controls.

**Explicitly deferred:** editable monitoring/exposure parameters and all post-Phase 5A work. Revisit at the Phase 5A review.

## Decisions

1. Option A applies:
   - read-only inventory is visible on the home LAN;
   - all writes remain loopback-only through the existing mutation guard;
   - authentication is out of scope.
2. Monitoring and exposure parameters remain read-only until the Phase 5A review.
3. Calibration, prescription, volume, readiness and e1RM-formula values never become editable.
4. Near-term deliverables:
   - read-only parameter inventory;
   - relative-strength pair CRUD;
   - LIM-27 point 3 report controls.

## Safety boundary

The inventory exposes only:

- parameter names and effective values;
- source: canonical config, local override or code constant;
- editability class;
- documentation links.

It must not expose:

- absolute filesystem paths;
- database contents;
- athlete-specific values;
- personal training records;
- individual calibration observations.

Every write must remain behind the existing loopback Host + same-origin + JSON guard. Tests must prove LAN-origin writes are rejected.

## Workstream A: read-only parameter inventory

### A1. Catalogue

Create one grouped inventory:

| Group | Source | Editability |
|---|---|---|
| Monitoring definitions | config/monitoring.v1.yaml | read-only, Phase 5A locked |
| Exposure and dose | config/exposure.v1.yaml | read-only, Phase 5A locked |
| Relationship configuration | canonical relationship YAML plus local overlay | pair configuration editable |
| Calibration context | calibration config and code constants | read-only |
| Prescription, volume and readiness | existing config | read-only |
| Analysis constants | code constants and version | fixed |

Each entry provides:

- stable key;
- label;
- effective value;
- unit or range where applicable;
- source label;
- editability class;
- reason such as Phase 5A freeze or calibration decision required;
- relative documentation path.

### A2. API

GET /api/settings/monitoring returns:

- revision hash;
- grouped parameters;
- read-only flag;
- current Phase 5A status;
- no-auth/LAN-read caveat.

No write endpoint for monitoring values.

### A3. UI

Add Settings -> Monitoring and reports:

- grouped tables or definition lists;
- search/filter;
- badges: Editable, Read-only, Fixed, Phase 5A locked;
- expandable explanations;
- documentation links;
- no inputs for locked values;
- responsive mobile portrait and landscape.

### A4. Tests

- expected groups and parameters are present;
- no absolute paths or athlete data;
- effective values match service values;
- read-only endpoint works over LAN and loopback;
- no monitoring write route;
- docs links resolve.

## Workstream B: relative-strength pair CRUD

### B1. Storage

Introduce config/strength-relationships.local.yaml, following the exercise-demand overlay pattern:

- canonical YAML remains reviewed and unchanged;
- local additions, edits by id and tombstones are merged by the loader;
- the local file is git-ignored;
- existing canonical pairs remain visible;
- editing or deleting a canonical pair writes only a local override.

### B2. API

- GET /api/performance/relationships
- POST /api/performance/relationships
- PUT /api/performance/relationships/{id}
- DELETE /api/performance/relationships/{id}
- POST /api/performance/relationships/{id}/reset

Numerator and denominator are immutable after creation; change membership by deleting and adding.

### B3. Validation

- known, distinct exercises;
- both e1RM-capable;
- unique pair and id;
- valid relationship type;
- positive gap;
- max age at least gap;
- minimum observations at least 2;
- descriptive notes;
- revision must match the loaded form.

### B4. Writes

- validate merged result;
- atomic temp-file replace;
- backup under data/config-backups/;
- invalidate relationship and ratio caches;
- field-level errors;
- no partial writes.

### B5. UI

Extend Configured relative strength:

- list/filter pairs;
- edit, delete and reset;
- source badge Canonical or Local override;
- revision mismatch: reload and retry;
- clear descriptive-only warning.

### B6. Tests

- add/edit/delete/reset round trips;
- canonical YAML unchanged;
- comments and unrelated pairs preserved;
- invalid values rejected;
- duplicate pair/id rejected;
- cache invalidation;
- LAN write rejected;
- revision conflict rejected;
- no partial state.

## Workstream C: LIM-27 point 3 report controls

All controls are read-only and never write.

### C1. e1RM calibration and coverage windows

- GET /api/e1rm/calibration?window_days=84
- GET /api/e1rm/tests-needed?window_days=84

Add calibration-window and coverage-window inputs to the Athlete calibration and measured-tests panels. Blank means the existing default. Invalid values show an inline error.

Do not confuse this with /api/calibrate, which is rubric calibration.

### C2. Volume

Use existing /api/volume?weeks=&date=:

- weeks input, default 4;
- as-of date input, default today.

### C3. Continuity and fatigue

Use existing date parameters:

- /api/continuity?date=
- /api/fatigue?date=

### C4. Validation

Use existing /api/validation?max_dates=:

- maximum-dates input, default 12;
- documented safe range.

### C5. Symptom history

Add a read-only Raw symptom history disclosure:

- date, region, level, settlement state, source/note where stored;
- no editing;
- existing symptom form remains the only write path.

### C6. Test cadence

Add a read-only Strength-test cadence block:

- next due date;
- last test;
- whether coverage is current;
- link to the existing recording flow.

### C7. Rules

- defaults preserve current behaviour exactly;
- only the affected panel refetches;
- invalid input is visible;
- no database writes;
- mobile layout remains usable.

## Workstream D: documentation

Update:

- docs/WEB-UI.md;
- docs/UI-MAP.md;
- docs/UI-CLI-PARITY.md;
- docs/LIMITATIONS-REGISTER.md;
- ROADMAP.md after completion;
- docs/MONITORING-ANALYSIS.md.

Do not mark Phase 5A complete or pre-approve Phase 5B.

## Delivery sequence

1. Inventory backend.
2. Inventory UI.
3. Relationship overlay and CRUD backend.
4. Relationship CRUD UI.
5. Report controls.
6. Hardening, mobile checks and release.

## Acceptance criteria

- Inventory is read-only and LAN-visible.
- No monitoring, calibration, prescription or optimisation value is editable.
- Relationship writes are loopback-only.
- Canonical relationship YAML is unchanged by UI edits.
- Every LIM-27 point 3 control passes its argument to the existing service.
- Defaults are unchanged when untouched.
- Invalid input is visible, never silently defaulted.
- No new database schema.
- No change to monitoring calculations, calibration state or prescriptions.
- Full public suite, Ruff and front-end syntax checks pass.

## Deferred

- Editable monitoring/exposure parameters.
- Calibration factor/gate editing.
- Prescription threshold, volume and readiness editing.
- Authentication.
- Bulk review and state YAML UI.
- Any Phase 5B work.
