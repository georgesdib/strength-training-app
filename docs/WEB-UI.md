# WEB UI

A local browser interface over the same Python core. It is an additional surface, not a
replacement for the CLI.

## Run

```bash
./run-web.sh                       # launcher: finds the venv, opens the browser
./run-web.sh --no-open --port 8001
./run-web.sh --db other.db

strength-coach web                 # http://127.0.0.1:8000
strength-coach web --open
strength-coach web --port 8001
```

`run-web.sh` refuses a non-loopback `--host` and moves `--db` before the subcommand (it is a
global option in the CLI). It is convenience only: it ends in the same `strength-coach web`.

**Local only, no authentication.** The default bind is 127.0.0.1. Do not pass a public host.

## Pages

- **Today** — goal, block week, readiness, injury signal, unreviewed count, recent sessions.
- **Import** — upload the training and readiness CSVs; parsed in memory, hashed and stored in
  SQLite, never written to the repository. New cumulative exports are overlap-matched against
  stored rows, so old history is not duplicated.
- **Prescribe** — date + day; deterministic prescription, warnings and notes; every item cites
  rule ids.
- **Review** — unreviewed/recent session sheet; engine scores shown for context; human marks,
  plus a **Run rubric calibration** button (same report as `strength-coach calibrate`),
  confidence and note; calibration report after saving.
- **Readiness** — any subset of 1-5 and device fields; manual values win per field; the
  computed global/category score is shown; overrides take 0.00–1.00 with a reason. A current
  workout is refused until readiness is ready.
- **Athlete** — append-only editing of profile, constraints, suitability, e1RM overrides,
  strength tests, block start and symptoms; shows the current tables and injury signal.
- **Docs** — local Markdown rendered without external assets.

## API

| route | purpose |
|---|---|
| `GET /api/overview` | dashboard data |
| `POST /api/import` | `{training: {name, text}, readiness: {name, text}}` -> import report |
| `POST /api/prescribe` | `{date, day}` -> prescription |
| `GET /api/review/<session>` | session sheet |
| `POST /api/review/<session>` | `{scores, confidence, note}` -> marks |
| `GET /api/readiness/<date>` | merged readiness |
| `POST /api/readiness` | `{date, values, note}` -> merged readiness + score |
| `POST /api/readiness/override` | `{date, scope, value, reason}` -> merged readiness + score |
| `GET /api/readiness/calibrate` | calibration report text (no auto-apply) |
| `GET /api/state` | profile, constraints, suitability, e1RM, symptoms, injury signal |
| `GET /api/exercises` | canonical exercise catalogue for the pickers |
| `POST /api/state/profile` / `constraint` / `suitability` / `e1rm` / `test` / `symptom` / `block` | append-only state writes |
| `GET /api/calibrate` | calibration report |
| `GET /api/docs` / `GET /api/docs/<name>` | doc list / rendered doc |

## Design

The web layer is serialisation and routing only. It calls the same functions as the CLI:
`build_prescription`, `build_facts`/`score_session`, `record_marks`, `record_manual`, and
`backtest`. A missing value is still `unknown`; the UI does not fill it in.

## Limitations

- No LLM proposal/chat UI (the CLI `run --propose` remains the path).
- State editing is available; the taxonomy itself and programme rules remain config/CLI.
- No authentication; never expose beyond localhost.
