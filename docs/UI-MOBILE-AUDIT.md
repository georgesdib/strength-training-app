# MOBILE UI AND FORM-CONTROL AUDIT

**Status:** accepted and closed 2026-10-28. Implemented at checkpoints 1-4; the owner completed
the native iPhone pass and reviewed the working tree. The training engine, prescription rules,
readiness arithmetic and stored data contracts did not change. Checkpoint 1 covers the P0
contract failures and constrained athlete/exercise fields; checkpoint 2 the
active-workout/readiness and mobile foundations; checkpoint 3 the interaction, navigation and
accessibility work; checkpoint 4 the remaining mobile cards, searchable pickers, advanced
disclosures and field-level errors.
**Scope:** iPhone 16 Pro Max portrait and landscape (440 x 956 and 956 x 440 CSS px), with a
desktop-preserving responsive strategy. The review covers the daily training path in depth and
the admin/state forms for form-control correctness.
**Evidence:** rendered Chromium emulation at the two target viewports with a disposable
database and a synthetic active plan; source inspection; database schema inspection; Node and
pytest checks. Native Safari on a physical iPhone was not used, so keyboard, picker and
safe-area behaviour still need a device pass.

## 1. Verdict

The training core and visual language are sound. The two user-facing gaps are distinct:

1. The active workout is a long desktop pipeline compressed into a phone. Its eight-column
   plan table is roughly 998 CSS px wide inside a 358 px panel in portrait and forces the
   document to about 1039 px. The set logger is buried below readiness results, the plan and
   optional import tools, and every set requires re-entering values and re-selecting the lift.
2. The form layer is not yet a trustworthy constrained-choice interface. Several controls are
   free text although the domain is finite, and some writes are rejected by the database or
   stored without validation.

The workout is the more visible problem; the form contracts are the more serious one. Fix the
contracts first, then make the gym flow phone-first.

## 2. Resolved vocabulary decisions

- The database schema and `DATA-MODEL.md` are canonical for athlete state. `health` in
  `config/athlete-state.example.yaml` is stale and is relabelled `longevity`.
- Constraint kinds are `injury`, `contraindication`, `mobility`, `asymmetry`; severities are
  `hard_exclude`, `caution`, `monitor`.
- Exercise patterns and primary muscles are closed vocabularies derived from the taxonomy.
  VBT family is data-defined: the UI offers existing families and an explicit "new family"
  path. Server validation rejects unknown new writes while preserving existing legacy values.
- Legacy values are shown as "legacy - not in the current list" and are never silently blanked,
  replaced, or coerced.

## 3. P0 findings

| ID | Screen | Finding | Severity | Evidence |
|---|---|---|---|---|
| P0-1 | Exercise Details | `saveExerciseDetails()` reads `props.day_roles.length` after deleting `day_roles`; the submit throws before the API call | Critical | `static/exercises.js` |
| P0-2 | History -> Edit | "Add set" looks for a `tbody` in a card container and is a silent no-op; the fallback helper is undefined | Critical | `static/history.js` |
| P0-3 | Athlete -> Profile | Primary goal is free text against a six-value database CHECK; invalid values become a generic 500 | Critical | `static/app.js`, migration 0003 |
| P0-4 | Athlete -> Constraint | Kind offers `rom`/`preference`, which the database rejects | Critical | `static/index.html`, migration 0003 |
| P0-5 | Athlete -> Constraint | Region, forbidden patterns and forbidden exercises are unvalidated text; a typo makes a hard-exclude rule inert | High | `static/app.js`, `prescribe/constraints.py` |

No schema migration is required for P0. The fixes are constrained controls, canonical option
sources and server-side 400 validation.

## 4. Daily-path findings

| ID | Finding | Severity | Evidence |
|---|---|---|---|
| U-1 | Active plan table breaks page width in portrait and exceeds the panel in landscape | High | rendered emulation; `static/workout.js` |
| U-2 | Readiness results, category tables and prescription remain above the active workout | High | rendered emulation; `static/index.html` |
| U-3 | Set logger clears load/reps/RIR/velocity and resets the exercise select after every add | High | rendered emulation; `static/workout.js` |
| U-4 | Readiness fields are bare 1-5 selects with no scale direction; stress/soreness inversion is invisible | High | `static/app.js` |
| U-5 | Optional CSV/velocity tools and the end-workout form sit below the logger | High/medium | `static/index.html` |
| U-6 | Touch targets measure below 44 px; row actions are smaller still | Medium | rendered emulation; `static/style.css` |
| U-7 | Dialog colours are hard-coded dark; light-theme muted text is 3.44:1 and links 2.28:1 | High | `static/index.html` |
| U-8 | No global landscape/short-height rules and no safe-area handling | High | `static/style.css` |
| U-9 | Prescription review is a nine-column horizontal table | High | `static/app.js`, `static/style.css` |
| U-10 | History list is 720 px wide with actions off-screen; Review is a dense four-column table | Medium | `static/style.css`, `static/app.js` |
| U-11 | No field-level error association, `aria-invalid`, `aria-describedby`, `aria-current` or modal focus management | Medium | static inspection |
| U-12 | Remove set/plan item has no undo; void uses a blocking prompt | Medium | `static/workout.js`, `static/history.js` |

## 5. Restricted-choice inventory

| Screen | Field | Domain / source | Current | Required |
|---|---|---|---|---|
| Exercise editor | `pattern` | taxonomy patterns | select | closed select |
| Exercise editor | `vbt_family` | taxonomy families; extensible | text | existing families + explicit new-family path |
| Exercise editor | `primary_muscles` | taxonomy muscle keys | comma text | multi-select/chips |
| Exercise editor | `log_names` | arbitrary strings | textarea | textarea (correct) |
| Exercise editor | `spinal_cost` | ordinal 1/2/2.5/3 | number | constrained select or validated number |
| Athlete | constraint `kind` | four database values | select with two invalid options | canonical select |
| Athlete | constraint `region` | configured injury regions | text | select |
| Athlete | `forbidden_patterns` | taxonomy patterns | comma text | multi-select |
| Athlete | `forbidden_exercises` | exercise ids | comma text | searchable multi-select |
| Athlete | `since`/`settled_on` | month/date convention | text | month/date input |
| Athlete | suitability/e1RM/test/exposure exercise | exercise ids | constrained select | constrained picker |
| Athlete | symptom region/level/settled | config; 0-3; yes/no/unknown | selects | correct |
| Workflow | readiness fields | 1-5, higher better | bare selects | anchored labels; presets; optional 1-5 row |
| Workout | set exercise | planned lifts | select, resets after add | select, preserved |
| Workout | load/reps/RIR/velocity | numeric | number inputs | numeric; reps required for rep work |
| Workout | form rating | 1-5 or blank | select | select with accessible name |
| Prescribe | session type / target | canonical templates; 30/45/60 | selects | correct |
| Prescribe | throttle scope | patterns or whole session | text + datalist | select |
| History | RIR | numeric; inconsistent upper bound | number | one documented range |
| Review | confidence | high/low/unknown | select | correct |
| Cardio | modality | open vocabulary | text | keep text; optional suggestions |
| Measures | metric | configured metric keys | select from API | correct |
| Settings profile | registry fields | registry `kind`/`choices` | generated | keep; this is the model |

Later change: the three goal controls once listed here (`primary_goal`, `goal_rank`,
`focus_lifts`) were removed on 2026-10-30 because no rule, feature or prescription read them
(`DEC-STATE-02`); the profile form no longer contains them.

## 6. Mobile and interaction plan

- Active workout: one card per planned exercise; logger first; plan options, CSV import and
  velocity behind disclosures; end-session action reachable without a long scroll.
- Set logger: preserve the exercise; prefill from the selected plan item or previous set;
  show the target inline; require a deliberate "Add set".
- Readiness: label the endpoints; bring the existing presets into the Workflow form; pilot a
  compact 1-5 row only if labels and 44 px targets survive.
- Tables: cards on mobile for prescription, active workout, history and review; keep dense
  analytics tables scrollable and keep desktop tables.
- Foundations: 16 px form controls, 44 px primary and frequent row actions, row-layout
  checkbox labels, theme-aware dialogs, safe-area and short-viewport rules.
- Accessibility: field-level errors, `aria-invalid`, `aria-describedby`, focus management,
  contextual action names, undo for routine removals.
- Navigation: a direct "Today's session" action that routes to the current workflow state.

## 7. Verification plan

- DOM tests for the Exercise Details submit and History Add set.
- API tests for invalid goal, constraint kind, region, pattern, muscle and VBT family, and for
  legacy preservation.
- Static checks that constrained fields do not render as unrestricted text.
- Browser checks at 440 x 956 and 956 x 440: document width does not exceed the viewport,
  dialogs fit, controls are 16 px, primary targets are at least 44 px.
- Existing tests and a manual native-iOS pass for keyboard, picker and safe-area behaviour.
- No training-engine regression: the prescription, readiness and workout tests remain green.

## 8. Checkpoints

1. P0 contract fixes, canonical athlete/exercise controls, server validation, and targeted
   tests. Stop for owner review.
2. Active-workout and readiness rebuild, mobile foundations, and responsive tables.
3. Accessibility, navigation CTA and remaining interaction polish.
4. Mobile cards, searchable exercise pickers, advanced disclosures, field-level errors and
   final verification. Closed.

## 9. Checkpoint 1 report (2026-10-28)

Implemented:

- P0-1 and P0-2: Exercise Details no longer reads an undefined `day_roles`; History
  "Add set" appends to the real card container and uses the existing wiring helper.
- P0-3 and P0-4: primary goal and constraint kind are canonical selects; the API rejects
  unknown goals, kinds, severities, regions, forbidden patterns/exercises and exercise ids
  with a useful 400.
- Canonical choices are served from `GET /api/options` and included in `GET /api/state`;
  the exercise catalogue exposes patterns, VBT families and muscles.
- Exercise pattern is a select; VBT family is a select of current families with an explicit
  "Add new family…" option and a validated new-family input; primary muscles are a checklist. Existing legacy values are shown as
  "legacy - not in current list" and kept unless deliberately changed.
- Constraint forbidden patterns/exercises are checklists; region, kind and severity are
  selects; `since`/`settled_on` use month inputs.
- `health` in `config/athlete-state.example.yaml` is removed; `longevity` remains the
  example goal.

Tests run:

- `pytest tests/test_canonical_options.py tests/test_exercise_admin.py tests/test_ui_frontend.py tests/test_docs_consistency.py` - pass.
- `pytest tests/test_prescribe.py tests/test_workout.py tests/test_athlete_state.py ...` - 115 pass.
- Targeted `tests/test_web.py` page, options, state-edit and rejection tests - pass.
- `ruff check .` - pass.
- The full `tests/test_web.py` file did not complete within the available run window and was
  stopped; targeted tests covering the changed endpoints passed.
- The local UI was restarted; `GET /`, `GET /api/options` and `POST /api/programme`
  returned 200.

At that point the next scope was: ordered goal-rank control and focus-lift multi-picker,
exercise single-select searchable pickers, readiness semantics/presets, active-workout rebuild,
mobile tables, touch/safe-area/dialog/accessibility work, and the remaining verification. All
of it was completed in later checkpoints.

## 10. Checkpoint 2 report (2026-10-28)

Implemented the daily-path and mobile-foundation work:

- Active workout: logger first; plan and device import are collapsed secondary sections;
  the end-session form follows the logged sets. Planned exercises are cards; logged sets are
  cards. The eight-column table is gone.
- The logger keeps the selected exercise, preserves load/reps/RIR after adding a set, clears
  only optional velocity, and pre-fills from the plan when the lift changes. It shows the
  planned target and next set number inline. Load 0 is no longer converted to "missing".
- Readiness: 1-5 options now label their endpoints; stress and soreness say 5 = none. Quick
  readiness presets are available inside the Workflow form, not only on the Readiness page.
- Prescription review and History now render cards on narrow screens while retaining desktop
  tables. Review and ended-workout tables have scroll containers; import previews do too.
- Dialogs use theme variables, a bounded height and a mobile width. Form controls are 16 px
  on narrow/short viewports, primary actions have larger targets, and safe-area and
  short-landscape rules are present.

Verification: `ruff check .`, Node syntax checks, and the affected
`test_ui_frontend.py`, `test_docs_consistency.py`, `test_workout.py` and
`test_prescribe.py` tests pass. The served page still returns 200 and contains the new
workout structure. No native Safari or browser-automation pass has been run; rendered layout
and keyboard behaviour still need that check.

At that point the next scope was accessibility error association and focus management, the
navigation CTA, destructive-action confirmation, ordered goal-rank/focus-lift pickers, and the
full test/verification pass. These were completed in later checkpoints.

## 11. Checkpoint 3 report (2026-10-28)

Implemented the remaining interaction and contract polish:

- Accessibility: the sidebar is a modal dialog with focus movement, a Tab trap, `aria-modal`,
  `aria-current` on the active nav item and focus restoration. Dialogs have accessible
  names. Live regions cover the workout, exercise, history and athlete messages, and the
  workout logger sets `aria-invalid` and focuses the field on its own validation errors.
- The Today screen has a direct "Start today's session" action that routes to the current
  Workflow state.
- Goal rank is an ordered, reorderable checklist; focus lifts are a searchable constrained
  checklist. Legacy focus ids stay visible and selected.
- Suitability, e1RM, test, exposure and history-edit exercise fields are constrained selects.
  The API rejects unknown exercise ids in history corrections as well as in state writes.
- Removing a set or a planned exercise asks for confirmation with the lift and set in the
  prompt. The old unused exercise datalist was removed.
- Prescription and History cards remain the narrow-screen presentation; desktop tables remain.

Verification:

- `ruff check .`, Node syntax checks and the affected history/UI/workout/prescription tests pass.
- A broad non-integration test lane was started; its completion is recorded in the final
  verification section below.
- Native Safari, rendered keyboard behaviour and a physical-iPhone pass are still not claimed.

## 12. Final verification (2026-10-28)

Automated:

- `ruff check .` — clean.
- Node `--check` on every client module — clean.
- Affected contract/API suites — pass, including canonical options/validation, exercise admin,
  UI contracts, docs consistency, history, workout, prescription and athlete state.
- The full non-integration/non-golden lane — **exit 0**, rerun after the checkpoint 4 changes.
- The integration/golden lane — **exit 0**, 20 tests.
- Targeted web tests for the page, `/api/options`, state editing, canonical rejection,
  history correction, readiness presets and field-level errors — pass.
- The local UI was restarted on the existing database; `GET /`, `GET /api/options`,
  `GET /api/readiness/presets` and `POST /api/programme` returned 200.
- The owner reported completing the native iPhone pass and reviewing the working tree.

Not claimed by the agent:

- The agent did not independently operate a physical iPhone. The owner's pass is the
  device-level evidence for keyboard, picker and safe-area behaviour.
- No browser automation or post-change screenshot review is installed in this environment.

## 13. Checkpoint 4 report (2026-10-28)

Implemented the remaining accepted UI refinements:

- Review rubric: desktop keeps the table; narrow screens use one card per rubric item.
  Anchors and the long "why" explanation are behind disclosures; the score input remains a
  single control (no duplicate inputs).
- Exercise pickers: a reusable search filter sits above the constrained native select for
  suitability, e1RM, test, exposure, history edit, workout Add exercise and the shared Swap
  dialog. The select still carries the canonical value; the filter only narrows choices.
- Workout Swap now has one searchable dialog rather than one 140-option select per plan card.
- `spinal_cost` is a validated 0-5, half-step number input with an ordinal helper. Explicit
  nulls now clear `vbt_family` and `spinal_cost` instead of silently preserving them.
- Exercise "Additional properties" and the Settings drop candidate-pool JSON are collapsed
  behind advanced disclosures; the generated settings-profile fields are unchanged.
- Selected 400 responses now include an additive `fields` map. The athlete profile,
  constraint, suitability, e1RM, test, exposure, symptom, block-start, declared-break,
  cardio, measurement, exercise editor, readiness and Settings forms use it to mark and focus
  the responsible input; the API `error` string remains unchanged. Manual workout sets now
  require reps and bound RIR to 0-6, and history corrections apply the same bounds to new or
  changed sets while leaving an unchanged legacy set alone.

Verification is recorded in the final verification section after the clean suite run.

## 14. Closeout

The audit is closed on 2026-10-28. All accepted implementation items are complete, the owner
completed the native iPhone pass, the full automated suite is green, and the working tree is
ready for commit. No further audit actions are open.

## Related

- [UI-MAP.md](UI-MAP.md) — route and panel map.
- [WEB-UI.md](WEB-UI.md) — API surface and manual browser checklist.
- [UI-IMPROVEMENT-PLAN.md](UI-IMPROVEMENT-PLAN.md) — earlier UI hardening work.

