# Evidence-Based Strength Coach

A local-first strength-coaching tool built around a **fixed methodology**. It ingests
training and readiness logs, critiques the most recent session against explicit programme
rules, prescribes the next session, and explains both with citations to the exact rules used.

**Design principle:** *Python writes the what, the LLM writes the why.* All arithmetic,
cleaning, calibration and prescription generation is deterministic Python. The LLM layer is
small, tool-bound and auditable — and the system still emits a safe, valid prescription if the
LLM call fails entirely.

---

## Status

**Proposal stage.** The architecture, data model and rule format are written and reviewed;
the deterministic core is partially implemented (`utils`, `domain`, `features.baseline`).

What runs today:

- the data profiler, which produces the evidence base for the design,
- the baseline reporter, which summarises current strength per lift,
- the shared `utils` / `domain` layer they are built on, with tests.

The ingestion → prescription → critique pipeline is deliberately **not** built yet. See
`docs/V0-SCOPE.md`.

## Quickstart

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

.venv/bin/python -m pytest            # 98 tests
.venv/bin/python tools/profile_data.py    # profile your own export
.venv/bin/python tools/baseline.py        # strength baseline, latest date in the log
```

The tools read `data/raw/training_log.csv` and `data/raw/readiness.csv`. See
[`data/README.md`](data/README.md) for the expected schema.

## Privacy

This is a public repository and it contains **no training data and no personal metrics**.

- `data/` is git-ignored (the raw exports are a complete personal training history).
- `private/` is git-ignored (documents derived from a real log).
- The code, schemas, rules and tests contain no athlete-specific values.

If you run this yourself, everything you generate stays local unless you choose to commit it.

## Repository map

```
config/
  exercises/taxonomy.v1.yaml   exercise identity + properties (single source of truth)
  rules/programme.v1.yaml      the constitution as citable, machine-checkable rules
docs/                          the design record
data/                          your exports (git-ignored)
strength_coach/
  utils/                       permanent shared helpers (pure, tested)
  domain/                      pure domain arithmetic (e1RM, load)
  features/                    derived features
tools/profile_data.py          reproducible data profile
tools/baseline.py              reproducible strength baseline
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

0. [`ROADMAP.md`](ROADMAP.md) — where the project is right now, and what is next
1. [`docs/DECISIONS.md`](docs/DECISIONS.md) — decisions that are expensive to reverse
2. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — layers, data flow, where the LLM sits
3. [`docs/DATA-MODEL.md`](docs/DATA-MODEL.md) — schemas, append-only records
4. [`docs/DATA-QUALITY.md`](docs/DATA-QUALITY.md) — the data-quality ledger (`DQ-*`)
5. [`docs/RULES-FORMAT.md`](docs/RULES-FORMAT.md) — citable rule IDs
6. [`docs/VBT-CALIBRATION.md`](docs/VBT-CALIBRATION.md) — velocity targets and sparsity
7. [`docs/V0-SCOPE.md`](docs/V0-SCOPE.md) — the first end-to-end slice
8. [`docs/OPEN-QUESTIONS.md`](docs/OPEN-QUESTIONS.md) — open ambiguities, with defaults
9. [`docs/SANITY-CHECKS.md`](docs/SANITY-CHECKS.md) — external verification of the model
10. [`docs/TRAINING-GUIDELINES.md`](docs/TRAINING-GUIDELINES.md) — evidence vs the programme

Contributor and agent instructions: [`AGENTS.md`](AGENTS.md).
