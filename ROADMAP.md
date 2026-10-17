# ROADMAP

The resume point for this project. If you are picking this up cold — human or agent — read
this file first, then [`AGENTS.md`](AGENTS.md) for the rules of the codebase.

Last updated: 2026-10-17 · version `0.0.1-dev` · **163 tests passing**

---

## 1. How to resume

```bash
cd strength-training-app
.venv/bin/python -m pytest            # expect: 163 passed
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
| 3 | Store (SQLite, append-only) | **not started** | planned `store/schema.sql`, `store/migrations/`, `store/db.py`, `store/repositories.py` |
| 4 | Rules loader + policy engine | **not started** | rules already encoded in `config/rules/programme.v1.yaml`; needs `rules/loader.py`, `registry.py`, `policy.py` |
| 5 | Prescription engine (Day B) + deterministic fallback | **not started** | planned `prescribe/templates.py`, `engine.py`, `fallback.py` |
| 6 | Critique rubric + trace | **not started** | planned `critique/facts.py`, `rubric.py`, `trace/run.py` |
| 7 | LLM layer (critique + prescription agents) | **not started** | planned `agents/llm.py`, `tools.py`, `NullLLM` |
| 8 | Backtest harness + labelled eval set | **not started** | planned `eval/backtest.py`, `eval/labelled_rubric.yaml` |
| 9 | CLI (`coach run --date`) | **not started** | planned `cli.py` |
| — | UI | **deferred indefinitely** | out of scope by request |

### What works end to end today

A real export can be cleaned, flagged, quarantined, grouped into sessions, given a programme
day guess, and calibrated for velocity targets. There is **no persistence and no
prescription/critique yet** — the pipeline runs in memory.

## 3. Next actions (in order)

1. **Phase 3 — store.** SQLite schema per `docs/DATA-MODEL.md` §1–§10, numbered migrations,
   append-only writes, `run`/`run_event` trace. Acceptance: cleaning a real export writes
   `clean_set` + `session` rows; re-running is idempotent in content, not in duplicate rows.
2. **Phase 4 — rules loader + policy.** Parse the YAML into `Rule` objects with a content
   hash; implement the registry predicates; evaluate with `veto` / `downgrade` / `warn` /
   `advisory` and the `unknown` verdict when inputs are missing. Acceptance: `PRG-RIR-001` and
   `PRG-SPINE-001` evaluate against historical sessions and produce verdicts with evidence
   references; `PRG-EREC-001` returns `unknown` because no symptom input exists.
3. **Phase 5 — prescription engine (Day B).** Deterministic, template-driven, unit-aware.
   Acceptance: the four `docs/V0-SCOPE.md` §4 criteria for executability, plus a golden test.

## 4. Known gaps and risks

| gap | impact | mitigation / status |
|---|---|---|
| No persistence | cannot replay a past day; work is lost between runs | Phase 3 (next) |
| Erector ramp has no anchor | `PRG-EREC-001` returns `unknown`; Day A/C cannot be prescribed safely | needs a block start date (`OPEN-QUESTIONS` Q3) |
| No symptom input | back-flare modifier and the ramp's stability gate cannot run | needs a manual input (`OPEN-QUESTIONS` Q4) |
| No timestamps | session duration unmeasurable; two sessions on one date indistinguishable | flagged as `POSSIBLE_DOUBLE_SESSION`; duration dropped (`OPEN-QUESTIONS` Q5) |
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
