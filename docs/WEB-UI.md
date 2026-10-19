# WEB UI

A local browser interface over the same Python core. It is an additional surface, not a
replacement for the CLI.

## Run

```bash
strength-coach web                 # http://127.0.0.1:8000
strength-coach web --open
strength-coach web --port 8001
```

**Local only, no authentication.** The default bind is 127.0.0.1. Do not pass a public host.

## Pages

- **Today** — goal, block week, readiness, injury signal, unreviewed count, recent sessions.
- **Import** — upload the training and readiness CSVs; parsed in memory, hashed and stored in
  SQLite, never written to the repository.
- **Prescribe** — date + day; deterministic prescription, warnings and notes; every item cites
  rule ids.
- **Review** — unreviewed/recent session sheet; engine scores shown for context; human marks,
  confidence and note; calibration report after saving.
- **Readiness** — any subset of 1-5 and device fields; manual values win per field; merged
  values show their source.
- **Athlete** — profile, constraints, suitability and the per-region injury signal (read-only).
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
| `POST /api/readiness` | `{date, values, note}` -> merged readiness |
| `GET /api/state` | profile, constraints, suitability, per-region injury signal |
| `GET /api/calibrate` | calibration report |
| `GET /api/docs` / `GET /api/docs/<name>` | doc list / rendered doc |

## Design

The web layer is serialisation and routing only. It calls the same functions as the CLI:
`build_prescription`, `build_facts`/`score_session`, `record_marks`, `record_manual`, and
`backtest`. A missing value is still `unknown`; the UI does not fill it in.

## Limitations

- No LLM proposal/chat UI (the CLI `run --propose` remains the path).
- No state-editing forms; those remain CLI operations. Import is available.
- No authentication; never expose beyond localhost.
