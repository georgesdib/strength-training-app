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

**Available before P3:** `/api/overview`, `/api/workout/active`, `/api/progress` (fixed-lookback ratio points and coverage), `/api/outcomes`, `/api/volume` (bounded weekly working sets by pattern), `/api/history/days` (bounded stored active dates/workout IDs), `/api/performance/e1rm`, `/api/performance/relationship-options`, `/api/exercise-history` (50-record page limit with full-range analytics and offset pagination), `/api/monitoring-analysis` (descriptive lagged pairs), `/api/workout/{id}` (frozen plan and completed workout), `/api/cardio`, `/api/measurements` (latest 50 exact entries plus full summary), `/api/exposure`, `/api/residual`, `/api/shadow`, `/api/programme`, `/api/state`, and settings/import/logs/docs endpoints.

**Added by P3:** plan-item identity on set writes and item-level comparisons; paginated exact measurements and an inclusive readiness/bodyweight series; observed weekly RIR/tonnage/residual series; and read-only hard/effective pattern-group volume with direct/indirect/effective counts.

**Still unavailable:** an actual future-session calendar and complete historical execution comparisons for imported sessions without frozen app-workout plans. P3 does not invent either. The Progress calendar/frequency counts describe stored active dates, never scheduled adherence; exact exercise-history records page at 50 per request while summaries span the selected range; the cross-lift ratio keeps its fixed 56-day window. Do not convert these limits into zeroes or infer unavailable dimensions.

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
- P2 clear omissions, now addressed by P3 except where noted: no bodyweight-relative trend, weekly tonnage/intensity, or longitudinal VBT residuals at P2; no imported-session plan comparison; no invented schedule. Pattern-group effective sets (direct 1 + configured indirect 0.25) were available through the volume data when the accounting setting was `effective`, but there was no visible Progress control yet. P3 adds the read-only contracts and the effective-series control. No new API, database, or dependency was added in P2.
- Cardio charts only ISO weeks containing logged sessions, with WHO reference lines explicitly labelled context and partial-window/missing-log caveats. Measurements chart independent recorded points from the latest 50 API entries, split by method with no line connection, same-day averaging, or interpolation. Regression tests cover aggregation/date filters, exact tooltips, empty/missing values, series toggles, execution caveats, and method/coverage semantics.

### P3 — Read-only data contracts and pattern-group effective series (implemented 2026-11-06)

P3 is **in scope for closure**, implemented, and is not deferred. It covers four read-only additions:

1. **Complete plan/execution item matching** — match a frozen app-workout plan item to its logged set rows by stable plan item identity where the snapshot exists. Imported sessions without a frozen plan remain unavailable; do not infer a match from exercise name alone.
2. **Date-indexed bodyweight/readiness and measurement pagination** — add date-range/offset contracts for observed measurement and readiness records, including the bodyweight metric, so complete series and exact-record pages can be requested. Existing single-point and summary behavior remains; missing dates remain missing; no zero-fill.
3. **Weekly RIR/tonnage/residual history** — return weekly series with explicit units, coverage and missing periods. Do not interpolate, merge incompatible units, or turn absent weeks into zeroes.
4. **Pattern-group effective series** — add a read-only `accounting=hard|effective` selection to `/api/volume` (default: the profile setting), and a Progress hard/effective control over the existing pattern-group volume data. `effective_total` uses direct 1.0 plus the configured indirect credit. No new weighting model, no anatomical muscle mapping, and no missing-week fill. The chart must label direct/indirect and coverage.

Acceptance: each contract has an explicit API shape and regression tests; `/api/volume` rejects invalid accounting values and the default preserves the profile setting; the UI distinguishes observed, missing and unavailable states; no prescription, storage, append-only or training-policy semantics change. No schema migration is assumed by current evidence.

**Implementation evidence (2026-11-06):**

- **P3.1** — explicit `plan_item_index`, item-index comparison and ambiguity handling (`bf89890`).
- **P3.2** — exact measurement pagination and inclusive readiness/bodyweight series (`f20459f`, UI in `7e37f8d`).
- **P3.3** — weekly RIR/tonnage/residual history and Progress table (`55c9ecc`).
- **P3.4** — `accounting=hard|effective`, group-level direct/indirect/effective counts and Progress control (`bc89214`).
- No migration was added; existing schema columns and append-only tables were reused.

## Explicitly out of scope

No prescription engine or rule changes; no database-semantic changes, data deletion, or new persistent plan/log tables; no clinical diagnosis, composite health score, causal claim or unsupported threshold; no LLM prescription authority; no fatigue/fitness predictive model, RAG, vector store, autonomous agent framework, backup/export/restore feature, or new authentication boundary.

## Verification

For implementation changes, run focused tests, `python tools/check_ui_docs.py`, `ruff check .`, and the repository default pytest suite before finalizing where practical. Record actual results and distinguish automated tests from any manual verification already performed.

**2026-11-05 prior implementation verification:** 1,518 tests passed; targeted Progress/Outcomes/UI/API tests passed; `python tools/check_ui_docs.py`, `ruff check .`, `git diff --check`, and Node syntax checks passed. No browser/iPhone smoke test was performed.

**2026-11-05 follow-on verification:** 1,521 tests passed; `python tools/check_ui_docs.py`, `ruff check .`, `git diff --check`, and Node syntax checks for `analytics-charts.js`, `progress.js`, `performance.js`, and `app.js` passed. No browser/iPhone smoke test was performed.

**2026-11-05 final verification:** 1,525 tests passed; `python tools/check_ui_docs.py`, `ruff check .`, `git diff --check`, and Node syntax checks for all static JavaScript modules passed. The manual desktop-browser smoke test described in the implementation history passed; no iPhone-sized viewport/device test was performed.

**2026-11-06 P3/final verification:** 1,534 default tests passed; the optional `integration or regression or slow` layer passed with 41 tests; `python tools/check_ui_docs.py`, `ruff check .`, `git diff --check`, and Node syntax checks passed. No browser or iPhone walkthrough was performed.

## Final Audit and Closure

**Status:** Complete 2026-11-06.

**Purpose:** Verify the completed implementation against P0–P3, correct any remaining concrete defects, reconcile documentation, and formally close the UI redesign without introducing unnecessary feature work.

### Audit

- Verify every P0–P3 acceptance criterion against the current implementation.
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

### P3 verification

- Verify every P3 contract against the current implementation: plan/execution matching, measurement/readiness pagination and bodyweight series, weekly RIR/tonnage/residual history, and the pattern-group effective control.
- Confirm missing data remains visible and no anatomical muscle mapping was introduced.
- P3 must be implemented before closure; it is not deferred.

### Documentation reconciliation

- Update this plan with actual final audit findings and closure status.
- Reconcile `UI-MAP.md`, `WEB-UI.md`, and `ROADMAP.md` with the implemented navigation, features, limitations, and outstanding work.
- Remove obsolete implementation instructions and mark completed work accurately.
- Document intentional limitations and any out-of-scope work; P3 is in scope.

### Verification

- Run relevant focused tests and regression tests.
- Run the repository default pytest suite where practical.
- Run `python tools/check_ui_docs.py`, `ruff check .`, `git diff --check`, and applicable JavaScript syntax checks.
- Record the commands executed and their actual results.
- Do not require smoke tests, browser tests, or browser walkthroughs.

### Closure criteria

The UI redesign can be marked complete when:

- P0, P1, P2, and P3 acceptance criteria have been verified against the current implementation.
- No known blocking or material UI redesign defects remain unresolved.
- Corrections have appropriate regression coverage.
- P3 is implemented and verified.
- Supporting documentation accurately reflects the implementation.
- Automated verification results and known limitations are documented.
- The final audit report records the closure decision.

### Final audit deliverable

A concise final report containing:

- P0–P3 acceptance criteria verified.
- Defects identified and corrections made.
- Tests and checks executed, with actual results.
- P3 implementation and verification.
- Remaining known limitations.
- Final UI redesign completion status.
- Recommended merge of `ui-improvement` into `development`, if closure criteria are satisfied.

## Final audit report (2026-11-06)

**Status: CLOSED — UI redesign complete.**

- **P0:** six-area navigation, preserved routes, active-area accessibility and keyboard focus verified against the current source and existing destination tests.
- **P1:** Today continues to use `/api/workout/active`; as-of sRPE coverage, observed-measurement counts, readiness denominators, Outcomes day-level e1RM observations, chart empty states and Longevity coverage labels remain covered by focused tests.
- **P2:** the shared SVG chart layer, complete-range Exercise Explorer analytics, paged exact records, Progress drill-ins and explicit data limitations were rechecked against the source and tests.
- **P3.1:** sets use explicit frozen-plan item identity; duplicate exercises without an index remain ambiguous; original comparisons become unavailable after plan edits.
- **P3.2:** `/api/measurements` paginates exact records with inclusive date bounds; `/api/readiness/history` returns observed bodyweight/readiness points with manual-over-import precedence and no fill.
- **P3.3:** `/api/progress` returns observed weekly RIR/tonnage/residual history and a missing-week list; the Progress table never zero-fills missing weeks.
- **P3.4:** `/api/volume` accepts `accounting=hard|effective`, returns group-level direct/indirect/effective counts, and the Progress control labels the existing indirect-credit model. No anatomical muscle model was added.
- **Corrections:** removed stale muscle-group claims, stale per-rep Prescribe wording, and stale verification notes; added item-identity, pagination, weekly-history and accounting contracts with regression tests.
- **No migration or dependency changes:** no migration file, schema change, new package, prescription-engine change or append-only semantic change was introduced.
- **Verification:** full default suite passed with **1,534 tests**; the optional `integration or regression or slow` layer passed with **41 tests**; `tools/check_ui_docs.py`, `ruff check .`, `git diff --check` and Node syntax checks passed. No browser or iPhone smoke test was performed, as allowed by the plan.
- **Known limitations:** imported sessions without a frozen plan cannot be item-matched; historical rows whose identity cannot be proven remain unavailable; bodyweight history uses observed readiness dates only; weekly residual history only includes app-workout sets with stored targets; pattern-group effective volume is not anatomical muscle volume.
- **Merge recommendation:** merge `ui-improvement` into `development` after final push and delete the feature branch. Do not merge into `main` directly.

## Implementation updates

- **2026-11-05:** Six-area sidebar, active-group state, Today action summary, combined Progress entry point, per-exercise load/reps graphs, as-of/canonical reporting corrections, UI/docs-map updates, and regression coverage are implemented on `ui-improvement`. See the implementation commit for branch delivery status.
- **2026-11-05 follow-on:** Shared chart primitives and the integrated Progress workspace are implemented without new APIs or metric definitions. The former summary fields and cross-lift ratio remain; bounded chart additions and all explicit omissions are documented above.
- **2026-11-05 final QA:** Exercise Explorer now has independently testable configuration and analytics surfaces, inclusive date filters, complete-range analytics, duplicate-safe paged history, and live empty-state rendering. Health charts use recorded cardio weeks and method-separated measurement observations; no prescription logic, immutable IDs, or append-only storage semantics changed.

## Initial code-map

- Navigation/views: `strength_coach/web/static/index.html`, `app.js`, `docs/UI-MAP.md`.
- Workouts/history/exercises: `workout.js`, `history.js`, `exercises.js`, `summary.js`; APIs in `server.py` and feature modules.
- Chart presentation: `performance.js`, `analytics-charts.js`, `progress.js`, `style.css`; canonical computations remain in Python feature modules.
- Contracts: `tests/test_ui_frontend.py`, `tests/test_web.py`, `tests/test_progress.py`, `tests/test_outcomes.py`, `tests/test_exercise_history.py`, and docs consistency checks.
