# Evidence-Based Strength Coach

A local-first strength-coaching tool built around a **fixed methodology**. It ingests
training and readiness logs, critiques the most recent session against explicit programme
rules, prescribes the next session, and explains both with citations to the exact rules used.

**New here? Start with the [user guide](USER-GUIDE.md).** The canonical method summary is
[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md); public/private documentation rules are in
[`docs/PRIVACY.md`](docs/PRIVACY.md).

For a plain-English explanation of how a prescription is assembled—from athlete state and
readiness through exercise selection, load calculation, modifiers and validation—see
[`docs/WORKOUT-GENERATION.md`](docs/WORKOUT-GENERATION.md).

**Design principle:** *Python writes the what, the LLM writes the why.* All arithmetic,
cleaning, calibration and prescription generation is deterministic Python. The LLM layer is
small, tool-bound and auditable — and the system still emits a safe, valid prescription if the
LLM call fails entirely.

---

## Status

**v1.4.0 is released; v1.5 is planned.** The full slice runs:
import → readiness → prescribe a day → critique the last session → review it → calibrate. Days
are prescribable through rolling session types (squat, hinge, bench+squat, bench+hinge); athlete
state, constraints, suitability, e1RM overrides, symptoms and the exercise catalogue are editable
in the CLI and local web UI; the LLM can narrate or propose within the rules; VBT targets attach
where the data supports them.

Delivered in v0.2/v0.3: readiness score and overrides, wearable/HRV/RHR baselines, injury signal,
continuity calibration, cardio capture, measurements, session RPE/length, recent stress,
per-lift readiness, e1RM calibration/decay, rolling session types, readiness volume valve,
weekly volume ledger/MRV cap, exercise selection with A/B/C *variant* comparability, and the local web UI
with import, state, Programme, Exercises and calibration reports (the Terminal page was removed in 2026-10-28, `DEC-WEB-02`). v0.3 and v0.4 are
complete. v0.4 packaged the audit, documentation and form closeout. **v1.0 beta** packaged the
workable app and guided Workflow UI for user testing. **v1.1 beta** adds the raw Performance
view, configured relative-strength ratios, read-only monitoring analysis and the Phase 5A
review follow-up. **v1.2.0** removed the beta label and shipped the deterministic template resolver as an
opt-in feature behind `resolver.enabled` (default false). **v1.3.0** closed the UI redesign,
measurement/readiness cleanup and documentation infrastructure. **v1.4.0 is the current stable
release:** structured VBT target metadata, active-workout target feedback, completed-workout and
History target comparisons, and the longitudinal Performance VBT dashboard. The cardio capture
audit, a reproducible cardio impulse/shadow load and comparable calibration depth are deferred to
v1.5 (ROADMAP §4.13a/§4.14). Prospective validation
remains a future gate, not an active candidate; review follow-ups are in ROADMAP §4.20.
See [ROADMAP.md](ROADMAP.md).

What runs today:

- **ingest** — both exports, cleaned under the documented sentinel policy, quarantined rather
  than dropped, reconstructed into sessions with a canonical session type;
- **store** — SQLite, append-only, numbered migrations, a replayable `run`/`run_event` trace;
- **rules** — the constitution loaded as hash-bearing rules, one predicate per `check.fn`,
  verdicts with citable evidence, and `unknown` where an input does not exist;
- **prescribe** — a deterministic session of one of the four canonical types, whose loads are solved from a
  recent e1RM (or a manual override), rounded down to real increments, and validated for
  executability;
- **critique** — six measured rubric items against a stored session, two explicitly
  unmeasurable rather than guessed;
- **eval** — a backtest that replays sessions through the rubric and compares them with
  hand-made marks, per item and per session.

The CLI that ties these together is `strength-coach`; see the [user guide](USER-GUIDE.md).
For the decision order, limitations and hard boundaries, read
[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).
For the end-to-end explanation of workout generation and its assumptions, read
[`docs/WORKOUT-GENERATION.md`](docs/WORKOUT-GENERATION.md).

## Quickstart

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
source .venv/bin/activate           # so `strength-coach` is on PATH

.venv/bin/python -m pytest -m "not integration and not golden and not regression and not slow"   # fast iteration
.venv/bin/python -m pytest tests/test_prescribe.py --lf             # targeted / last failed
.venv/bin/python -m pytest            # public suite; optional layers excluded
.venv/bin/python -m pytest -m ""      # everything; -n 0 to debug serially
.venv/bin/python -m pytest -m "integration or regression or slow" --dist loadfile   # optional layers on request
.venv/bin/python tools/profile_data.py    # profile your own export
.venv/bin/python tools/baseline.py        # strength baseline, latest date in the log
.venv/bin/python tools/llm_check.py       # show the LLM configuration (see below)
.venv/bin/python tools/import_export.py   # load data/raw into data/coach.db
.venv/bin/python tools/eval_prepare.py --session <date>   # labelling sheet
.venv/bin/python tools/backtest.py        # rubric vs hand marks
.venv/bin/python tools/export_repo.py     # full export incl. private data and .git, no build/cache data
.venv/bin/python tools/db_transfer.py export   # database transfer archive (not a merge)
./run-web.sh                              # local web UI at http://127.0.0.1:8000
```

The tools read `data/raw/training_log.csv` and `data/raw/readiness.csv`. See
[`data/README.md`](data/README.md) for the expected schema. Use `--no-git` to leave `.git` out
of the export; the default archive contains private health data and is not encrypted.

After extracting an export, `./setup-venv.sh` creates `.venv` and installs the dev extras;
use `./setup-venv.sh --locked` for the `requirements.lock` versions.

## Moving the database between machines

`tools/db_transfer.py` moves `data/coach.db` as a **full replacement** by default. It is for
the case where one machine is authoritative and another is used for development;
`--upgrade-fill` is the narrow exception that can carry target-only rows.

```bash
# authoritative machine
python tools/db_transfer.py export --db data/coach.db --include-local-config
scp data/exports/coach-db-*.tar.gz dev-host:

# development machine: stop the app first
python tools/db_transfer.py import --archive coach-db-*.tar.gz --db data/coach.db --dry-run --include-local-config
python tools/db_transfer.py import --archive coach-db-*.tar.gz --db data/coach.db --force --include-local-config

# new machine with no target database yet
python tools/db_transfer.py import --archive coach-db-*.tar.gz --db data/coach.db --create --force --include-local-config
```

The database-only archive is the default. Add `--include-local-config` on export to carry the
git-ignored local overlays (`config/*.local.yaml`, `config/exercises/*.local.yaml` and
`config/llm.local.toml`) and to record their hashes in the manifest. Import requires the same
flag when the archive contains them, backs up any existing local config files, and rolls the
database back if the config restore fails. When `config/llm.local.toml` is present, the archive
includes the LLM key, so handle it as a secret.

The archive contains the SQLite snapshot, a manifest with the full applied migration set
(version and checksum), the app version and the database SHA-256. Import verifies the
archive, compares the complete migration set with the target, and **fails before replacing
anything** if any migration, checksum or database hash differs. It refuses while the target
has SQLite WAL side files, writes a `coach.db.pre-transfer-*` backup beside an existing
target, and then replaces the file atomically.

`--create` permits a missing target. The tool creates it at the local code's schema only after all
archive, schema and `--force` checks pass; a dry run does not create it. A newly created
target has no prior data, so no backup is written. If the archive is older than the local
code, combine `--create` with `--upgrade`.

Default import requires the source and target schemas to match exactly. Two schema opt-in
modes are available:

- **`--upgrade`** accepts a source that is older than the local code, applies the missing
  migrations to a copy, and then replaces the target. It fails if the source or target has a
  migration the local code does not know, or a checksum differs — downgrade and divergence are
  never applied.
- **`--upgrade-fill`** does the same, but also copies **target-only rows** into the upgraded
  source before replacement. It requires the target to already be at the local migration
  version, and fails if the source has rows the target lacks, if a shared row differs, if a
  table has no primary key and is not empty, or if a foreign-key/unique/trigger check fails.
  It never overwrites an existing row.

Neither side is labelled authoritative: you choose which archive to import and must pass
`--force`. Default import is a full replacement; `--upgrade-fill` is the only data-fill path,
and it is deliberately conservative. Anything the fill cannot prove safe aborts before the
target is touched. The archive contains personal health data and is not encrypted, so
transfer it over SSH or an encrypted disk.

`tools/backup_app.py` is the full-app backup. Its default archive includes non-secret local
config overlays but always excludes local secrets such as `config/llm.local.toml` and `.env`;
`--source-only` excludes the database, raw exports, private data and all local overlays.

## CI and releases

CI installs the pinned [`requirements.lock`](requirements.lock), runs Ruff, the public
unit/golden suite on Python 3.11 and 3.12, builds a source archive and wheel, and starts the
real web server against a disposable database for a smoke test. Release tags matching `v*`
re-run those gates and publish only after they pass. See
[`docs/RELEASING.md`](docs/RELEASING.md) for local commands, tag/version rules, branch
protection and recovery from a failed release.

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

`review` is the historical calibration loop. It shows the session beside the rubric's scores,
can record a mark per item append-only, and prints running agreement; an item is flagged for
revisiting once it has five marks and still disagrees by more than 0.25. **The loop is dormant
since 2026-11-13** (`DEC-EVAL-08`): no marks are requested and the review prompt is retired,
but existing marks and reports stay readable. Nothing is retuned automatically — a rubric
change is a decision, not a side effect.

## Privacy

This is a public repository and it contains **no training data and no personal metrics**.

- `data/` is git-ignored (the raw exports are a complete personal training history).
- `private/` is git-ignored (documents derived from a real log).
- The code, schemas, rules and tests contain no athlete-specific values.

If you run this yourself, everything you generate stays local unless you choose to commit it.

## Bring your own model

The LLM is optional. With no configuration the system runs with `NullLLM`:
deterministic prescriptions, scores and rule verdicts still work. Optional
LLM-generated narrative, LLM-assisted selection and the CLI LLM-proposal path
are unavailable; no prescription, score or rule verdict depends on a model being
present.

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
  templates/session-types.v1.yaml  canonical session templates
  templates/inference.v1.yaml      imported-session type inference
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
  prescribe/                   deterministic session-type engine and load solver
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
3. [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) — canonical decision flow, limitations and
   what the app will never do; [`docs/PRIVACY.md`](docs/PRIVACY.md) — public/private boundary
4. [`docs/DECISIONS.md`](docs/DECISIONS.md) — decisions that are expensive to reverse
5. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — layers, data flow, where the LLM sits
6. [`docs/DATA-MODEL.md`](docs/DATA-MODEL.md) — schemas, append-only records
7. [`docs/DATA-QUALITY.md`](docs/DATA-QUALITY.md) — the data-quality ledger (`DQ-*`)
8. [`docs/RULES-FORMAT.md`](docs/RULES-FORMAT.md) — citable rule IDs
9. [`docs/VBT-CALIBRATION.md`](docs/VBT-CALIBRATION.md) — velocity targets and sparsity
10. [`docs/V0-SCOPE.md`](docs/V0-SCOPE.md) — the first end-to-end slice
11. [`docs/OPEN-QUESTIONS.md`](docs/OPEN-QUESTIONS.md) — open ambiguities, with defaults
12. [`docs/SANITY-CHECKS.md`](docs/SANITY-CHECKS.md) — external verification of the model
13. [`docs/TRAINING-GUIDELINES.md`](docs/TRAINING-GUIDELINES.md) — evidence vs the programme

Contributor and agent instructions: [`AGENTS.md`](AGENTS.md).
