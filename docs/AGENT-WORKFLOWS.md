# Agent workflows — strength-training-app

Detailed procedures for working in the Python server. The lean entry point is
../AGENTS.md; workspace-wide rules are in ../../AGENTS.md.

## 1. Orientation

This is a local-first strength-coaching tool with a fixed methodology. Python computes;
the LLM explains. If the LLM is unavailable, the system still emits a safe, valid
prescription. The server is authoritative for readiness, prescriptions, loads, sets,
progression and scoring.

Read only what the task needs:
- ROADMAP.md — live phase status and next actions.
- docs/DECISIONS.md — expensive-to-reverse decisions.
- docs/DATA-MODEL.md — canonical schema.
- docs/API.md — HTTP contracts.
- docs/README.md and docs/manifest.yaml — public documentation index and metadata.

Keep CI workflow files aligned with main. Main is integration; development is where work
happens.

## 2. Domain rules agents must not undo

### Non-negotiable invariants

1. The constitution (docs/RULES-FORMAT.md, config/rules/) is the source of truth.
2. The LLM never does arithmetic; every prescription number comes from Python.
3. The policy engine may veto/downgrade the LLM; the reverse is forbidden.
4. Readiness is 1–5, higher is better. Stress = 5 means no stress.
5. 0 is column-specific; never apply a global sentinel rule.
6. Unknown thresholds go in config as an ASSUMPTION, never invented science.
7. Prescriptions, critiques, calibrations and rule versions are append-only.
8. Never deduplicate repeated training rows.
9. Unknown exercise names are resolved or reported, never silently dropped.
10. Non-obvious decisions get a one-line domain-reason comment.
11. Goals, injuries and preferences are stored athlete state, not prompt text.
12. Empty/incomplete input produces unknown, never pass.
13. Never commit personal data; data/ and private/ are git-ignored.

### Sentinel rules

| Column | 0 means | Handling |
|---|---|---|
| Avg_velocity, Avg_power, Avg_rom, TUT | device not used | sentinel to NaN |
| Weight_Used | unweighted bodyweight | valid; preserve |
| RIR | true failure | valid; preserve; RIR 6 = warm-up |
| readiness Weight/HRV/RHR | missing | sentinel to NaN |
| readiness *_Readiness | missing | sentinel to NaN |
| readiness Sleep/Energy/Mood/Soreness/Stress | impossible | no sentinel |

Never reuse dates.NULL_DATE_TOKENS for numeric columns; it contains 0 and would erase
genuine RIR 0 observations.

### Exercise identity

- Resolve every raw name through utils.exercises; never branch on a raw log string.
- Preserve DEC-TRAPBAR-02 (date-scoped competition deadlift identity).
- Back extension and hyperextension share history; prefer back_extension when prescribing.
- RIR 6 is a warm-up, excluded from working volume/e1RM adjustment but preserved.
- Bodyweight progression acts on added load; total mass is used only for e1RM.
- Trap-bar RIR uses the default window; the empty override map is intentional.
- Effort window is RIR 1–4 with a 2–3 target; RIR 0 is forbidden.
- Adding an exercise is YAML, not Python. New properties need schema/docs updates.

## 3. Code layout

Import direction points down:
utils ← domain ← ingest/store ← features ← rules/prescribe/critique ← agents/eval.

- Shared computation belongs in utils (pure) or domain (domain arithmetic), never re-implemented.
- Config, not code: taxonomy, templates, rules, thresholds, rep ranges, load increments.
- Prefer small pure functions with explicit inputs; no global mutable state.
- Type-hint public functions; docstrings explain why.
- Python 3.11+; use from __future__ import annotations.
- No new dependency without a reason.

## 4. Tests and definition of done

Run the narrowest relevant tests while iterating. The default suite excludes integration,
golden, regression and slow layers.

    .venv/bin/python -m pytest tests/test_prescribe.py tests/test_rules_policy.py
    .venv/bin/python -m pytest --lf
    .venv/bin/python -m pytest -m "not integration and not golden and not regression and not slow"
    .venv/bin/python -m pytest -n 0

Run the default suite once before handing off. Optional layers run only when the owner
asks or in the release workflow:

    .venv/bin/python -m pytest -m "integration or regression or slow" --dist loadfile

A change is done when:
1. Relevant tests pass, and new behaviour has a test that fails without it.
2. Measured-fact changes still match private/docs/EVIDENCE.md, or both are updated.
3. Config changes carry a domain reason.
4. Judgement calls are recorded as assumptions/open questions.
5. Documentation checks pass when docs change.
6. Multi-statement writes use strength_coach.store.db.transaction.
7. Web handlers use data-action plus delegation, never dynamic inline handlers.
8. Dates use formatLocalDate/today, never UTC slices for machine defaults.
9. Unexpected web errors return a generic 500 and are logged; expected 400/404/409 stay useful.
10. Request bodies respect MAX_BODY_BYTES; never read an unbounded Content-Length.
11. ruff check passes; line length 110; no new per-file ignore without a reason.

Tests assert contracts, not incidental order. Golden fixtures pin full item order only
because the prescription is user-facing. If a test fails only because an unrelated item
moved, the test is too literal. Integration tests that import real exports are marked and
must not run in the fast lane; synthesise public test data.

### Waiting for long suites

Do not poll a running suite in short increments. Estimate from collected count/recent runs,
start it as a managed background job, wait once near that estimate, then inspect once.
Report the final summary.

### Measured suite duration

Measured 2026-11-10 on the **iMac coding host** (Intel Core i5-6500, 4 cores, 8 GB RAM,
macOS 12.7.6, Python 3.14.8, pytest 9.2.0, xdist `-n auto`):

| Command | Result | Test time | Wall time |
|---|---|---:|---:|
| `.venv/bin/python -m pytest` (default suite) | 1706 passed | 104.6 s | ~105 s |
| `.venv/bin/python -m pytest -m ""` (all layers) | 1747 passed | 107.0 s | ~108 s |

These are iMac figures for scheduling one background run; they say nothing about the
deployed server. The ODROID-C4 is the deployed server and benchmarking host, and its
resolver-build timings in [`PERFORMANCE-PROFILE.md`](PERFORMANCE-PROFILE.md) were measured
on that hardware: this table does not change them, and they remain the reference for
deployed behaviour. Re-measure when the suite grows materially.

## 5. Documentation governance

- docs/manifest.yaml is authoritative for public document metadata.
- Current public guidance lives in docs/ and gets a manifest entry.
- Internal design specs live in docs/design/ (maintainer audience).
- Completed plans/audits move to docs/archive/ and get a row in its README.
- Link to the canonical explanation; do not maintain duplicate descriptions.
- Never add private/ to the manifest, viewer or a public index.
- docs/README.md is the human index; docs/manifest.yaml is the machine index.
- tests/test_docs_manifest.py and tests/test_docs_consistency.py enforce coverage, links,
  DEC/LIM references and the public/private boundary.
- The iOS client plan, iPhone user guide and device acceptance live in the sibling StrengthApp
  repository; do not add client-owned documents here. Server-owned iOS API contracts stay in
  docs/design/ because the server is authoritative for the API. Link across repositories with
  absolute GitHub URLs; the portfolio placement policy is
  [docs/DOCUMENTATION.md](https://github.com/georgesdib/strength-app/blob/main/docs/DOCUMENTATION.md).

Do not duplicate the full docs map here. The manifest and docs/README.md are the source.

## 6. CLI/UI parity

Everything built in the CLI should also be available in the local web UI where practicable,
in the same change. The UI calls the same core function as the CLI, never re-implements it.

If a capability cannot reasonably live in the UI (interactive prompt, destructive migration,
host-level operation), record the exception in docs/WEB-UI.md and ROADMAP.md rather than
leaving it silently missing.

The in-browser terminal was removed (DEC-WEB-02). Do not reintroduce a state-changing
browser command runner without authentication.

Standing permission: restart the local web process when code changes make it stale, without
asking first. Restart it the same way it was started (same DB/bind/port, detached), then
verify:
- GET / returns 200.
- POST /api/programme returns 200.
- The served HTML no longer contains removed pages.

Config-only edits do not need a restart; any change under strength_coach/ does.

## 7. Ask before changing

- Adding a hard rule.
- Changing a threshold that affects a prescription.
- Interpreting an ambiguous rule; add it to OPEN-QUESTIONS.md.
- Phase status changes; update ROADMAP.md in the same commit.
- Fixing data that looks wrong: flag/quarantine, never silently delete.

State the ambiguity, options and recommendation, then wait.

## 8. Migrations

See AGENT-MIGRATIONS.md for schema, append-only, transaction, preservation and test rules.
See AGENT-DEBUGGING.md for logs, failure triage and data quarantine.
