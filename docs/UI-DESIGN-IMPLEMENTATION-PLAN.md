# Strength Training App UI Design — audit and implementation plan

**Audit basis:** `ui-improvement` at `c6e45ae`; read-only source/API review on 2026-11-05. Follow-on work continues the existing vanilla-JS, local-first UI; it does not replace the app architecture.

## Audit summary

The current product organizes its destinations into six named areas: Today, Training, Progress, Health & Longevity, Programme Intelligence, and Administration. Its dependency-free SVG charts use the shared frame/axis and line/bar renderers in `analytics-charts.js`; existing e1RM, ratio, dose, monitoring, cardio and measurement charts use that layer. Exercise Explorer combines add/view/edit with per-exercise analytics; chart summaries cover the complete selected date range while exact completed-session records paginate in 50-session pages. Existing APIs return more useful dated data than the former Progress summary exposed.

The main opportunities are to make the six areas discoverable in navigation without duplicating existing forms; keep Today focused; make charts look and behave consistently; fix a few misleading coverage displays; and make existing descriptive data easier to scan. Preserve current routes, IDs, loaders, workflows, and append-only semantics.

## Proposed six-area information architecture

| Principal area | Existing destinations to retain | Consolidation intent |
|---|---|---|
| **Today** | Today dashboard | Action hub: readiness/workout action, due reviews, concise recent context and links. No duplicated readiness form. |
| **Training** | Workflow, History, Exercises | Execution, completed records/corrections, and Exercise Explorer remain distinct tasks. |
| **Progress** | Performance, Outcomes | Unified discovery for strength, dose, outcomes and consistency; retain the detail pages and their existing filters. |
| **Health & Longevity** | Longevity, Cardio, Measures, Readiness | Summary plus existing capture/history and readiness configuration routes; daily readiness entry stays in Workflow. |
| **Programme Intelligence** | Prescribe, Programme, Review | Forecast and read-only programme diagnostics remain distinct from completed execution and prescription authority. |
| **Administration** | Athlete, Import, Settings, Logs, Docs | Keep data/configuration tasks; clarify editable state vs reports and document local system limits. |

## Data/API audit and limits

**Available without a new backend contract:** `/api/overview`, `/api/workout/active`, `/api/progress` (fixed-lookback ratio points and coverage), `/api/outcomes`, `/api/volume` (bounded weekly working sets by pattern), `/api/history/days` (bounded stored active dates/workout IDs), `/api/performance/e1rm`, `/api/performance/relationship-options`, `/api/exercise-history` (50-record page limit with full-range analytics and offset pagination), `/api/monitoring-analysis` (descriptive lagged pairs), `/api/workout/{id}` (frozen plan and completed workout), `/api/cardio`, `/api/measurements` (latest 50 exact entries plus full summary), `/api/exposure`, `/api/residual`, `/api/shadow`, `/api/programme`, `/api/state`, and settings/import/logs/docs endpoints. These support Progress and Health & Longevity charts without duplicated domain calculations.

**Not available as truthful time series today:** an actual future-session calendar, complete historical execution comparisons for imported sessions without frozen app-workout plans, a dedicated date-indexed bodyweight series, weighted muscle-group attribution, and a weekly tonnage/intensity/residual series with matching units and coverage. The Progress calendar/frequency counts describe stored active dates, never scheduled adherence; exact exercise-history records page at 50 per request while summaries span the selected range; the cross-lift ratio keeps its fixed 56-day window. Do not convert these limits into zeroes or infer unavailable dimensions.

**Correctness issues to address before adding interpretations:** progress sRPE coverage must be as-of and count the stated field independently of duration; Longevity must count observed measurements rather than configured metric keys; readiness coverage text must reflect the actual intended/returned fields; Outcomes first/last e1RM should agree with canonical eligible best-per-training-day observations. These are reporting corrections, not prescription or storage changes.

## Prioritized milestones and acceptance criteria

### P0 — Information architecture and compatibility — complete (2026-11-05)

- Implement six named navigation groups with existing destination buttons, preserve hash routes and route loaders, expose the active group, and support keyboard focus on collapsed navigation.
- Keep existing view IDs and data-entry destinations. Add no empty placeholder pages just to satisfy a top-level area name.
- Implemented in `index.html`/`app.js`; hash routes and destination IDs remain intact, active areas are exposed accessibly, and existing destination tests pass.

### P1 — Actionable Today and truthful summaries — complete (2026-11-05)

- Use existing active-workout state to offer Continue vs Start; keep readiness unknown/partial explicit and link to Workflow.
- Move detail-heavy Today reports to their owning Progress/Review/Training view, retaining concise status and shortcuts.
- Expose the existing dated progress-ratio points as a descriptive chart and average volume as a snapshot (never attendance as a trend).
- Correct as-of sRPE coverage, observed-measurement count, readiness denominator and Outcomes e1RM day-level series. Surface already-returned outcome fields rather than duplicating feature calculations.
- Today now uses `/api/workout/active`, a compact action hub and a recent-ratio/volume snapshot. Detailed per-rep velocity moved to Performance; form follow-up details are collapsed.
- Reporting fixes: `/api/progress` counts the latest effective sRPE feedback independent of duration, constrained to non-voided sessions on/before the requested date; Longevity counts metrics with observations and shows the actual readiness-field denominator; Outcomes uses canonical eligible best-per-exercise-per-day observations.
- Focused tests cover future feedback/as-of coverage, sRPE with no duration, same-day e1RM deduplication, chart no-data behavior and Longevity coverage labels.

### P2 — Reusable charts and existing-data drill-ins — complete (2026-11-05)

- Added a shared, dependency-free SVG chart layer for date-proportional multi-series lines and grouped bars; it supports reference lines/bands, exact point/category tooltips, consistent axes/units, empty states, responsive SVG, and keyboard/touch series toggles. e1RM, performance ratio, session dose, monitoring, cardio, and measurement charts use the shared renderers; existing chart-expand behavior and semantics remain.
- Exercise Explorer now shows completed working-set count, load medians split by `load_basis`, rep medians split by `reps_unit`, and eligible e1RM observations; same-date fragments combine, null values stay missing, and units are never mixed. Date bounds apply to analytics and exact records; summaries cover the selected range, while duplicate-safe 50-session pages load all exact records without a history cap. “All history” clears both date bounds.
- Progress now combines selectable e1RM raw/trailing-median series and best/latest context, basis-aware logged load/reps, weekly pattern and selected-exercise working-set volume, selected-exercise training dates, an observed-day calendar, non-overlapping weekly training frequency against an optional configured target, the existing fixed-56-day ratio, on-demand lagged dose/e1RM scatters, and one completed app-workout original-plan vs logged-set-row comparison. That comparison is aggregate-only (rows may include different roles, no item matching) and is not an adherence measure. Main-lift change detail and sRPE coverage are retained.
- Clear omissions: no bodyweight-relative trend, weighted muscle volume, weekly tonnage/intensity, or longitudinal VBT residuals because current API contracts do not provide reliable complete series; no imported-session plan comparison; no invented schedule. No new API, database, or dependency was added.
- Cardio charts only ISO weeks containing logged sessions, with WHO reference lines explicitly labelled context and partial-window/missing-log caveats. Measurements chart independent recorded points from the latest 50 API entries, split by method with no line connection, same-day averaging, or interpolation. Regression tests cover aggregation/date filters, exact tooltips, empty/missing values, series toggles, execution caveats, and method/coverage semantics.

### P3 — Optional read-only data contracts

Only if validated product need remains: complete plan/execution item matching, date-indexed bodyweight/readiness or measurement pagination, weighted muscle attribution, or weekly RIR/tonnage/residual history. Specify and test contracts before graphing. No schema migration is assumed by current evidence.

P3 is **not a prerequisite for completing the UI redesign**. If no sufficiently justified product need remains, record P3 as deferred rather than expanding scope.

## Explicitly out of scope

No prescription engine or rule changes; no database-semantic changes, data deletion, or new persistent plan/log tables; no clinical diagnosis, composite health score, causal claim or unsupported threshold; no LLM prescription authority; no fatigue/fitness predictive model, RAG, vector store, autonomous agent framework, backup/export/restore feature, or new authentication boundary.

## Verification

For implementation changes, run focused tests, `python tools/check_ui_docs.py`, `ruff check .`, and the repository default pytest suite before finalizing where practical. Record actual results and distinguish automated tests from any manual verification already performed.

**2026-11-05 prior implementation verification:** 1,518 tests passed; targeted Progress/Outcomes/UI/API tests passed; `python tools/check_ui_docs.py`, `ruff check .`, `git diff --check`, and Node syntax checks passed. No browser/iPhone smoke test was performed.

**2026-11-05 follow-on verification:** 1,521 tests passed; `python tools/check_ui_docs.py`, `ruff check .`, `git diff --check`, and Node syntax checks for `analytics-charts.js`, `progress.js`, `performance.js`, and `app.js` passed. No browser/iPhone smoke test was performed.

**2026-11-05 final verification:** 1,525 tests passed; `python tools/check_ui_docs.py`, `ruff check .`, `git diff --check`, and Node syntax checks for all static JavaScript modules passed. The manual desktop-browser smoke test described in the implementation history passed; no iPhone-sized viewport/device test was performed.

## Final Audit and Closure

**Status:** Pending

**Purpose:** Verify the completed implementation against P0–P2, correct any remaining concrete defects, reconcile documentation, and formally close the UI redesign without introducing unnecessary feature work.

### Audit

- Verify every P0–P2 acceptance criterion against the current implementation.
- Inspect the actual implementation rather than relying solely on commit messages or previous reports.
- Identify discrepancies between this plan, `UI-MAP.md`, `WEB-UI.md`, `ROADMAP.md`, and the current code.
- Confirm that the six-area information architecture and existing workflows remain coherent.
- Confirm that existing charts and drill-ins accurately represent their underlying data and documented limitations.
- Confirm that no UI change has inadvertently altered prescription calculations, database semantics, historical records, or append-only behavior.

### Corrections

- Fix verified functional, data-integrity, presentation, or documentation defects that materially affect the completed redesign.
- Add or update targeted regression tests where appropriate.
- Do not undertake speculative improvements, unrelated refactoring, feature expansion, or new dependencies.
- Do not change prescription engine behavior, training methodology, or database semantics.

### P3 decision

- Reassess whether a validated product need justifies any P3 work.
- If a specific requirement remains, document its scope, rationale, contract, and tests before implementation.
- Otherwise explicitly defer P3 and record the rationale.
- P3 must not prevent closure of the UI redesign.

### Documentation reconciliation

- Update this plan with actual final audit findings and closure status.
- Reconcile `UI-MAP.md`, `WEB-UI.md`, and `ROADMAP.md` with the implemented navigation, features, limitations, and outstanding work.
- Remove obsolete implementation instructions and mark completed work accurately.
- Document any intentional limitations and deferred work.

### Verification

- Run relevant focused tests and regression tests.
- Run the repository default pytest suite where practical.
- Run `python tools/check_ui_docs.py`, `ruff check .`, `git diff --check`, and applicable JavaScript syntax checks.
- Record the commands executed and their actual results.
- Do not require smoke tests, browser tests, or browser walkthroughs.

### Closure criteria

The UI redesign can be marked complete when:

- P0, P1, and P2 acceptance criteria have been verified against the current implementation.
- No known blocking or material UI redesign defects remain unresolved.
- Corrections have appropriate regression coverage.
- P3 is either justified and implemented or explicitly deferred.
- Supporting documentation accurately reflects the implementation.
- Automated verification results and known limitations are documented.
- The final audit report records the closure decision.

### Final audit deliverable

A concise final report containing:

- P0–P2 acceptance criteria verified.
- Defects identified and corrections made.
- Tests and checks executed, with actual results.
- P3 decision and rationale.
- Remaining known limitations.
- Final UI redesign completion status.
- Recommended merge of `ui-improvement` into `development`, if closure criteria are satisfied.

## Implementation updates

- **2026-11-05:** Six-area sidebar, active-group state, Today action summary, combined Progress entry point, per-exercise load/reps graphs, as-of/canonical reporting corrections, UI/docs-map updates, and regression coverage are implemented on `ui-improvement`. See the implementation commit for branch delivery status.
- **2026-11-05 follow-on:** Shared chart primitives and the integrated Progress workspace are implemented without new APIs or metric definitions. The former summary fields and cross-lift ratio remain; bounded chart additions and all explicit omissions are documented above.
- **2026-11-05 final QA:** Exercise Explorer now has independently testable configuration and analytics surfaces, inclusive date filters, complete-range analytics, duplicate-safe paged history, and live empty-state rendering. Health charts use recorded cardio weeks and method-separated measurement observations; no prescription logic, immutable IDs, or append-only storage semantics changed.

## Initial code-map

- Navigation/views: `strength_coach/web/static/index.html`, `app.js`, `docs/UI-MAP.md`.
- Workouts/history/exercises: `workout.js`, `history.js`, `exercises.js`, `summary.js`; APIs in `server.py` and feature modules.
- Chart presentation: `performance.js`, `analytics-charts.js`, `progress.js`, `style.css`; canonical computations remain in Python feature modules.
- Contracts: `tests/test_ui_frontend.py`, `tests/test_web.py`, `tests/test_progress.py`, `tests/test_outcomes.py`, `tests/test_exercise_history.py`, and docs consistency checks.
