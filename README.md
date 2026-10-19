# Evidence-Based Strength Coach

A local-first strength-coaching tool built around a **fixed methodology**. It ingests
training and readiness logs, critiques the most recent session against explicit programme
rules, prescribes the next session, and explains both with citations to the exact rules used.

**New here? Start with the [user guide](USER-GUIDE.md).**

**Design principle:** *Python writes the what, the LLM writes the why.* All arithmetic,
cleaning, calibration and prescription generation is deterministic Python. The LLM layer is
small, tool-bound and auditable — and the system still emits a safe, valid prescription if the
LLM call fails entirely.

---

## Status

**v0 complete; v0.1 in progress.** The full slice runs: import → prescribe a day → critique
the last session → review it → calibrate. Days A, B and C are prescribable, athlete state
(goals, constraints, suitability, e1RM overrides) and symptoms are stored, the LLM can narrate
or propose within the rules, and VBT targets are attached where the data supports them.
[ROADMAP.md](ROADMAP.md) lists what remains: the labelled calibration set (3.8, human work);
video moved to v0.2, which also covers readiness entry, manual logging, format adapters and
the programme view.

What runs today:

- **ingest** — both exports, cleaned under the documented sentinel policy, quarantined rather
  than dropped, reconstructed into sessions with an explicit day guess;
- **store** — SQLite, append-only, numbered migrations, a replayable `run`/`run_event` trace;
- **rules** — the constitution loaded as hash-bearing rules, one predicate per `check.fn`,
  verdicts with citable evidence, and `unknown` where an input does not exist;
- **prescribe** — a deterministic session for Day A, B or C, whose loads are solved from a
  recent e1RM (or a manual override), rounded down to real increments, and validated for
  executability;
- **critique** — six measured rubric items against a stored session, two explicitly
  unmeasurable rather than guessed;
- **eval** — a backtest that replays sessions through the rubric and compares them with
  hand-made marks, per item and per session.

The CLI that ties these together is `strength-coach`; see the [user guide](USER-GUIDE.md).

## Quickstart

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
source .venv/bin/activate           # so `strength-coach` is on PATH

.venv/bin/python -m pytest            # 411 public tests (15 more locally, private)
.venv/bin/python tools/profile_data.py    # profile your own export
.venv/bin/python tools/baseline.py        # strength baseline, latest date in the log
.venv/bin/python tools/llm_check.py       # show the LLM configuration (see below)
.venv/bin/python tools/import_export.py   # load data/raw into data/coach.db
.venv/bin/python tools/eval_prepare.py --session <date>   # labelling sheet
.venv/bin/python tools/backtest.py        # rubric vs hand marks
```

The tools read `data/raw/training_log.csv` and `data/raw/readiness.csv`. See
[`data/README.md`](data/README.md) for the expected schema.

## Using it

```bash
python -m strength_coach.cli import                    # data/raw -> data/coach.db
python -m strength_coach.cli run --date 2026-10-20     # critique the last session, prescribe
python -m strength_coach.cli review --session 2026-10-15  # mark it; calibration updates
python -m strength_coach.cli calibrate                 # agreement report so far
```

`run` is the v0 slice: it critiques the most recent stored session and prescribes the
requested date, then prints every item with the rule id or stored set that justifies its
load. Re-running the same date writes nothing unless you pass `--force`.

`review` is the calibration loop. It shows the session beside the rubric's scores, asks for
your mark on each item, stores them append-only, and immediately prints running agreement.
Do it after any session you want to judge: the report gets sharper with every review, and an
item is flagged for revisiting only once it has five marks and still disagrees by more than
0.25. Nothing is retuned automatically — a rubric change is a decision, not a side effect.

## Privacy

This is a public repository and it contains **no training data and no personal metrics**.

- `data/` is git-ignored (the raw exports are a complete personal training history).
- `private/` is git-ignored (documents derived from a real log).
- The code, schemas, rules and tests contain no athlete-specific values.

If you run this yourself, everything you generate stays local unless you choose to commit it.

## Bring your own model

The LLM is optional. With no configuration the system runs with `NullLLM`: every
deterministic feature works, and the only thing missing is the narrative paragraph — no
prescription, score or rule verdict depends on a model being present.

To enable narration:

```bash
cp config/llm.example.toml config/llm.local.toml   # git-ignored
$EDITOR config/llm.local.toml                      # base_url, model, api_key
.venv/bin/python tools/llm_check.py                # show the effective settings
.venv/bin/python tools/llm_check.py --call         # send one test prompt
```

The default endpoint is **DeepSeek** (`https://api.deepseek.com/v1`, `deepseek-chat`), so a
provider plus an API key is enough. Any other **OpenAI-compatible** endpoint works too
(OpenAI, OpenRouter, vLLM, llama.cpp, Ollama) by setting `base_url` and `model`. The API key
is optional because a local server may not need one.

Prefer not to put the key on disk? The environment overrides the file:

| variable | meaning |
|---|---|
| `STRENGTH_COACH_LLM_PROVIDER` | `null` or `openai_compatible` |
| `STRENGTH_COACH_LLM_MODEL` | model name |
| `STRENGTH_COACH_LLM_BASE_URL` | endpoint root, e.g. `http://127.0.0.1:11434/v1` |
| `STRENGTH_COACH_LLM_API_KEY` | bearer token |
| `STRENGTH_COACH_LLM_TEMPERATURE` / `_MAX_TOKENS` / `_TIMEOUT_S` | sampling and limits |
| `STRENGTH_COACH_LLM_CONFIG` | path to a different settings file |

The model **never computes**: every number is produced by Python and handed to it as a fact.
Its output is recorded as a `run_event`, never written into a prescription or a score, so a
bad model can produce bad prose but cannot change what you lift.

## Repository map

```
config/
  exercises/taxonomy.v1.yaml   exercise identity + properties (single source of truth)
  rules/programme.v1.yaml      the constitution as citable, machine-checkable rules
  templates/days.v1.yaml       day identification + Day B prescription slots
  thresholds.v1.yaml           increments, rounding, e1RM window, fatigue multiplier
  llm.example.toml             LLM configuration template (the real file is git-ignored)
docs/                          the design record
data/                          your exports (git-ignored)
strength_coach/
  utils/                       permanent shared helpers (pure, tested)
  domain/                      pure domain arithmetic (e1RM, load)
  ingest/                      cleaning, flags, quarantine, sessions, readiness merge
  store/                       SQLite migrations, append-only repositories, read queries
  features/                    derived features, baselines, VBT calibration
  rules/                       constitution loader, predicates, policy verdicts
  prescribe/                   deterministic Day A/B/C engine and load solver
  critique/                    rubric over a stored session
  agents/                      LLM interface, config, narrative (NullLLM by default)
  trace/                       run lifecycle
  eval/                        backtest harness and labelled-set comparison
tools/profile_data.py          reproducible data profile
tools/baseline.py              reproducible strength baseline
tools/llm_check.py             shows the effective LLM settings; --call tests them
tests/                         unit + integration tests
```

## The data model in one paragraph

The logs are messy in ways that are not obvious: `0` means five different things depending on
the column, one weight column mixes unweighted / total-mass / added-load semantics, durations
are stored in a reps column for isometric holds, and there are no timestamps so sessions must
be reconstructed from dates alone. Repeated identical rows look like duplicates but are real
sets. Every one of those decisions is written down with its evidence in
[`docs/DATA-QUALITY.md`](docs/DATA-QUALITY.md), because a silent interpretation of any of them
would corrupt every number downstream.

## Reading order

1. [`USER-GUIDE.md`](USER-GUIDE.md) — how to install it, run it and read the output
2. [`ROADMAP.md`](ROADMAP.md) — where the project is right now, and what is next
3. [`docs/DECISIONS.md`](docs/DECISIONS.md) — decisions that are expensive to reverse
4. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — layers, data flow, where the LLM sits
5. [`docs/DATA-MODEL.md`](docs/DATA-MODEL.md) — schemas, append-only records
6. [`docs/DATA-QUALITY.md`](docs/DATA-QUALITY.md) — the data-quality ledger (`DQ-*`)
7. [`docs/RULES-FORMAT.md`](docs/RULES-FORMAT.md) — citable rule IDs
8. [`docs/VBT-CALIBRATION.md`](docs/VBT-CALIBRATION.md) — velocity targets and sparsity
9. [`docs/V0-SCOPE.md`](docs/V0-SCOPE.md) — the first end-to-end slice
10. [`docs/OPEN-QUESTIONS.md`](docs/OPEN-QUESTIONS.md) — open ambiguities, with defaults
11. [`docs/SANITY-CHECKS.md`](docs/SANITY-CHECKS.md) — external verification of the model
12. [`docs/TRAINING-GUIDELINES.md`](docs/TRAINING-GUIDELINES.md) — evidence vs the programme

Contributor and agent instructions: [`AGENTS.md`](AGENTS.md).
