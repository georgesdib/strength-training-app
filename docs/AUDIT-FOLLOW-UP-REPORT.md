# AUDIT FOLLOW-UP — report

**Date:** 2026-10-27
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
methodology is optimal. The four residuals below were reviewed with the owner on 2026-10-27.
**R2 and R4 were accepted and closed** (R2 is not a defect; R4 is a coverage limitation).
**R1 and R3 remain open** — they were not accepted or fixed, and are described here for the
owner's decision.

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

### 2.2 Residuals (R2/R4 closed; R1/R3 open)

| id | severity | residual | evidence / why it remains | impact |
|---|---|---|---|---|
| R1 | S3 | `plan_drop` and the under-MEV top-up still read the full context for a plan date with a recorded session | Deliberately out of DEC-VOLUME-31; the plan's D.7 records it. Only reachable with `main_lift_policy: drop` or a persistent under-MEV pattern and a same-date rebuild | A drop/under-MEV decision could be based on a week that counts the date's recorded work twice; narrow, opt-in edge |
| R2 | S3 | `features/baseline.working_rir_median` still includes box-jump RIR values, though `rir_compliance_pct` excludes them | Descriptive median only; the value is recorded effort, not a target. DEC-POWER-03 excludes the window/compliance path | A per-lift descriptive RIR median for box jumps is not a target; no prescription change |
| R3 | S3 | Readiness's own RIR bump is not re-solved against the load (pre-existing) | A.8; fixing it would change every readiness-reduced session and needs its own decision | The printed RIR after a readiness bump can sit on a load solved for the previous RIR; the direction is not guaranteed |
| R4 | S3 | No browser-level UI test suite; ruff is configured but not installed; SQLite concurrency/lock and a real populated-DB migration were not exercised | Tooling limitation, stated rather than papered over | UI rendering and rare concurrency/populated-DB paths are not verified automatically |

**R1 and R3 are open**; no code change was made. R1 is the only one that can change an
accounting decision in a narrow opt-in path; R3 would change loads if fixed. R2 and R4 are
closed as described above.

---

## 3. Changes made

| commit | change |
|---|---|
| `83197b1` | Audit plan plus `DEC-POWER-02` and `DEC-VOLUME-30` |
| `8784a0b` | **C**: `prescribe/summary.py`, `tools/programme_summary.py`, generated review tables, ROADMAP/CORE/VOLUME-MANAGEMENT reconciliation, stale-name test |
| `fe2a20e` | **A**: sumo essential, flare hold at build time with load re-solve, erector-dose ceiling, `DEC-SPINE-08`, `LIM-53` closed, interaction matrix, constitution 1.19.0 wording |
| `1da0cfc` | **D**: `RuleContext.prior_to`, MRV/spinal/budget revision view, same-date note/warning, `DEC-VOLUME-31` |
| `7a332b6` | **B**: quality-limited power, nullable RIR, `effort_model`/`quality_stop`, migration `0041`, API/UI/CLI/narrative/proposal, analytics, `DEC-POWER-03` |

No training threshold, exercise choice or programme structure was changed beyond the approved
decisions. No personal workout data is used in the report or fixtures.

---

## 4. Tests and evidence

### 4.1 Baseline and final suite

| command | result |
|---|---|
| `.venv/bin/python -m pytest -q` before the fixes | **exit 0**, 887 collected (the pre-change baseline) |
| `.venv/bin/python -m pytest -q` after all fixes | **exit 0**, **921 tests collected** (906 public + 15 private integration) |

The final run includes the concurrent exercise-admin commit; the audit's own changes are green.

### 4.2 Five-fix verification

```text
.venv/bin/python -m pytest \
  tests/test_symptom.py tests/test_back_flare_interactions.py \
  tests/test_power_work.py tests/test_programme_summary.py \
  tests/test_same_date_accounting.py tests/test_invariants.py -q
```

**exit 0, 53 passed.**

### 4.3 Date-sensitive run in a non-local timezone

```text
TZ=America/New_York .venv/bin/python -m pytest \
  tests/test_continuity.py tests/test_undulation.py \
  tests/test_same_date_accounting.py tests/test_declared_break.py -q
```

**exit 0, 22 passed.**

### 4.4 Other checks

| check | result |
|---|---|
| `tests/test_docs_consistency.py` | **9 passed** |
| `python tools/programme_summary.py --check` | `programme summary is current` (exit 0) |
| `node --check strength_coach/web/static/app.js` / `workout.js` | exit 0 |
| `ruff` | **not run — configured in `pyproject.toml` but not installed in `.venv`** |
| browser suite | **none present**; UI exercised by HTTP/unit tests and JS syntax only |

---

## 5. Unverified areas

- **Browser-level UI behaviour** (clicks, stale responses, layout, accessibility); no browser
  suite exists, so only the API/JS contract and syntax were checked.
- **Live LLM** availability, malformed output, timeout and refusal; `NullLLM` is the default and
  the deterministic path is what the tests exercise.
- **SQLite concurrency/lock behaviour** under simultaneous requests; the app is single-user
  local, and no concurrency test was added.
- **Migration on a real populated database**; migration `0041` is applied by the test suite on
  fresh databases, but a backup/rehearsal on the user's data was not run.
- **Import fuzzing** beyond the existing malformed/overlap/idempotency tests; no new random
  corpus was generated.
- **Medical or training validity**; not audited and not claimed.

---

## 6. Residual risks

- **R1 is open** — the most material residual: same-date accounting is fixed for MRV, the spinal
  cap and budget allocation, but not for `plan_drop` or under-MEV. It is opt-in/narrow but real.
- **R2 is closed** — the descriptive box-jump RIR median is not a target and cannot change a
  prescription; this is the intended behaviour.
- **R3 is open** — the pre-existing readiness-RIR/load mismatch. The flare change fixed the same
  pattern for the flare, but readiness's own bump was explicitly out of scope.
- **Old prescriptions** keep their recorded RIR, including historical box-jump rows; this is
  append-only behaviour, not a migration defect.
- **Two-a-days** on one date are treated as that date's work (`ASSUMPTION-38`); a genuine second
  session would be undercounted by the revision view.
- **No browser/lint gate** means UI and style regressions rely on tests and manual checks.

---

## 7. Recommended next actions

No code action is required for **R2/R4**; both are closed. **R1 and R3 remain open** and need an
owner decision before any code change:

1. **R1** — if `main_lift_policy: drop` or under-MEV is used, pass the revision view into
   `plan_drop`/under-MEV and add one same-date test each. This is an accounting change, not a
   training-rule change.
2. **R3** — decide whether readiness should re-solve the load at the bumped RIR (a load change),
   keep the current heuristic and document it, or change only one of the two outputs.

Optional operational check: rehearse migration `0041` on a **copy** of `data/coach.db` and verify
an old prescription still reads correctly. This is a migration safety check, not an R1/R3 fix.

The deterministic engine remains authoritative. R1 and R3 must not be changed without a separate
decision.
