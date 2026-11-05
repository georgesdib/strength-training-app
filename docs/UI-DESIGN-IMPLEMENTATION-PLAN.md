# Strength Training App UI Design — audit and implementation plan

**Audit basis:** `ui-improvement` at `eb601ab`; read-only source/API review on 2026-11-05. This plan continues the existing vanilla-JS, local-first UI; it does not replace the app architecture.

## Audit summary

The current product already has separate Today, Workflow, History, Exercises, Outcomes, Performance, Longevity, Cardio, Measures, Prescribe, Programme, Review, Readiness and Administration-style views. Its chart layer is dependency-free SVG in `strength_coach/web/static/performance.js`; it already supports axes, legends, enlargement, e1RM/rolling median, dose time-series, and descriptive scatters. The Exercise Explorer now combines add/view/edit, an e1RM trend and working-set counts by training day. APIs return more useful data than some surfaces currently show.

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

**Available without a new backend contract:** `/api/overview` (today/readiness/reviews/recent), `/api/workout/active`, `/api/progress` (ratio points, aggregate attendance, average volume/status), `/api/outcomes` (strength/volume/readiness/cardio/measurement summaries), `/api/performance/*`, `/api/exercise-history`, `/api/cardio`, `/api/measurements`, `/api/exposure`, `/api/residual`, `/api/shadow`, `/api/programme`, completed workout summaries, `/api/state`, and settings/import/logs/docs endpoints. These support navigation, summaries, per-exercise trends, cardio weekly bars, raw measurement plots within the returned window, and snapshot visuals with qualifications.

**Not available as truthful time series today:** an actual future-session calendar, weekly attendance history, a longitudinal actual-vs-plan series, date-indexed readiness history in the Outcomes response, and full measurement history beyond the current endpoint window. Do not derive these from a snapshot or aggregate. Consider a bounded, read-only API only after users explicitly need the trend; it would need as-of, grouping, fragment, missingness and pagination contracts.

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

### P2 — Reusable charts and existing-data drill-ins — partial (2026-11-05)

- Added an observation-based performance-ratio line chart with exact tooltips, real-date spacing, a 1.00 reference and no-imputation disclosure; the working-set chart now uses date-proportional spacing and exact tooltips.
- Exercise Explorer now shows completed working-set count, load medians split by `load_basis`, and rep medians split by `reps_unit`; same-date fragments combine, null values stay missing, and units are never mixed. Existing e1RM/rolling-median graph remains.
- Extend shared axes/style and selectively add cardio weekly minutes/reference context, method-aware measurement-entry trends, or carefully qualified programme snapshot visuals only after confirming date/unit/method contracts. No projection or attendance time series from snapshots.
- Acceptance still open for the remaining P2 plots and a touch/keyboard browser smoke test. Current renderer tests cover empty ratio, one-point and missing/mixed-unit exercise data; browser automation is not installed.

### P3 — Optional read-only data contracts

Only if validated product need remains: bounded weekly attendance, completed-only execution aggregation, date-indexed readiness, or measurement pagination. Specify and test contracts before graphing. No schema migration is assumed by current evidence.

## Explicitly out of scope

No prescription engine or rule changes; no database-semantic changes, data deletion, or new persistent plan/log tables; no clinical diagnosis, composite health score, causal claim or unsupported threshold; no LLM prescription authority; no fatigue/fitness predictive model, RAG, vector store, autonomous agent framework, backup/export/restore feature, or new authentication boundary.

## Verification

For each milestone run focused tests, `python tools/check_ui_docs.py`, `ruff check .`, and the repository default pytest suite before finalizing. Browser automation is not installed in this repo's documented environment; report a manual iPhone/browser smoke test only if one is actually performed.
**2026-11-05 implementation verification:** 1,518 tests passed; targeted Progress/Outcomes/UI/API tests passed; `python tools/check_ui_docs.py`, `ruff check .`, `git diff --check`, and Node syntax checks passed. No browser/iPhone smoke test was performed.

## Implementation updates

- **2026-11-05:** Six-area sidebar, active-group state, Today action summary, combined Progress entry point, per-exercise load/reps graphs, as-of/canonical reporting corrections, UI/docs-map updates, and regression coverage are implemented on `ui-improvement`. See the implementation commit for branch delivery status.

## Initial code-map

- Navigation/views: `strength_coach/web/static/index.html`, `app.js`, `docs/UI-MAP.md`.
- Workouts/history/exercises: `workout.js`, `history.js`, `exercises.js`, `summary.js`; APIs in `server.py` and feature modules.
- Chart presentation: `performance.js`, `style.css`; canonical computations remain in Python feature modules.
- Contracts: `tests/test_ui_frontend.py`, `tests/test_web.py`, `tests/test_progress.py`, `tests/test_outcomes.py`, `tests/test_exercise_history.py`, and docs consistency checks.
