# ROADMAP

The resume point for this project. If you are picking this up cold — human or agent — read
this file first, then [`AGENTS.md`](AGENTS.md) for the rules of the codebase.

Last updated: 2026-10-17 · **v0 complete** · version `0.1.0-dev` · **316 tests passing**

---

## 1. How to resume

```bash
cd strength-training-app
.venv/bin/python -m pytest            # expect: 316 passed
.venv/bin/python tools/profile_data.py   # data profile (needs data/raw/)
.venv/bin/python tools/baseline.py       # strength baseline
```

Then read, in order:

1. [`USER-GUIDE.md`](USER-GUIDE.md) — how to use what exists
2. **this file** — where we are and what is next
2. [`docs/DECISIONS.md`](docs/DECISIONS.md) — decisions that are expensive to reverse
3. [`docs/OPEN-QUESTIONS.md`](docs/OPEN-QUESTIONS.md) — what is still ambiguous, with defaults
4. [`docs/V0-SCOPE.md`](docs/V0-SCOPE.md) — the agreed scope and its exclusions
5. [`AGENTS.md`](AGENTS.md) — invariants, layering, definition of done

**Resume rule:** update the status table below in the same commit as any phase change. If the
table disagrees with the code, the table is wrong — fix it before adding features.

## 2. Status

| # | Phase | Status | Artifacts |
|---|---|---|---|
| 0 | Design + approval | **done** | `docs/ARCHITECTURE.md`, `DATA-MODEL.md`, `DATA-QUALITY.md`, `RULES-FORMAT.md`, `VBT-CALIBRATION.md`, `MODULE-LAYOUT.md`, `V0-SCOPE.md`, `OPEN-QUESTIONS.md`, `SANITY-CHECKS.md`, `TRAINING-GUIDELINES.md` |
| 1 | Ingest (clean + sessions) | **done** | `ingest/clean.py`, `ingest/sessions.py`, `config/templates/days.v1.yaml` |
| 2 | Derived features + VBT calibration | **done** | `features/derived.py`, `features/baseline.py`, `features/vbt_calibration.py`, `domain/e1rm.py`, `domain/load.py`, `domain/rir.py` |
| 3 | Store (SQLite, append-only) | **done** | `store/migrations/0001_initial.sql`, `store/db.py`, `store/repositories.py`, `store/importer.py` |
| 4 | Rules loader + policy engine | **done** | `rules/loader.py`, `registry.py`, `context.py`, `policy.py`; predicates for all five rules |
| 5 | Prescription engine (Day B) + deterministic fallback | **done** | `prescribe/templates.py`, `config.py`, `loads.py`, `engine.py`, `fallback.py`; `config/thresholds.v1.yaml` |
| 5.5 | Athlete state — DATA-MODEL §11 tables | **v0.1** | planned `store/migrations/0003_athlete_state.sql`; unblocks Days A/C and hard constraints |
| 6 | Critique rubric + trace | **done** | `critique/facts.py`, `critique/rubric.py`, `trace/run.py`; 6 measurable items + 2 unmeasured |
| 7 | LLM layer (narrative only) | **done** | `agents/client.py`, `config.py`, `narrative.py`; `config/llm.example.toml`, `tools/llm_check.py` |
| 8 | Backtest harness + labelled eval set | **done** | `eval/harness.py`, `eval/labels.py`, `tools/eval_prepare.py`, `tools/backtest.py`; 3 hand-marked sessions, 42% item agreement |
| 9 | CLI (`run` / `review` / `calibrate` / `import`) | **done** | `cli.py`; prescriptions persisted; calibration loop closed |
| v0.1 | Next version | **planned** | see §3: athlete state, Days A/C, symptom input, VBT wiring, larger labelled set |
| — | UI | **deferred indefinitely** | out of scope by request |

### What works end to end today

A real export can be cleaned, flagged, quarantined, grouped into sessions, given a programme
day guess, calibrated for velocity targets, and **persisted**: one import writes `raw_row`,
`clean_set`, `session` and `quarantine` inside a replayable `run`/`run_event` trace, and
re-importing the same file writes no duplicate rows. The constitution can now be evaluated
against that history: `rules` parses the YAML into hash-bearing `Rule` objects, the registry
supplies one predicate per `check.fn`, and `policy` returns a verdict per rule with citable
evidence. A **Day B session is now generated**: loads solved from recent e1RM (or double
progression for accessories), rounded down to the athlete's 0.5 kg microplates, with
MOD-FAT-001 reducing loads when sleep or energy is <= 2. Every item cites a rule id and a
stored set, and the prescription refuses to be executable if a load, the RIR window, the
erector-day rule or the weekly spinal cap would be broken. A performed session can now be
**critiqued**: six rubric items score it (RIR adherence, progression adherence, weekly spinal
cost, essential work, redundancy, rotation) with evidence references, and two are stored as
`measurable = 0` because the export cannot support them (session duration, within-set velocity
loss). The critique is persisted append-only inside a `run` trace. An **optional narrative** can explain
either artifact: the model receives the facts as JSON, may not compute, and its output is
recorded as a `run_event` rather than written into a prescription or a score. With no model
configured (`NullLLM`) the run is structurally identical and loses only the prose. There is
**the full v0 slice runs**: `strength-coach run --date` imports if needed, critiques the
last session, prescribes the date, persists both inside a run trace, and prints a rationale
that cites a rule or a stored fact. `review` is the calibration loop: it shows the session
beside the rubric's scores, takes marks, stores them append-only, and reports running
agreement immediately. Two of the three marks are reconstructed from memory and excluded;
on the one remembered session, 60% of items agree within ±0.25 (`DEC-EVAL-03/04`).

## 3. v0.1 — the next version

v0 is complete (see §2 and the user guide). This is the agenda for the next version, in
dependency order. Nothing here blocks using v0 as it stands.

### 3.1 Athlete state — the §11 tables  (prerequisite for 3.2-3.4)

Scope: `athlete_profile`, `constraint`, `exercise_suitability`, `metric_definition`,
`symptom_log`, as numbered migration `0003_athlete_state.sql`, plus writers and a CLI to
enter them.

Why it is first: it is the only way goals, injuries and preferences become *state* rather than
something an agent remembers. Until it exists, no hard constraint can veto anything and an
empty table is indistinguishable from "no constraint".

Acceptance: the five tables exist; a `constraint` row with `severity = hard_exclude` vetoes a
proposed exercise deterministically (test); `exercise_suitability.will_do = 0` surfaces as a
substitution, never a silent drop; an empty table yields `unknown`, never "nothing is wrong".

Input: `private/docs/INFO-REQUESTS.md` §1-3, read back for confirmation before being written.

### 3.2 Days A and C

Depends on 3.1, plus the erector-ramp anchor (Q3) and the SSB question (H1). Day B was chosen
for v0 exactly because it avoids both.

Acceptance: a template per day with its own essential lifts; `PRG-SCHED-001` enforced on both
(no erector work on the hinge day, erector work allowed on A/C); a golden prescription per
day, in the same style as `tests/fixtures/golden_day_b.yaml`.

Consequence: `PRG-DP-001` stops being `unknown`. It is unknown today only because its scope
includes `back_extension`, which Day B never prescribes and so has no rep range.

### 3.3 Symptom input

Depends on 3.1 (`symptom_log`). This is the missing safety input (Q4): a manual `--back 0-3`
per session, with `settled_within_48h`.

Acceptance: `PRG-EREC-001` and `MOD-BACK-001` evaluate instead of returning `unknown`; the
stability gate uses real entries; every verdict cites the symptom rows it used.

### 3.4 VBT prescription wiring

Deferred by `DEC-VBT-01`. The calibration (band, sparsity ladder, versioning) already exists
and is tested; what is missing is the rule that turns a band into a target:

- which rep in the set is targeted — the first, the last, or a mean;
- what tolerance counts as "on target" before a set is flagged;
- what to prescribe when the band is wide, or when the lift is `uncalibrated`.

Acceptance: `PrescriptionItem` carries `velocity_target` and `vbt_basis`;
`prescription.calibration_ids` cites the rows used; an uncalibrated lift says so explicitly;
the golden fixture gains velocity columns.

Do not start this before those three questions have answers — inventing them is what the
deferral exists to avoid.

### 3.5 A labelled set worth tuning against

No code. Continue `review --session DATE` after sessions that are still fresh; the report
needs roughly ten *remembered* sessions per item before a weight or definition is changed
(`DEC-EVAL-03`, `DEC-EVAL-04`). Two of the three current marks are reconstructed and excluded.

### 3.6 Deliberately not planned

- A UI (deferred by request).
- Multi-athlete or cloud sync: this is local-first by design.
- RAG over the programme: rules are cited by id, and exact lookup beats semantic search here.
- Automatic rubric retuning: the report proposes, a person decides.

## 4. Known gaps and risks

| gap | impact | mitigation / status |
|---|---|---|
| No persistence | cannot replay a past day; work is lost between runs | **resolved** — `run`/`run_event` trace + append-only tables (phase 3) |
| Erector ramp has no anchor | `PRG-EREC-001` returns `unknown`; Day A/C cannot be prescribed safely | rule implemented; `unknown` names both missing inputs (`OPEN-QUESTIONS` Q3, Q4) |
| No athlete state | no injury, goal or preference can veto a prescription; an empty table currently reads as "no constraint" | phase 5.5 (scheduled) builds the §11 tables; until then nothing is inferred from silence |
| No symptom input | back-flare modifier and the ramp's stability gate cannot run | needs a manual input (`OPEN-QUESTIONS` Q4), stored in `symptom_log` (phase 5.5) |
| No timestamps | session duration unmeasurable; two sessions on one date indistinguishable | flagged as `POSSIBLE_DOUBLE_SESSION`; duration dropped (`OPEN-QUESTIONS` Q5) |
| Only Day B can be prescribed | Days A/C are blocked by the erector-ramp anchor (Q3), the SSB question (H1) and the missing §11 tables | phase 5 ships B only, per `V0-SCOPE.md`; phase 5.5 builds the state tables, then A/C templates land with the answers |
| Only ~45% of dates map to a programme day | day-specific rules cannot be scored on the rest | day inference reports explicit reasons; do not force a bucket |
| Velocity is per-set only | within-set velocity loss not computable | labelled decay proxy; `DEC-VELOCITY-01` |
| Rubric calibrated on **one reliable session** | 60% of items within ±0.25 (MAE 0.23); the other two marks are reconstructed from memory and excluded | `DEC-EVAL-04`; needs ~10 remembered sessions before changing weights |
| Spinal cost ignores load and effort | a 50 kg good-morning at RIR 3 counts the same as a maximal one | ASSUMPTION-02 / Q8; a weighted-by-e1RM or RIR version needs the athlete's decision |
| VBT targets not prescribed | a prescription carries no `velocity_target`; `calibration_ids` is empty | deferred to v0.1 by `DEC-VBT-01`; the calibration code and tests remain, only the prescription wiring is postponed |
| ACWR contested | cannot be a hard rule | advisory only; `DEC-ACWR-01` |

## 5. Idea backlog (not approved, not scheduled)

Recorded so good ideas are not lost, explicitly **not** commitments:

- `sets_per_muscle_group_per_week` feature, so volume is audited in sets rather than sessions.
- Readiness composite with a `metric_definition` table so new metrics need no code change.
- Rotation scoring split by session provenance (app-assigned vs self-directed).
- Grip-strength left/right asymmetry as a readiness input and a unilateral-work trigger.
- Per-lift manual velocity overrides with expiry.
- Regime-change detection (a lift's volume collapsing while a substitute rises).

## 6. How to change this roadmap

- Phase status changes go in the table, in the same commit as the work.
- New phases get a number and an acceptance criterion before any code is written.
- Anything that changes a rule, a threshold that affects a load, or a recorded decision must
  also append to [`docs/DECISIONS.md`](docs/DECISIONS.md).
- Personal goals, injuries and preferences are **not** recorded here — this repository is
  public. They live in the git-ignored `private/`.
