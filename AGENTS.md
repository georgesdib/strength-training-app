# AGENTS.md — strength-training-app

Lean entry point for agents editing the Python server. Read the workspace-level
../AGENTS.md first, then the topic document for the task:

- docs/AGENT-WORKFLOWS.md — orientation, code layout, tests, documentation, CLI/UI parity.
- docs/AGENT-MIGRATIONS.md — append-only and schema/migration rules.
- docs/AGENT-DEBUGGING.md — logs, failure triage, data quarantine and long-running tests.

ROADMAP.md holds live phase status; docs/DECISIONS.md holds expensive-to-reverse
decisions. Do not duplicate either here.

Output discipline and high-risk approval rules are defined by the workspace `../AGENTS.md`.

## Authority

The server is authoritative for readiness, prescriptions, loads, sets, progression and
scoring. The LLM may explain or propose, never compute or veto the rules. The iOS client
must not define training policy.

## Branch

- Development happens on development, not main.
- Do not merge or push an integration branch without the owner's explicit instruction.
- Keep CI workflow files aligned with main; branch protection decides what runs.

## Guardrails — do not undo

- The constitution (docs/RULES-FORMAT.md, config/rules/) is the source of truth.
- Never let the LLM do arithmetic, invent thresholds, or override policy.
- Readiness is 1–5, higher is better; stress 5 means no stress.
- 0 is column-specific. Never apply a global sentinel rule.
- Prescriptions, critiques, calibrations and rule versions are append-only.
- Never deduplicate repeated training sets.
- Resolve unknown exercise names; never silently drop them.
- User goals, injuries and preferences are stored state, not prompt text.
- Empty/incomplete input yields unknown, never pass.
- Never read, commit or transmit data/, private/, real exports, health data, tokens or keys.
- The web UI is home-network only; never expose it publicly.
- Ask before changing a hard rule, threshold, data interpretation or migration.

## Definition of done — short form

1. Narrowest relevant tests pass; add a test that fails without the behaviour.
2. ruff check passes for the changed area.
3. New config has a domain-reason comment; judgement calls become assumptions.
4. Documentation is updated where behaviour changed; docs-consistency checks pass if docs changed.
5. Multi-statement writes use a transaction and leave no partial state.
6. Report only task, files, decisions, test status, risks and next action.

Detailed test recipes and documentation governance are in docs/AGENT-WORKFLOWS.md.
The docs index is docs/README.md and docs/manifest.yaml. Migration specifics are in
docs/AGENT-MIGRATIONS.md. Client-owned docs (plan, iPhone guide, device acceptance) live in
the sibling StrengthApp repository; server-owned iOS API contracts live in docs/design/.


### 9.2 Shared documentation ownership

The portfolio repository is canonical for shared project-wide plans, specifications, architecture, server/client contracts, cross-repository decisions and shared acceptance/operations policy. Start at https://github.com/georgesdib/strength-app/blob/main/docs/README.md and locate shared plans under `docs/plans/` and contracts under `docs/contracts/`. Do not copy those documents into this repository; old paths may contain concise compatibility pointers only.

This repository retains Python architecture, API/data-model implementation, schema/migration detail, backend-only tests, server operations and code-coupled docs. `ROADMAP.md` remains the canonical backend implementation-status source; do not create a competing portfolio status table. When backend implementation changes invalidate a shared requirement, update the portfolio canonical plan/contract and this repository's implementation docs/references in coordinated branches.
