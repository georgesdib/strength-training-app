# AUDIT FOLLOW-UP — report

**Date:** 2026-10-27
**Status: CLOSED 2026-10-27.** No open findings, residuals or follow-up actions. The owner
backs up `data/coach.db` externally; browser-level UI tests and a SQLite concurrency test were
explicitly declined as unnecessary. The pre-`0041` backup is retained locally (git-ignored).
**Scope:** the five previous audit findings and the changed surfaces from
[`AUDIT-FOLLOW-UP-PLAN.md`](AUDIT-FOLLOW-UP-PLAN.md): back-flare scope, quality-limited power,
programme documentation, same-date accounting and the interaction tests. Risk-based T1/T2/T3
checks; not a line-by-line re-audit of the whole application.

**Audited code:** the plan's A–D work is in `7a332b6` (`fe2a20e` for A, `1da0cfc` for D,
`8784a0b` for C). While this audit ran, another session committed `8a8fcea` (exercise-admin
day-role validation); that change is outside this audit's scope and is not evaluated here.

---

## 1. Executive verdict

**The application is functionally reliable enough for continued personal use, with the
qualifications below.** All five previous findings are fixed behaviourally and covered by
regression tests. The full public+private suite passes, the generated programme summary matches
configuration, and the new prescription invariants hold across the four session types.

It is **not** medically validated, and this audit does not establish that the training
methodology is optimal. All four residuals below are now closed: **R1 and R3 were fixed** on
2026-10-27 after owner approval (`DEC-VOLUME-32`, `DEC-READINESS-18`); **R2 and R4 were accepted
and closed** (R2 is not a defect; R4 is a coverage limitation). No S3 residual remains open.

No S1 (wrong prescription/executability, cap breach, data loss) or S2 (material user-visible
wrong number/state) finding remains open.

---

## 2. Findings

### 2.1 Closed — the five previous findings

| id | severity | finding | behavioural evidence | status |
|---|---|---|---|---|
| F1 | S1 (was) | The bench+hinge sumo was non-essential, so the flare skipped the day's heaviest spinal item while still citing `MOD-BACK-001` | `tests/test_symptom.py`, `tests/test_back_flare_interactions.py`; sumo RIR 3, load re-solved, citation only on change | **closed** (`DEC-SPINE-08`) |
| F2 | S2 (was) | Power work stored RIR 4-5 while the engine instructed a quality stop; the warning was not persisted, and RIR analytics scored box-jump RIR against 2-3 | `tests/test_power_work.py`; null RIR, `effort_model=quality`, stored stop rule, API/prompt/analytics exclusion | **closed** (`DEC-POWER-03`) |
| F3 | S2 (was) | The review and dependent summaries described the old single-leg RDL support | `tests/test_programme_summary.py`; generated block names the sumo, 57 sets/week, 4/5.5 spinal week; `tools/programme_summary.py --check` exits 0 | **closed** (`DEC-SPINE-05` reconciliation) |
| F4 | S2 (was) | A plan rebuilt on a date with a recorded session counted the same sets as completed and proposed in MRV, spinal and the budget | `tests/test_same_date_accounting.py`; revision view, plan counted once, report/apply agree | **closed** (`DEC-VOLUME-31`) |
| F5 | S3 (was) | The symptom tests did not assert the sumo or the final prescription under combined modifiers | `tests/test_back_flare_interactions.py`; final item/RIR/load/issues for readiness, gap, deload, spinal and DUP | **closed** (A.4.1) |

### 2.2 Residuals (all closed 2026-10-27)

| id | severity | residual | evidence / why it remains | impact |
|---|---|---|---|---|
| R1 | S3 (closed) | `plan_drop` and the under-MEV top-up were counting a same-date session as completed *and* adding the plan | Fixed by `DEC-VOLUME-32`: `_apply_under_mev` uses `prior_to(for_date)`; `plan_drop` supplies the template as the revision plan. `tests/test_same_date_accounting.py` covers both | Was a narrow opt-in edge; now the revision semantic is uniform across the budget paths |
| R2 | S3 (closed, not a defect) | `features/baseline.working_rir_median` includes box-jump RIR values, though `rir_compliance_pct` excludes them | Descriptive median only; the value is recorded effort, not a target. DEC-POWER-03 excludes the window/compliance path | Intended behaviour: preserve the logged observation without scoring it as a target |
| R3 | S3 (closed) | Readiness's own RIR bump was not re-solved against the load (pre-existing) | Fixed by `DEC-READINESS-18`: the load is re-solved at the bumped RIR from the factor-scaled e1RM. `tests/test_readiness_score.py` asserts the solver result and the changed-load case | Loads for readiness-reduced items changed; the printed RIR and load now describe the same set |
| R4 | S3 (closed, accepted coverage) | No browser-level UI test suite; ruff is configured but not installed; SQLite concurrency/lock not exercised. The populated-DB migration was rehearsed and applied on 2026-10-27 | Tooling limitation, stated rather than papered over; migration now verified on the real file. The owner declined browser and concurrency follow-up tests on 2026-10-27 and backs up the live DB externally | UI rendering and rare concurrency paths remain unverified but accepted |

All four are closed. R1 and R3 are fixed with regression tests; R2 is not a defect; R4 is an
accepted coverage limitation. No S3 residual remains open.

---

## 3. Changes made

| commit | change |
|---|---|
| `83197b1` | Audit plan plus `DEC-POWER-02` and `DEC-VOLUME-30` |
| `8784a0b` | **C**: `prescribe/summary.py`, `tools/programme_summary.py`, generated review tables, ROADMAP/CORE/VOLUME-MANAGEMENT reconciliation, stale-name test |
| `fe2a20e` | **A**: sumo essential, flare hold at build time with load re-solve, erector-dose ceiling, `DEC-SPINE-08`, `LIM-53` closed, interaction matrix, constitution 1.19.0 wording |
| `1da0cfc` | **D**: `RuleContext.prior_to`, MRV/spinal/budget revision view, same-date note/warning, `DEC-VOLUME-31` |
| `7a332b6` | **B**: quality-limited power, nullable RIR, `effort_model`/`quality_stop`, migration `0041`, API/UI/CLI/narrative/proposal, analytics, `DEC-POWER-03` |
| R1/R3 pass | Same-date revision now covers `plan_drop` and under-MEV (`DEC-VOLUME-32`); readiness re-solves the load at the bumped RIR (`DEC-READINESS-18`); tests and live migration rehearsal |

No training threshold, exercise choice or programme structure was changed beyond the approved
decisions. No personal workout data is used in the report or fixtures.

---

## 4. Tests and evidence

### 4.1 Baseline and final suite

| command | result |
|---|---|
| `.venv/bin/python -m pytest -q` before the fixes | **exit 0**, 887 collected (the pre-change baseline) |
| `.venv/bin/python -m pytest -q` after all fixes | **exit 0**, **925 tests collected** (910 public + 15 private integration) |

The final run includes the concurrent exercise-admin commit; the audit's own changes are green.

### 4.2 Five-fix verification

```text
.venv/bin/python -m pytest \
  tests/test_symptom.py tests/test_back_flare_interactions.py \
  tests/test_power_work.py tests/test_programme_summary.py \
  tests/test_same_date_accounting.py tests/test_invariants.py -q
```

**exit 0, 55 passed.**

### 4.3 Date-sensitive run in the production timezone

The host and the running web process are `Europe/London` (`/etc/timezone`, `timedatectl`;
the process has `TZ` unset and inherits the system zone). The full suite in §4.1 therefore ran
in London.

```text
TZ=Europe/London .venv/bin/python -m pytest \
  tests/test_continuity.py tests/test_undulation.py \
  tests/test_same_date_accounting.py tests/test_declared_break.py -q
```

**exit 0, 24 passed.**

A second run under a non-local `TZ=America/New_York` also passed 24, so the date tests do not
depend on the machine-local calendar.

### 4.4 Other checks

| check | result |
|---|---|
| `tests/test_docs_consistency.py` | **9 passed** |
| `python tools/programme_summary.py --check` | `programme summary is current` (exit 0) |
| R1/R3 targeted (`tests/test_same_date_accounting.py`, `tests/test_readiness_score.py`) | **30 passed** |
| migration `0041` rehearsal and live apply | copy passed; live now has 41 migrations, `integrity_check = ok`, old rows `effort_model = 'rir'`, `quality_stop IS NULL`, `rir_target` digest unchanged |
| `node --check strength_coach/web/static/app.js` / `workout.js` | exit 0 |
| `ruff` | **not run — configured in `pyproject.toml` but not installed in `.venv`** |
| browser suite | **none present**; UI exercised by HTTP/unit tests and JS syntax only |

---

## 5. Unverified areas

- **Browser-level UI behaviour** (clicks, stale responses, layout, accessibility); no browser
  suite exists, so only the API/JS contract and syntax were checked.
- **Live LLM** availability, malformed output, timeout and refusal; `NullLLM` is the default and
  the deterministic path is what the tests exercise.
- **SQLite concurrency** under simultaneous requests; the app is single-user local, and no
  concurrency test was added. The migration itself was rehearsed on a copy and applied to the
  live `data/coach.db` on 2026-10-27 (backup retained).
- **Import fuzzing** beyond the existing malformed/overlap/idempotency tests; no new random
  corpus was generated.
- **Medical or training validity**; not audited and not claimed.

---

## 6. Residual risks

- **R1 is closed** — same-date accounting now covers MRV, the spinal cap, budget allocation,
  `plan_drop` and under-MEV.
- **R2 is closed** — the descriptive box-jump RIR median is not a target and cannot change a
  prescription; this is the intended behaviour.
- **R3 is closed** — readiness now re-solves the load at the bumped RIR; the load change is
  deliberate (`DEC-READINESS-18`).
- **Old prescriptions** keep their recorded RIR, including historical box-jump rows; this is
  append-only behaviour, not a migration defect.
- **Two-a-days** on one date are treated as that date's work (`ASSUMPTION-38`); a genuine second
  session would be undercounted by the revision view.
- **No browser/lint gate** means UI and style regressions rely on tests and manual checks. This
  is accepted as a coverage limitation; no browser or concurrency follow-up test is planned.

---

## 7. Closure

**The audit is fully closed as of 2026-10-27.** There are no open findings, no open residual
risks and no code follow-up actions.

- **Backup — done by the owner.** `data/coach.db` is backed up externally; the local
  pre-`0041` backup is also retained (git-ignored).
- **Browser-level UI test — struck.** The owner declined it on 2026-10-27. R4 remains an
  accepted coverage limitation, not an open action.
- **SQLite concurrency test — struck.** The owner declined it on 2026-10-27; the app is
  single-user local.
- **Migration `0041` — complete.** Rehearsed on a copy, applied live, 41 migrations recorded,
  `integrity_check = ok`, old rows default to `effort_model = 'rir'`, `quality_stop IS NULL`.
- **`ruff` / live LLM — coverage notes only.** Not required for closure; the deterministic tests
  and the `NullLLM` path are what the audit covered.

The deterministic engine remains authoritative. R1 and R3 are implemented as recorded decisions;
any further change to them needs a new decision.
