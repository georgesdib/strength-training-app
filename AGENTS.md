# AGENTS.md — how to work in this repository

Instructions for any AI agent (or human) contributing to this project. Read this before
editing anything. It encodes decisions that are easy to "helpfully" undo.

---

## 1. What this project is

A local-first strength-coaching tool with a **fixed methodology**. It is not a chatbot
that invents programmes. Python computes; the LLM explains. If the LLM is unavailable,
the system must still emit a safe, valid prescription.

## 2. Current status — read this first

**v0, v0.1 and v0.2 are complete; v0.3 is in progress.** Cardio is v0.4, video v0.5 (see ROADMAP). The labelled calibration set is §4.14.

**Read [`ROADMAP.md`](ROADMAP.md) first** — it holds the live phase status, the next actions
and the resume checklist. [`docs/DECISIONS.md`](docs/DECISIONS.md) holds every decision that is
expensive to reverse.

What exists today is:

- `docs/` — the proposal and design record (public).
- `private/docs/` — documents derived from a real training log (git-ignored, never pushed).
  `EVIDENCE.md`, `BASELINE.md`, `INFO-REQUESTS.md` live there.
- `data/raw/` — raw exports (git-ignored).
- `strength_coach/utils/` — permanent shared helpers (built early on purpose; see §4).
- `config/exercises/taxonomy.v1.yaml` — exercise identity + properties.
- `tests/` — tests for the above.
- `tools/profile_data.py` — regenerates `private/docs/EVIDENCE.md`.
- `tools/baseline.py` — regenerates the numbers in `private/docs/BASELINE.md`.
- `strength_coach/domain/` — e1RM, load arithmetic, RIR classes (tested).
- `strength_coach/ingest/` — cleaning, flags, quarantine, session reconstruction.
- `strength_coach/features/` — derived metrics, per-lift baseline, VBT calibration, per-region injury signal, cardio capture summary, periodic measurement log, optional session RPE/length, e1RM calibration/decay, per-lift readiness, strength fitness-fatigue shadow model, scheduled/reactive deload policy.
- `strength_coach/store/` — SQLite migrations, append-only repositories, import orchestration.
  `data/coach.db` is created on demand and is git-ignored.
- `strength_coach/rules/` — constitution loader, one predicate per `check.fn`, policy verdicts.
- `strength_coach/prescribe/` — deterministic Day A/B/C engine, load solver, fallback, and the constraint check that applies stored athlete state. `config/thresholds.v1.yaml` holds the increments and e1RM window.
- Athlete state lives in the §11 tables (`athlete_profile`, `athlete_constraint`, `exercise_suitability`, `metric_definition`, `symptom_log`), entered with `strength-coach state`.
- `strength_coach/critique/` — deterministic rubric over a stored session; unmeasurable metrics are stored `measurable = 0`.
- `strength_coach/trace/` — run lifecycle around `run` / `run_event`.
- `strength_coach/eval/` — backtest harness, labelled-set comparison, and the database-backed
  marks that make calibration continuous (`rubric_mark`, append-only).
- `strength_coach/cli.py` — `import`, `run`, `review`, `calibrate`, `state`, `block`, `e1rm`,
  `test`, `symptom`, `cardio`, `measure`, `fatigue`, `select`, `exercise`, `readiness`, `programme`, `web`. `review` (with `--pending`) is the routine that keeps calibration current.
- `strength_coach/web/` — local-only HTTP UI and JSON API over the same core; no authentication, bind 127.0.0.1.
- `strength_coach/agents/` — LLM interface, config, narrative and structured proposals.
  `NullLLM` is the default; the model may explain or propose, but never compute. Keys live in the git-ignored `config/llm.local.toml`
  or the environment (`config/llm.example.toml` is the committed template).
- `ROADMAP.md` — phase status and next actions (update it in the same commit as the work).

Build order, current status and the next actions live in `ROADMAP.md` — do not duplicate
them here, because two copies drift. Do not add a hosted UI. The local web UI exists because the user asked for it and must stay 127.0.0.1-only.

## 3. Non-negotiable invariants

Break any of these and the result is wrong even if the tests pass.

1. **The constitution (`docs/RULES-FORMAT.md`, `config/rules/`) is the source of truth.**
   Never silently reinterpret an ambiguous rule. Raise it as an open question.
2. **Never let the LLM do arithmetic.** Every number in a prescription comes from a
   Python function via a tool call.
3. **The LLM may never veto the rules.** The policy engine may veto or downgrade an LLM
   suggestion; the reverse is not allowed.
4. **Readiness scales are 1–5, higher is better.** `Stress = 5` means *no stress*.
   Any code assuming "stress 5 = bad" is a bug. There is a test for this.
5. **`0` is not one thing.** See §5.
6. **No fabricated science.** If a threshold is unknown, put it in config as an
   assumption and mark it `ASSUMPTION-n`. Do not invent a citation.
7. **Append-only records.** Prescriptions, critiques, calibrations and rule versions are
   never mutated; corrections create a new row with a pointer back.
8. **Never deduplicate training rows.** Identical repeated sets are real sets. See
   `docs/DATA-QUALITY.md` DQ-DUP-01.
9. **Unknown exercise names must not be silently dropped.** Resolve or report.
10. **Every non-obvious decision gets a one-line comment stating the domain reason.**
11. **User goals, injuries, tightness and preferences are STATE, not prompt text.**
    They live in the `athlete_profile` / `constraint` / `exercise_suitability` tables
    (`docs/DATA-MODEL.md` §11) so a hard constraint can veto a prescription
    deterministically, whatever an agent says.
12. **An empty/incomplete input produces an `unknown` verdict, never `pass`.**
13. **Never commit personal data.** `data/` and `private/` are git-ignored and this
    repository is public. If a test needs a realistic value, synthesise it. Tests that read
    `data/raw` and assert values derived from it are private (`tests/*_integration.py`, ignored).

## 4. Code layout rules

- Import direction points **down**: `utils` ← `domain` ← `ingest`/`store` ← `features` ←
  `rules`/`prescribe`/`critique` ← `agents`/`eval`. Nothing lower may import anything
  higher.
- **If a computation is needed in two places, it belongs in `utils` (pure) or `domain`
  (domain arithmetic) and is imported.** Never re-implement. The user asked for this
  explicitly.
- Config, not code: exercise taxonomy, day templates, rule documents, thresholds,
  rep ranges, load increments, calibration overrides.
- Prefer small pure functions with explicit inputs. No global mutable state.
- Type-hint public functions. Docstrings explain *why*, not just *what*.

## 5. The sentinel rules (memorise these)

`0` means different things per column. Never apply a global rule.

| Column | `0` means | Handling |
|---|---|---|
| `Avg_velocity`, `Avg_power`, `Avg_rom`, `TUT` | device not used | sentinel → NaN |
| `Weight_Used` | unweighted bodyweight movement | **valid**, preserve |
| `RIR` | true failure | **valid**, preserve. `RIR 6` = warm-up (`DEC-RIR-01`) |
| readiness `Weight`, `HRV`, `RHR`, `Fat_Percent` | missing | sentinel → NaN |
| readiness `*_Readiness` | missing | sentinel → NaN |
| readiness `Sleep`/`Energy`/`Mood`/`Soreness`/`Stress`/`Nutrition`/`Hydration` | impossible (1–5 scale) | no sentinel exists |

Do **not** reuse `dates.NULL_DATE_TOKENS` for numeric columns: it contains `"0"` and doing
so silently erased genuine `RIR = 0` observations during development.

## 6. Exercise identity

- Resolve every raw name through `utils.exercises`; never branch on the raw log string.
- Recorded decisions are encoded and **must not be reverted**:
  - `DEC-TRAPBAR-02` — "Competition Deadlift" is **date-scoped**: sumo deadlift before
    ~2026-08-17, trap-bar deadlift from then on and forward. Never relabel the whole history.
    The switch date is config (ASSUMPTION-05) and may change, especially with manual logging.
  - `DEC-BACKEXT-02` (amends `DEC-BACKEXT-01`) — back extension ≡ hyperextension **including
    historical rows**. `Hyperextensions` rows keep their own identity, but they **do** count
    as back-extension history for load and dose lookups.
  - `DEC-RIR-01` — `RIR 6` marks a **warm-up**. Not effort. Excluded from compliance,
    e1RM adjustment and working volume, but preserved and reported.
  - `DEC-LOAD-02` — bodyweight progression acts on **added load**; total mass is used only
    for an e1RM.
  - `DEC-WINDOW-01` — the trap bar's RIR window is the default (it used to be 3-4).
    The per-lift override map is kept, empty, so changing it back is config, not code.
  - `DEC-RIR-02` — the effort window is **RIR 1-4 with a 2-3 target**; RIR 0 is forbidden.
    The evidence is in `docs/RIR-EVIDENCE.md`.
- There is a standing directive: **back extension is the same as hyperextension, including its
  history.** When prescribing, prefer `back_extension`.
- Adding an exercise = editing YAML, not Python. If you need a new *property*, add it to
  the entity schema and document it in `docs/DATA-MODEL.md`.

## 7. Definition of done for any change

1. `python -m pytest` passes.
2. New behaviour has a test that fails without it.
3. If the change affects measured facts, `python tools/profile_data.py` still matches
   `private/docs/EVIDENCE.md` — or you have updated both.
4. New/changed config has a comment explaining the domain reason.
5. If you made a judgement call, it is written down as an assumption, not just in code.

### 7.1 How to run tests without wasting ten minutes

The full suite includes costly integration and golden tests. While iterating, run only what
the change can affect:

```bash
.venv/bin/python -m pytest tests/test_prescribe.py tests/test_rules_policy.py
.venv/bin/python -m pytest --lf                       # only the last failures
.venv/bin/python -m pytest -m "not integration and not golden"   # broad, ~2 min
.venv/bin/python -m pytest -n 0                       # serial, for debugging a failure
```

`pytest` runs in parallel by default (`pytest-xdist`, one worker per core). A full run is
about 4-5 minutes; the fast lane is under 2. Run the **full** suite once, before handing off
or committing — not after every edit. If a
test fails, fix it and re-run that file/marker first; a full re-run is the last step, not the
first reflex.

Tests assert **contracts, not incidental order**: e.g. "power work precedes the main lift"
rather than "item 0 is the box jump". Only the golden fixtures pin full item order, on
purpose, because the prescription is a user-facing document. When a template changes, update
the fixture deliberately; if a test fails only because an unrelated item moved position, the
test is too literal.

A test that imports the real export is `integration`-marked and must not run in the default
fast lane. If a public test needs data, synthesise it with `make_training`/`make_readiness` —
never read `data/raw`.

## 8. Style

- Python 3.11+. `from __future__ import annotations`.
- Small modules, explicit dataclasses, no clever metaprogramming.
- Exceptions over silent fallbacks; if a fallback is correct, name it and log it.
- Do not add a dependency without a reason in the PR text. Current runtime deps:
  `pandas`, `numpy`, `PyYAML`. Test dep: `pytest`.

## 9. Documentation map

| File | Contents |
|---|---|
| `USER-GUIDE.md` | how to install, run and read the output (the human-facing entry point) |
| `ROADMAP.md` | live phase status, next actions, resume checklist |
| `docs/DECISIONS.md` | append-only decision log (`DEC-*`) with where each is enforced |
| `docs/REFERENCES.md` | consolidated scientific bibliography with DOIs and where each is used |
| `docs/ARCHITECTURE.md` | layers, data flow, where the LLM sits |
| `docs/DATA-MODEL.md` | canonical schemas, tables, append-only records |
| `docs/DATA-QUALITY.md` | the decision ledger (DQ-*) and open sentinel questions |
| `docs/READINESS.md` | how readiness is derived, merged and used; what is config vs rule |
| `docs/READINESS-SCORE.md` | proposed global and per-lift readiness scoring, evidence and phases |
| `docs/CONTINUITY.md` | gap detection and re-entry rules; the injury signal is separate |
| `docs/INJURY-SIGNAL.md` | per-region injury signals, what "tolerated" loading means, injury-to-exercise links |
| `docs/CORE-TRAINING.md` | core/trunk training evidence and the proposed programme amendment |
| `docs/LONGEVITY-REVIEW.md` | modality review against the longevity-first goal: gaps, doses, priorities |
| `docs/FATIGUE-FITNESS.md` | fatigue-fitness evidence, strength recovery, e1RM calibration and why no model drives loads |
| `docs/LIFT-READINESS.md` | per-lift readiness evidence, components, weights and downward-only rule |
| `docs/EXERCISE-VARIANTS.md` | how to add a canonical variant, slot wiring, history caveat, selection tuning |
| `docs/SELECTION-COMPARABILITY.md` | evidence and proposed three-class guard for variant substitution |
| `docs/STRENGTH-PROGRAM-REVIEW.md` | evidence check and critique of the strength programme (review only) |
| `docs/VOLUME-MANAGEMENT.md` | MEV/MAV/MRV evidence, configured landmarks, ledger and MRV cap |
| `docs/NEXT-PHASE-FATIGUE-PLAN.md` | final lean non-cardio fatigue plan: sRPE/duration backfill, descriptive calibration, optional deload; no experiments |
| `docs/WEB-UI.md` | local web UI surface, API and its limitations |
| `docs/RIR-EVIDENCE.md` | why the effort window is RIR 1-4 with a 2-3 target |
| `docs/SPINAL-COST.md` | evidence behind the ordinal spinal-cost ratings |
| `docs/TRAINING-DYNAMICS.md` | evidence on 1RM testing, rep ranges and DUP; proposal, not decision |
| `docs/RULES-FORMAT.md` | citable rule IDs + 5 encoded rules |
| `docs/VBT-CALIBRATION.md` | clean set, sparsity, overrides, versioning, current wiring |
| `docs/VBT-EVIDENCE.md` | VBT evidence, best practices, what our data can and cannot support |
| `docs/MODULE-LAYOUT.md` | file layout and test strategy |
| `docs/V0-SCOPE.md` | smallest end-to-end slice and its exclusions |
| `docs/OPEN-QUESTIONS.md` | ranked design questions blocking the build |
| `docs/SANITY-CHECKS.md` | external verification of classification/formulas |
| `docs/TRAINING-GUIDELINES.md` | programme vs published evidence, with conflicts |
| `private/docs/EVIDENCE.md` | measured profile of a real export (personal) |
| `private/docs/BASELINE.md` | current strength baseline (personal) |
| `private/docs/INFO-REQUESTS.md` | goals/injury/suitability backlog (personal) |

## 10. CLI/UI parity — standing instruction

Everything built in the CLI must also be available in the local web UI **where practicable**,
in the same change. The UI must call the same core function as the CLI, never re-implement it.
If a capability cannot reasonably live in the UI (interactive prompt, destructive migration,
host-level operation), record the exception in `docs/WEB-UI.md` and `ROADMAP.md` §4.11 rather
than leaving it silently missing.

The in-browser terminal is the fallback for uncovered commands: it runs **only**
`strength-coach`, never a shell, and is bound to the UI database.

## 11. Things an agent should ask instead of doing

**Standing rule: when in doubt, ask the user.** Do not silently choose an interpretation,
a variant, a threshold, a data migration or a programme change because it seems convenient.
State the ambiguity, the options and your recommendation, then wait.

- Adding a new hard rule → ask; the constitution is versioned and owned by the user.
- Changing a threshold that affects a prescription → ask.
- Interpreting an ambiguous rule → add to `OPEN-QUESTIONS.md`, do not pick silently.
- Phase status changes → update `ROADMAP.md` in the same commit, never in a separate one.
- "Fixing" data that looks wrong (e.g. `Reps_Done = 1015`) → flag it, quarantine it, do
  not silently delete it.
