# W0 — EXECUTION-PATH MAP AND BASELINE

**Status:** complete 2026-10-23.
**Method:** code-path trace plus the existing test suite. No implementation change.
**Scope:** import → stored state → prescription → workout → review → next prescription.

---

## 1. Main path

```text
CSV / UI form
  ↓
import_export
  raw_row → clean.build_clean_sets → sessions.build_sessions
  → session / clean_set / quarantine / readiness_day
  ↓
athlete state (profile, constraints, suitability, overrides, symptoms)
  ↓
readiness (manual/preset/context/import; date-scoped score)
  ↓
session type (explicit or rolling schedule)
  ↓
build_prescription
  selection → e1RM/load → readiness → back flare → continuity
  → VBT → under-MEV → MRV cap → deload → warm-up
  → constraints → minimum session → final validation
  ↓
prescription shown
  ↓
workout.start (plan frozen; UI commits prescription + provenance)
  ↓
sets / actual performance / end
  ↓
session + clean_set materialisation
  ↓
critique / review / calibration
  ↓
next prescription
```

The central invariant is visible in the code: **history is read only up to the requested
date**, and a prescription is built from stored records, not from a later session.

## 2. Stage table

| stage | entry point | core functions | reads | writes |
|---|---|---|---|---|
| import | `import`, `POST /api/import` | `store.importer.import_export`, `clean.build_clean_sets`, `sessions.build_sessions` | training CSV, readiness CSV, taxonomy, inference config | `run`, `run_event`, `raw_row`, `clean_set`, `session`, `readiness_day`, quarantine |
| state | `state`, `/api/state/*` | repositories + `constraints.evaluate` | profile, constraints, suitability, e1RM overrides, symptoms | append-only state rows |
| readiness | `readiness`, Readiness UI, `/api/readiness` | `features.readiness`, `features.readiness_score` | readiness entries, context flags, baseline, overrides | readiness entries/context/settings/overrides |
| session type | CLI `run`, web prescribe | `prescribe.schedule.next_session_type` or explicit choice | session history, rolling rule | none |
| selection | `select`, `/api/selection`, Apply selection | `prescribe.selection` | taxonomy, suitability, recent history, readiness, priorities | none until explicitly applied |
| load | `build_item` | `e1rm_decay`, `e1rm_calibration`, `loads.solve_load`, overrides | e1RM observations, measured tests, overrides, increments, last working load | none; refs in the item |
| readiness modifier | `_apply_readiness_score` | readiness score/factors, injury ceiling, optional set reduction | date score, per-lift readiness, injury signal, config | item load/RIR/sets + `MOD-FAT-001` |
| back flare | `_apply_back_flare` | symptom state + thresholds | latest low-back symptom | erector dose/main RIR |
| continuity | `_apply_continuity` | gap band + calibration + 20% load cap | session gap, returns, config | item load/RIR + `MOD-GAP-001` |
| VBT | `_attach_vbt_targets` | `vbt_calibration` | velocity sets, calibration | velocity target, calibration ids |
| under-MEV | `_apply_under_mev` | volume ledger | 4-week history by pattern | accessory set + `MOD-VOL-002` |
| MRV cap | `_apply_volume_cap` | volume landmarks | 7-day prior sets + proposed sets | accessory set reduction + `MOD-VOL-001` |
| deload | `deload.apply_items` | deload config, prior load factors, primary compounds | decision, current items, readiness/continuity factors | sets/load/RIR + `MOD-DELOAD-001` |
| warm-up | `warmup.attach` | ramp config | final item load | ramp sets |
| constraints | `constraints.evaluate` | stored state | athlete constraints/suitability | vetoes/warnings |
| minimum session | `minimum_session.apply` | target minutes, floors, timing estimate | explicit user request, current items | accessory/main sets + `MOD-MIN-001` |
| validation | `validate_prescription`, `validate_references` | rule document, `RuleContext` | final items, history, config | `issues`; no mutation |
| workout | `workout.start` / sets / end | `workout`, `score` | frozen plan, readiness, actual sets | workout rows/events, session/clean_set |
| review | `review`, `/api/review` | `critique.build_facts`, `score_session`, `record_marks` | session facts, rubric | marks, feedback, calibration |
| next prescription | repeat | — | all of the above | — |

## 3. Modifier ownership and order

| modifier | owner | applied after | applies to |
|---|---|---|---|
| `MOD-FAT-001` | `_apply_readiness_score` | base load/RIR | load, RIR, optional sets |
| `MOD-BACK-001` | `_apply_back_flare` | readiness | erector dose, main RIR |
| `MOD-GAP-001` | `_apply_continuity` | back flare | load/RIR; 20% combined cap with readiness |
| `MOD-VOL-002` | `_apply_under_mev` | continuity | accessory sets upward, bounded |
| `MOD-VOL-001` | `_apply_volume_cap` | under-MEV | accessory sets downward, bounded |
| `MOD-DELOAD-001` | `deload.apply_items` | volume cap | sets/load/RIR, one-way floors |
| `MOD-MIN-001` | `minimum_session.apply` | deload + warm-up | volume only; explicit user |
| `MOD-SELECT-001` | selection block in `build_prescription` | before load | exercise identity |
| `MOD-E1RM-001` | `build_item` / calibration | load path | e1RM correction |
| `MOD-E1RM-DECAY-001` | `build_item` / decay | load path | stale e1RM adjustment |

Deload is now applied **inside** the build, before minimum session and final validation. The
old post-build deload path is gone from the CLI and web callers.

## 4. Branch inventory on the main path

### Import

- training-only, readiness-only and pair imports;
- overlapping/duplicate rows and raw-import idempotence;
- bodyweight/added-load resolution;
- warm-up RIR 6 marker;
- unknown exercise → quarantine, never silent drop;
- duplicate readiness rows → merge by `most_complete` / latest;
- empty or fully overlapping files.

### Prescription

- explicit session type vs rolling auto;
- selection applied / near-comparable confirmation / class C blocked;
- slots with multiple variants vs one exercise;
- e1RM present / calibrated / decayed / stale but last load available / no load;
- power/bodyweight/external load;
- readiness ready / insufficient / unknown / low / context-suppressed device fields;
- injury ceiling, back flare, hard constraint;
- short/medium/long continuity bands and calibrated vs fixed factor;
- under-MEV / normal / over-MRV;
- deload scheduled / reactive / none / suggestion only;
- minimum requested / unavailable / already short / partial / deep tier;
- final validation pass/fail;
- proposal path (LLM) when explicitly enabled.

### Workout and review

- start from a prescription;
- plan modified in-session (swap/add/remove/set count);
- actual set add/update/remove;
- timed vs manual duration;
- sRPE recorded vs not recorded;
- completed vs abandoned;
- review marks/confidence/feedback;
- completed workout materialisation and later import.

## 5. Inputs that can be missing, stale or non-comparable

| input | failure mode | current handling |
|---|---|---|
| e1RM | stale, missing, variant-specific | decay window; calibrated test correction; last working-load fallback; warning |
| exercise identity | renamed, date-scoped implement, variant | taxonomy resolution; trap-bar date scope; unknown quarantine |
| bodyweight | external vs total vs added | `load_basis`; total only for e1RM |
| RIR | missing / warm-up / 0 / high | missing is not zero; RIR 6 is warm-up; RIR 0 is surfaced; primary window validated |
| readiness | missing / partial / device-only / context | `unknown`/`insufficient`; device baseline; context flags |
| symptoms | absent | `unknown`, not “no flare” |
| constraints | unrecorded | warning “unknown, not absent”; no permission inferred |
| session plan | UI preview vs committed | preview read-only; workout start commits prescription |
| duration | imported logs have no timestamps | unmeasurable in imported rubric; live workout measures |
| history | late/backfilled rows | date-scoped context; no lookahead, but timestamp quality remains a known limitation |
| volume | 4-week/7-day windows differ | explicit window per feature; not one universal number |

## 6. Current test coverage

| area | representative tests |
|---|---|
| clean/import/session reconstruction | `test_clean.py`, `test_sessions.py`, `test_store.py` |
| domain arithmetic | `test_e1rm.py`, `test_load.py`, `test_rir.py`, `test_numeric.py` |
| rules | `test_rules_loader.py`, `test_rules_policy.py` |
| prescription | `test_prescribe.py`, `test_golden_prescription.py`, `test_session_types.py` |
| readiness | `test_readiness*.py`, `test_lift_readiness.py` |
| continuity | `test_continuity*.py` |
| volume/MRV | `test_volume.py`, `test_progress.py` |
| deload/minimum/W3 | `test_w3_interactions.py`, `test_minimum_session.py`, `test_programme.py` |
| selection/proposal | `test_selection*.py`, `test_proposal.py`, `test_main_substitution.py` |
| workout | `test_workout.py`, `test_web.py` |
| critique/review/calibration | `test_critique*.py`, `test_reviews*.py`, `test_eval.py` |
| outcomes/readiness feedback | `test_outcomes.py`, `test_readiness_feedback.py` |
| web API | `test_web.py`, `test_run_web.py` |

**Current baseline:** 662 tests collected (647 public + 15 private), full suite passing at the
time of this map.

## 7. Candidate findings — not yet confirmed

These are questions for later workstreams, not defects established by W0.

| ID | candidate | next workstream |
|---|---|---|
| W0-C1 | `athlete_profile.max_session_minutes` is stored/displayed but not consumed by the prescription engine; templates use a fixed `time_cap_s` | W1 |
| W0-C2 | `SESSION_DURATION` in the rubric remains unmeasurable for imported sessions even though live workouts have measured duration | W11 |
| W0-C3 | `MOD-MIN-001` can remove all non-essential items; if no remaining item carries the ref, `prescription_modifier` may have no row even though the note records the mode | W3 follow-up / provenance |
| W0-C4 | Deload and minimum estimates use planning seconds, not measured duration; the note is an estimate | W11 |
| W0-C5 | The UI prescribe preview and the committed workout artifact are different states; this is intentional but should stay explicit | W11/parity |
| W0-C6 | The rolling schedule and attendance are not measured by the progress dashboard | W1/W7 |
| W0-C7 | Imported logs have no reliable timestamps, so session duration and late entry remain weak | W2/W11 |
| W0-C8 | The minimum-session deep tier can reduce a main lift to 2 sets; the evidence for that dose is a heuristic, not a trial | W4 |

None of these is confirmed as a defect by this map.

## 8. Exit-criteria assessment

- **Every prescription modifier has a named owner and call order:** met; see §3.
- **No undocumented branch remains on the main path:** documented at the level of the main
  path and its material branches; proposal/LLM and some UI-only branches are summarized, not
  exhaustively traced.
- **Inputs that can be missing/stale/non-comparable are listed:** met; see §5.
- **Current test baseline is recorded:** met; 662 tests.

W0 is a map, not a validation result. It does not establish that the programme is effective.
