# Documentation index

This is the human entry point to the public documentation. The **authoritative machine-readable
list** is `manifest.yaml`: it defines every document's path, id, title, category, status and
audience, and the Docs viewer is generated from it. This page is a curated entry point; the
manifest is authoritative for metadata and navigation.

Start with [`USER-GUIDE.md`](../USER-GUIDE.md) to use the app, and [`ROADMAP.md`](../ROADMAP.md)
for current status and next actions. [`AGENTS.md`](../AGENTS.md) holds the engineering rules.

## Status legend

| status | meaning |
|---|---|
| `canonical` | Current guidance for its subject; update it when the behaviour changes |
| `evidence` | Evidence review or analysis that supports a decision; not a how-to |
| `reference` | Registers, schemas, bibliography, format specifications |
| `plan` | Active or gated plan; not yet implemented or not yet closed |
| `archived` | Completed/closed history in [`archive/`](archive/README.md); not current guidance |
| `design` | Internal design specification; not shown in the Docs viewer |

## Architecture and data

- [ARCHITECTURE.md](ARCHITECTURE.md) — layers, data flow, where the LLM sits
- [DATA-MODEL.md](DATA-MODEL.md) — canonical tables, append-only records
- [DATA-QUALITY.md](DATA-QUALITY.md) — DQ decision ledger and sentinel questions
- [PRIVACY.md](PRIVACY.md) — public/private boundary and external-LLM payload rules
- [RELEASING.md](RELEASING.md) — CI, pinned dependencies, release tagging

## Methodology and prescription

- [METHODOLOGY.md](METHODOLOGY.md) — versioned decision flow, limitations, never-do list
- [RULES-FORMAT.md](RULES-FORMAT.md) — the constitution format and rule IDs
- [SESSION-TEMPLATES.md](SESSION-TEMPLATES.md) — template/slot field guide
- [WORKOUT-GENERATION.md](WORKOUT-GENERATION.md) — how a prescription is built
- [VOLUME-MANAGEMENT.md](VOLUME-MANAGEMENT.md) / [VOLUME-BUDGET.md](VOLUME-BUDGET.md) — landmarks and operator guide
- [FREQUENCY-AND-VOLUME.md](FREQUENCY-AND-VOLUME.md) — sessions-per-week behaviour
- [MINIMUM-SESSION.md](MINIMUM-SESSION.md), [TECHNIQUE-THROTTLE.md](TECHNIQUE-THROTTLE.md)
- [SPINAL-COST.md](SPINAL-COST.md), [RIR-EVIDENCE.md](RIR-EVIDENCE.md), [TRAINING-DYNAMICS.md](TRAINING-DYNAMICS.md)

## Readiness, injury and readiness-dependent selection

- [READINESS.md](READINESS.md) — derivation, merge, gate and configuration
- [READINESS-SCORE.md](READINESS-SCORE.md) — global/per-lift score, overrides, limits
- [LIFT-READINESS.md](LIFT-READINESS.md) — per-lift components and downward-only rule
- [CONTINUITY.md](CONTINUITY.md), [INJURY-SIGNAL.md](INJURY-SIGNAL.md), [SYMPTOM-LOGGING.md](SYMPTOM-LOGGING.md)
- [FORM-ASSESSMENT.md](FORM-ASSESSMENT.md), [FORM-PROSPECTIVE.md](FORM-PROSPECTIVE.md), [FORM-USE-EVIDENCE.md](FORM-USE-EVIDENCE.md)
- [READINESS-EXERCISE-SELECTION-PLAN.md](READINESS-EXERCISE-SELECTION-PLAN.md) (implemented policy), [SELECTION-COMPARABILITY.md](SELECTION-COMPARABILITY.md)
- [FATIGUE-SIGNALS.md](FATIGUE-SIGNALS.md), [FATIGUE-FITNESS.md](FATIGUE-FITNESS.md)

## Features, UI and operations

- [WEB-UI.md](WEB-UI.md) — local web surface and limits
- [API.md](API.md) — HTTP API routes, security, limits and errors
- [UI-MAP.md](UI-MAP.md) — panel/route map and docs links
- [UI-CLI-PARITY.md](UI-CLI-PARITY.md) — parity and intentional gaps
- [OUTCOMES.md](OUTCOMES.md), [MONITORING-ANALYSIS.md](MONITORING-ANALYSIS.md)
- [TRAINING-DAY-MODEL.md](TRAINING-DAY-MODEL.md)
- [VBT-EVIDENCE.md](VBT-EVIDENCE.md), [VBT-CALIBRATION.md](VBT-CALIBRATION.md), [VBT-REP-LEVEL.md](VBT-REP-LEVEL.md), [REP-VELOCITY.md](REP-VELOCITY.md)

## Evidence, decisions, registers

- [DECISIONS.md](DECISIONS.md) — append-only decision log (`DEC-*`)
- [REFERENCES.md](REFERENCES.md) — bibliography with DOIs and usage
- [LIMITATIONS-REGISTER.md](LIMITATIONS-REGISTER.md) — living limitation index
- [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md) — live ambiguities and defaults
- [RUBRIC-CALIBRATION.md](RUBRIC-CALIBRATION.md) — calibration loop, B1 outcome and what to do next
- [SANITY-CHECKS.md](SANITY-CHECKS.md), [V0-SCOPE.md](V0-SCOPE.md)

## Active and gated plans

- [HIGH-INTENSITY-EXPOSURE-PLAN.md](HIGH-INTENSITY-EXPOSURE-PLAN.md) (Phase 3 pending)
- [INJURY-ATTRIBUTION-PLAN.md](INJURY-ATTRIBUTION-PLAN.md) (Phase 3 open)
- [LLM-INTEGRATION-PLAN.md](LLM-INTEGRATION-PLAN.md)
- [WEAKNESS-TARGETING-PLAN.md](WEAKNESS-TARGETING-PLAN.md) (gated)

## Archive and internal design

- [archive/](archive/README.md) — closed audits, completed plans and superseded proposals. Do not
  treat archived text as current guidance; each entry names its current canonical source. The
  W0–W12 working reports are grouped in the [audit appendix](archive/audits/README.md).
- `design/` — internal design specifications (monitoring). These are maintained in the
  repository but deliberately not shown in the Docs viewer; they are **public source**, not
  private data.

## Public/private boundary

`private/` is git-ignored and never served by the documentation UI or API; the public manifest
must not reference it. The boundary and its enforcement are documented in
[PRIVACY.md](PRIVACY.md); the manifest test enforces that no public entry resolves under
`private/`.

## Keeping this current

- A new public document lives in `docs/` (or `docs/archive/` only when it is completed history)
  and must be added to `manifest.yaml` with a category and status.
- A completed plan or closed audit moves to `docs/archive/` with a row in
  [`archive/README.md`](archive/README.md); its inbound links are updated.
- Do not duplicate a canonical explanation: link to the canonical document instead.
- The manifest and these indexes are checked by `tests/test_docs_manifest.py` and
  `tests/test_docs_consistency.py`.
