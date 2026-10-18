# ROADMAP

The resume point for this project. If you are picking this up cold — human or agent — read
this file first, then [`AGENTS.md`](AGENTS.md) for the rules of the codebase.

Last updated: 2026-10-17 · version `0.0.1-dev` · **271 tests passing**

---

## 1. How to resume

```bash
cd strength-training-app
.venv/bin/python -m pytest            # expect: 271 passed
.venv/bin/python tools/profile_data.py   # data profile (needs data/raw/)
.venv/bin/python tools/baseline.py       # strength baseline
```

Then read, in order:

1. **this file** — where we are and what is next
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
| 5.5 | Athlete state — DATA-MODEL §11 tables | **not started** | planned `store/migrations/0002_athlete_state.sql`, repository writers; unblocks Days A/C and hard constraints |
| 6 | Critique rubric + trace | **done** | `critique/facts.py`, `critique/rubric.py`, `trace/run.py`; 6 measurable items + 2 unmeasured |
| 7 | LLM layer (critique + prescription agents) | **not started** | planned `agents/llm.py`, `tools.py`, `NullLLM` |
| 8 | Backtest harness + labelled eval set | **not started** | planned `eval/backtest.py`, `eval/labelled_rubric.yaml` |
| 9 | CLI (`coach run --date`) | **not started** | planned `cli.py` |
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
loss). The critique is persisted append-only inside a `run` trace. There is **no CLI and no
LLM narration yet**.

## 3. Next actions

The main line is **7 → 8 → 9**. Phase 5.5 is scheduled but not on that line: it must land
before Days A/C and before any hard constraint can veto, and it can start as soon as the
answers are available.

1. **Phase 7 — LLM layer.** `NullLLM` plus one optional narrative call behind `--llm on`;
   the run must be identical in structure with it off (`docs/V0-SCOPE.md` §4 criterion 5).
2. **Phase 5.5 — athlete state tables (§11).** Not a detour: it is the prerequisite for Days
   A/C and for any hard constraint, and it can run in parallel with phases 7-9.
   *Why now and not earlier:* nothing can be stored until the tables exist, so collecting
   the answers before then would mean holding personal data with nowhere to put it.
   *Scope:* `athlete_profile`, `constraint`, `exercise_suitability`, `metric_definition`,
   `symptom_log` as numbered migration `0002_athlete_state.sql` plus writers.
   *Acceptance:* the five tables exist and are empty-not-guessed; a `constraint` row with
   `severity = hard_exclude` vetoes a proposed exercise deterministically (with a test); a
   `exercise_suitability.will_do = 0` is surfaced as a substitution, never silently dropped;
   an empty table yields `unknown`, never "nothing is wrong".
   *Input:* answers come from `private/docs/INFO-REQUESTS.md` §1-3 and are read back for
   confirmation before being written.
3. **Phase 8 — backtest harness + labelled eval set.** Replay history through phases 5-6 and
   compare against a hand-marked rubric.
4. **Phase 9 — CLI (`coach run --date`).** The end-to-end slice in `docs/V0-SCOPE.md` §1:
   ingest, prescribe, critique, persist, and print a rationale where every number cites a
   rule or a data point.

**Known follow-up from phase 5:** `PRG-DP-001` stays `unknown` even though the engine supplies
rep ranges, because its scope includes `back_extension`, which Day B never prescribes and so
has no range. That is honest (the rule covers Days A/C too) but noisy in the warning list; it
disappears once Days A/C get templates.

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
