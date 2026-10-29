# LLM INTEGRATION — FUTURE ARCHITECTURE AND PHASED PLAN

**Status:** proposed 2026-10-29. Documentation only: no runtime behaviour, prompt, API, schema,
dependency or training-rule changes are included in this plan.
**Roadmap workstream:** ROADMAP section 4.24.
**Owner:** the athlete. Phases 1 and 5 require explicit owner approval before implementation.
**Scope:** future analyst, programme-explainer and constrained workout-proposer capabilities,
their shared evidence/context layer, validation, approval, privacy and evaluation.

This document is a plan, not a claim that any described interface or capability exists. The
current implementation remains the source of truth until a phase is implemented and tested.

## 1. Current implementation (verified)

What exists today:

- strength_coach/agents/client.py — a text-in/text-out LLMClient protocol, NullLLM, and one
  OpenAI-compatible HTTP adapter. There are no tools, function calls, streaming or embeddings.
- strength_coach/agents/config.py — environment > git-ignored TOML > defaults; provider
  defaults to null; DeepSeek endpoint/model are defaults only after a provider is chosen; the
  key is masked in diagnostics.
- strength_coach/agents/narrative.py — critique and prescription prose from pre-computed
  facts. Output is a run_event, not a prescription or score; a raising client loses only prose.
- strength_coach/agents/selection.py — the minimal exercise-variant chooser. It receives
  already-filtered candidates and a one-line reason prompt; it may return only one of their
  exercise ids. Python validates the id and falls back deterministically.
- strength_coach/agents/proposal.py — a bounded structural proposal path: substitute, set
  sets, drop, reorder, choose a Python-computed menu option or set a listed rep scheme. It
  rejects load/RIR/percentage/velocity keys, rebuilds through the engine, and applies the same
  validators. It is CLI-only (run --propose; --yes for scripting).
- strength_coach/trace/ — one run row and ordered run_event rows; events include input,
  features, tool calls, LLM output, policy verdict and artifacts. run records input/config
  hashes, code version, model and tokens.
- The web UI exposes the optional Use LLM selection chooser and LLM settings. It has no
  analyst, explainer or proposer surface; the proposer remains CLI-only.

## 2. What is inadequate about the minimal selector

The selector is deliberately safe, but it is not an architecture for the three intended
capabilities:

1. It sees only the filtered candidates for one slot, not the athlete's current state, the
   prescription, recent training, prior selection history or the reason a previous choice
   changed.
2. Its output is one id and an unvalidated one-sentence reason. There is no evidence reference,
   no claim-level check and no report a user can inspect.
3. It has no prompt/schema/context version beyond the code itself, no structured validation
   record beyond the selection response, and no evaluation of whether its choices are better
   than the deterministic ranking.
4. It cannot explain a prescription, summarise progression or propose a workout. Those need
   different permissions and different context packages, not a larger version of the same
   prompt.
5. It is an optional choice inside a deterministic audit trail, not a general LLM service.

The deterministic selection engine, taxonomy, comparability classes, history and prescription
engine remain useful and stay. The selector LLM is scheduled for replacement, not immediate
removal.

## 3. Target capability boundaries

| Capability | May do | May not do | Output |
|---|---|---|---|
| **Athlete analyst** | Interpret a supplied, versioned context package; summarise progression, programme status and priority coverage; cite evidence ids | Choose exercises, change a prescription, calculate a value, assert a value not in context, present a heuristic as validated | Structured report with prose sections, claim/evidence links and data-quality limitations |
| **Programme explainer** | Explain a persisted prescription and its actual decision trace; compare with the baseline/previous; state uncertainty | Invent a rationale, claim optimality, suggest a change as though already applied, alter the prescription | Concise explanation plus expandable detail, with evidence refs |
| **Constrained proposer** | Propose bounded structural changes using canonical ids and allowed choices; state intent, trade-offs and uncertainties | Supply bar weights, RIR numbers, percentages, velocity targets, safety vetoes, arbitrary exercise ids or an unauthorised template change | Structured proposal; Python resolves loads, validates and, only after explicit approval, creates a new prescription |

### Permissions matrix

| Operation | Analyst | Explainer | Proposer | Deterministic core |
|---|---:|---:|---:|---:|
| Read versioned context/evidence | yes | yes | yes | provides it |
| Write to database directly | no | no | no | yes, through existing repositories |
| Calculate e1RM/load/volume/spinal cost | no | no | no | yes |
| Choose a canonical exercise id | no | no | only from the supplied allowed set | validates/rebuilds |
| Veto a rule or constraint | no | no | no | yes |
| Rebuild/validate a prescription | no | no | no | yes |
| Approve a proposal | no | no | no | user, through the UI/CLI |
| Persist accepted prescription | no | no | no | yes, append-only |

The same model client may serve all three, but the capability prompt, context contract, output
schema and validator are separate. A single do-anything prompt is out of scope.

## 4. Shared context and evidence layer

### 4.1 Deterministic builder

Create one Python-owned AthleteContextBuilder (future path:
strength_coach/agents/context.py) used by every capability. It must not call an LLM. It
assembles facts from existing functions and stores a canonical JSON package plus a hash.

Required top-level fields:

- schema_version and builder_version.
- capability and as_of date.
- athlete: goals, priorities, constraints, injuries, symptoms, suitability, equipment/schedule
  facts that are actually stored.
- programme: block context, current prescription id/session type, rolling schedule, volume
  allocation and relevant rule/assumption ids.
- lifts: per-lift summaries, tested maxima versus estimated e1RM, comparison windows,
  observation counts, data-quality flags, RIR/velocity/volume summaries.
- sessions: recent relevant sessions and working-set summaries, selected by a documented
  relevance rule; not an arbitrary sample and not the whole database.
- readiness and symptoms: scored/available state and unknowns.
- prescription: the deterministic baseline and its actual modifiers/warnings when the
  capability is the explainer or proposer.
- allowed: canonical exercise ids/slots/schemes/menus available to a proposer.
- evidence: the evidence registry described below.
- data_quality: missingness, low-n windows, legacy values, calibration coverage and
  uncertainty.
- privacy: the redaction policy applied and any omitted sections.

### 4.2 Relevance-based history

Do not send the entire database. The default selection is:

1. Current athlete state, current constraints and current prescription.
2. The last N relevant sessions (provisional N = 8–12, configurable) with working sets and
   session feedback.
3. Per-lift long-window summaries (28 and 84 days) and sufficient historical observations for
   the comparison being discussed.
4. Earlier exposures only when the selected lift, rule, symptom or proposal needs them; record
   why they were included.
5. No arbitrary random sample. Deterministic ordering and a source_counts manifest.

The builder records truncated_sections and a token estimate. Truncation priority is explicit:
current safety/constraints and the capability's actual question cannot be truncated; older
context may be.

### 4.3 Evidence registry

Each material fact gets a stable evidence id, for example:

    {
      "evidence_id": "ev:lift:bench_press:e1rm:2026-10-28",
      "source": "e1rm_calibration",
      "source_ids": ["..."],
      "window": {"start": "2026-07-31", "end": "2026-10-28"},
      "calculation": "28-day median; RIR-adjusted Epley",
      "value": 102.5,
      "unit": "kg",
      "quality": "estimated; n=4; formula bias unresolved",
      "rule_ids": ["DEC-E1RM-SOURCE-01"],
      "assumption_ids": ["ASSUMPTION-..."]
    }

The exact field names are fixed in Phase 1. Rules:

- Evidence ids are deterministic for the same source rows and window; a changed context changes
  the hash and the ids.
- A claim without evidence is allowed only for clearly labelled interpretation ("this may
  suggest") and must be marked as such.
- The UI can expand a claim to its evidence; the CLI can print the same references.
- The evidence registry is built from existing feature/repository functions. The LLM never
  supplies an evidence object.

### 4.4 Versioning and hashing

- Context: context.version, builder.version, canonical JSON hash.
- Prompt: prompt.id, prompt.version.
- Output: schema.id, schema.version.
- Model: provider/model id, temperature, max tokens and timeout.
- Validation: validator version and result.

These fields are written into the existing run/run_event payloads; no schema change is
required for the first phases. If proposal/report querying later needs a dedicated table, that
is a separate, additive migration decision (Phase 4/5), not part of this plan.

## 5. Capability A — Athlete analyst

### 5.1 Reports

1. **Lift-specific progression** — e1RM/test distinction, comparison windows, load/reps/RIR/VBT
   trends, exposure/volume, data sufficiency and a progress/plateau/inconclusive verdict.
2. **Overall programme status** — adherence vs intended frequency, main-lift and pattern
   progression, volume distribution, readiness/symptom/deload history, recent modifiers and
   missing data.
3. **Strength, power and longevity review** — priority alignment, coverage gaps and questions
   for review; never a clinical claim or a promise that a change improves longevity.

### 5.2 Contract

The analyst returns structured prose, not free-form only:

    {
      "schema_version": "llm.analysis.v1",
      "report_type": "lift_progression",
      "as_of": "2026-10-28",
      "summary": "...",
      "sections": [
        {
          "heading": "Bench press",
          "text": "...",
          "claims": [
            {"claim_id": "c1", "text": "...", "evidence_refs": ["ev:..."],
             "strength": "supported|suggestive|inconclusive"}
          ]
        }
      ],
      "limitations": ["..."],
      "data_quality": ["..."]
    }

Validation rejects unknown report types, missing evidence for a supported claim, evidence ids
not in the context, and any numeric token that does not appear in the supplied facts. The prompt
must say that an unchanged estimate is not a plateau, a calculated e1RM is not a tested maximum,
and missing data is unknown rather than zero.

### 5.3 UI/CLI

Read-only. A report is generated only on an explicit request, never automatically on page load.
The UI uses a panel with report type, as-of date, concise summary, expandable sections and
evidence links. The CLI exposes the same report type and writes the same trace. The
deterministic data tables remain available when the LLM is disabled.

## 6. Capability B — Programme explainer

### 6.1 Inputs

The persisted prescription, its item ids, rule refs, modifier provenance, warnings, unknown
inputs, and the actual candidate alternatives only if the engine evaluated them. It may use the
same context package as the analyst, restricted to the relevant dates.

### 6.2 Output

    {
      "schema_version": "llm.explanation.v1",
      "prescription_id": "...",
      "concise": "...",
      "detailed": "...",
      "why_selected": [{"text": "...", "evidence_refs": ["..."]}],
      "changes": [{"text": "...", "evidence_refs": ["..."]}],
      "uncertainties": ["..."]
    }

It must distinguish (1) why the session was selected, (2) what changed from baseline/previous,
(3) which constraint/modifier caused it and (4) what remains uncertain or heuristic. It may not
invent a rationale not present in the trace and may not claim an exercise is optimal.

### 6.3 UI

- A concise explanation in the Workflow preview, below the deterministic prescription.
- An expandable evidence/detail section, not a wall of prose.
- No effect on Start workout; the deterministic plan remains the thing committed.
- CLI equivalent; no new persistence artifact initially; the explanation is a run_event tied to
  the prescription.

## 7. Capability C — Constrained workout proposer

### 7.1 Context

The proposer uses the same context builder plus the deterministic baseline, allowed template
slots, allowed replacement ids, allowed schemes/menus and the hard constraints. The baseline is
always present and displayed as the alternative.

### 7.2 Proposal schema

The schema extends the existing structured proposal rather than creating a second pathway. No
free-form prescription text is parsed as an instruction. Proposed shape:

    {
      "schema_version": "llm.proposal.v1",
      "base_prescription_id": "...",
      "intent": "session_goal_id",
      "summary": "...",
      "changes": [
        {"action": "substitute", "slot_id": "...", "exercise": "...", "with": "..."},
        {"action": "set_sets", "exercise": "...", "sets": 4},
        {"action": "set_scheme", "exercise": "...", "scheme": "allowed_scheme_id"},
        {"action": "drop", "exercise": "..."},
        {"action": "reorder", "order": ["..."]},
        {"action": "choose", "exercise": "...", "option": "easier|harder|heavier|lighter|keep"}
      ],
      "evidence_refs": ["ev:..."],
      "tradeoffs": ["..."],
      "uncertainties": ["..."]
    }

Rules:

- Exercise ids must be canonical and in the allowed set for that slot.
- Set counts are bounded by the template/rule and are re-clamped by Python.
- Rep/effort choices are enum/menu ids, not raw RIR or velocity numbers. The existing
  DEC-LLM-05 menu principle is retained.
- Any load, weight, RIR, percentage, velocity or unknown numeric key is rejected before parsing.
- Missing/extra keys, unknown actions and unknown slots are rejected.
- Evidence refs must exist in the context; unsupported claims are not accepted.
- The model does not see the entire database and cannot query it.

### 7.3 Validation and approval pipeline

1. Build the deterministic context and baseline.
2. Call the proposer with the versioned prompt/schema.
3. Parse and validate the schema; reject numeric/unknown fields.
4. Check canonical ids, allowed actions, slot/template compatibility and athlete constraints.
5. Rebuild the affected items with the existing engine; solve loads in Python.
6. Run the same prescription/safety validators, constraint checks and hard-rule checks.
7. On any failure, keep the deterministic baseline and record the rejection reason.
8. Show baseline and proposal side by side with a diff, evidence, trade-offs and uncertainties.
9. Require explicit user approval (checkbox/button; no default accept).
10. Persist the accepted prescription and provenance append-only, using the existing model.
    The raw proposal remains an event/record; it is never itself the prescription.

Initial rollout is **shadow only** (generate, validate, record, do not present or apply), then
**opt-in approval** (show and require acceptance), then only after the evidence gates in section
9 may the owner consider broader use. Automatic replacement is out of scope permanently for
this workstream unless a separate decision changes it.

Preserve the existing safety restriction from DEC-LLM-04: do not propose on a session already
downgraded by a safety modifier. Any future relaxation requires a new decision and evidence.

## 8. Technical integration

- **Layering:** new code stays in agents/ (prompt/context/capability orchestration) and calls
  existing features/, prescribe/, store/ and trace/ functions. The deterministic layers must not
  import agents.
- **Contracts:** ContextPackage, Evidence, AnalysisReport, Explanation, WorkoutProposal,
  ValidationResult and capability/permission enums. Typed dataclasses or explicit validators; no
  clever metaprogramming.
- **Client:** reuse the existing LLMClient/OpenAI-compatible adapter. Do not add a provider or
  library unless a concrete need appears. No tool/function-calling requirement is established;
  structured JSON in the response is sufficient.
- **Trace:** every call opens a run with input_hash = context hash, config_hash = prompt/schema/
  config hash, llm_model, and emits input, llm_output, policy_verdict and artifact events as
  appropriate. Store the prompt id/version, context hash, schema version, provider/model,
  temperature, tokens and validation result in payloads. Reuse run_event payloads; no schema
  change is required for Phases 1–4.
- **Failure:** NullLLM, timeout, malformed JSON, invalid ids, unknown evidence, provider error
  and schema mismatch all return to the deterministic path. The UI must say that the
  deterministic plan/report is being used and why. No silent retry that changes the answer.
- **Latency/cost:** explicit user action; one request at a time; configurable timeout; bounded
  context and max tokens; no background calls; report context token estimate. Cache only by
  context/prompt/model hash and make the cache transport/local, not a training artifact.
- **Privacy:** minimise the payload; do not send raw free-text notes by default, and never send
  API keys or unrelated history. Keep full context in the local database; log hashes and
  metadata, not prompt bodies, by default. Document which fields are redacted. A future remote
  or multi-user deployment needs the auth/privacy work in ROADMAP section 4.19 first.
- **UI/CLI parity:** each capability gets both interfaces, or a documented exception in
  docs/UI-CLI-PARITY.md. Analyst/explainer are read-only; proposer approval is explicit in both.
  The iPhone UI uses cards/disclosures and cannot start a proposal automatically.
- **Retirement:** Phase 1 marks agents/selection.py deprecated in documentation. It is not
  removed until the replacement capabilities pass their gates (Phase 5). The deterministic
  selection engine and its comparability/taxonomy rules remain.

## 9. Evaluation and controlled rollout

| Dimension | Requirement |
|---|---|
| Safety | Accepted proposals never violate a hard constraint, rule or template; validation failures fall back |
| Programme coherence | Priority alignment, exercise comparability, volume allocation, continuity and template compatibility |
| Practical usefulness | Acceptance, edits, rejection reasons, time saved, explicit feedback |
| Factual reliability | Numeric claims match source records; evidence refs resolve; no invented rule ids |
| Training outcomes | Predefined prospective performance, adherence and symptom outcomes where available |

Record context/prompt/schema versions, model/config, baseline, proposal, validation/rejection
reasons, accepted prescription, user edits and subsequent outcomes, subject to privacy.

Rollout gates, provisional and owner-approved before Phase 5:

1. **Shadow:** zero hard-constraint violations; all proposals schema-valid or rejected with a
   reason; evidence refs resolve; deterministic baseline unchanged.
2. **Opt-in:** no safety failures in accepted proposals; user can inspect the diff; decline and
   fallback work; factual checks pass on a sampled set.
3. **Broader use:** only after the owner reviews prospective outcomes and usefulness. A high
   acceptance rate is not evidence of better coaching; observational outcomes are not causal.

No phase is allowed to increase autonomy without explicit owner approval of the gate results.

## 10. Phases

These are dependency-ordered, not date-ordered. The workstream starts after the v1.1
cardio/calibration priorities unless the owner reprioritises it. Each phase is separately
shippable; no phase may silently produce the next phase's capability.

### Phase 1 — Architecture and contracts (planning/implementation gate)

- **Scope:** approve the capability boundaries, permissions, context/evidence schema, prompt/
  schema/version contracts, privacy policy, evaluation definitions and the selector-deprecation
  plan. Define interfaces and the migration-free trace payloads.
- **Non-goals:** no analyst/explainer/proposer runtime, no prompt calls, no UI, no selector
  removal, no schema change.
- **Dependencies:** owner approval; no current v1.1 work is a hard dependency.
- **Expected code/docs:** this document, ROADMAP section 4.24, new DEC-LLM-07..11, future
  agents/context.py/contracts. No source change.
- **Acceptance:** owner signs off the decisions; interfaces and schemas are reviewable; no
  unresolved blocking design question.
- **Tests:** documentation consistency only; no runtime tests claimed.
- **Data/schema:** none. Reuse run/run_event; candidate tables deferred.
- **Safety/privacy:** permission matrix and privacy policy approved.
- **Exit:** approved contracts; proceed to Phase 2.

### Phase 2 — Shared context builder and athlete analyst

- **Scope:** deterministic context/evidence builder; analyst lift-progression and
  programme-status reports (and the strength/power/longevity review if the first two pass).
  Read-only CLI/API/UI.
- **Non-goals:** explainer, proposer, selection retirement, autonomous actions.
- **Dependencies:** Phase 1; existing features/readiness/outcomes/volume code.
- **Expected code/docs:** agents/context.py, agents/analyst.py, feature query helpers,
  API/CLI/UI, tests; update this plan and ROADMAP.
- **Acceptance:** deterministic context hash; every supported claim has evidence; e1RM/test and
  plateau/inconclusive distinctions are correct; missing data is unknown; LLM-off path still
  shows deterministic data; no numerical invention.
- **Tests:** context determinism/hash, relevance selection, evidence links, comparison windows,
  prompt injection, forbidden numeric invention, malformed output, provider failure, UI/CLI.
- **Data/schema:** none; run/run_event payloads.
- **Safety/privacy:** read-only; minimal context; no raw notes by default.
- **Exit:** owner review of sample reports; zero factual/evidence defects in the sampled set.

### Phase 3 — Programme explainer

- **Scope:** evidence-linked concise/detailed explanations of actual persisted prescriptions,
  modifiers and warnings; Workflow and CLI.
- **Non-goals:** analysis reports beyond the explainer, proposals, changing the prescription.
- **Dependencies:** Phase 2 context/evidence; existing prescription provenance and rule trace.
- **Expected code/docs:** agents/explainer.py, UI preview, CLI, tests; update plan/roadmap.
- **Acceptance:** explanation matches the stored prescription; distinguishes selected, changed
  and uncertain; no invented rationale; evidence resolves; deterministic explanation remains
  when LLM off.
- **Tests:** fixtures for no modifier/readiness/deload/constraint/unknown input; hallucinated
  rules/ids; numeric mismatch; timeout; UI/CLI.
- **Data/schema:** none; explanation is a run_event linked to the prescription.
- **Safety/privacy:** read-only; no Start-workout effect.
- **Exit:** owner review; no misleading explanations in the sample.

### Phase 4 — Constrained proposer in shadow

- **Scope:** structured proposal schema, validation pipeline, Python load resolution, baseline
  comparison, shadow recording. No user-facing application or approval.
- **Non-goals:** automatic replacement; UI approval; selector removal; broader autonomy.
- **Dependencies:** Phases 1–3; existing agents/proposal.py, prescription engine, validators,
  trace.
- **Expected code/docs:** evolve agents/proposal.py (do not create a duplicate pathway),
  validators, shadow command/API, tests; update plan/roadmap.
- **Acceptance:** schema rejects numbers/unknown ids/unauthorised changes; Python resolves all
  loads; hard constraints and template compatibility checked; invalid proposals fall back;
  baseline always present; shadow records complete.
- **Tests:** adversarial numbers/ids, malformed JSON, unknown slots, constraint/safety
  violations, timeout, LLM-off equivalence, deterministic baseline regression.
- **Data/schema:** none required initially; run/run_event stores proposal and verdicts. A
  dedicated query table is permitted only if evaluation proves it necessary, with a separate
  additive migration decision.
- **Safety/privacy:** shadow only; no writes to prescriptions; same privacy rules.
- **Exit:** owner-approved shadow gate from section 9; proceed to opt-in.

### Phase 5 — Opt-in approval, evaluation and selector retirement

- **Scope:** baseline/proposal diff, explicit approval in UI/CLI, accepted artifact persistence,
  feedback capture, controlled opt-in, selector decommission after replacement passes.
- **Non-goals:** autonomous replacement; training-rule changes; expanding to remote/multi-user
  without auth/privacy work.
- **Dependencies:** Phase 4 gates; owner approval; UI/CLI parity; privacy review.
- **Expected code/docs:** approval UI/API/CLI, prescription provenance, feedback/evaluation
  report, remove minimal selector path after evidence; update ROADMAP/DECISIONS/UI parity.
- **Acceptance:** explicit approval required; no default accept; deterministic baseline visible;
  rejected/invalid proposals never commit; accepted artifact append-only; acceptance/edit/
  rejection/outcome evidence recorded; selector removed only after the replacement gate.
- **Tests:** approval/decline, invalid proposal, timeout/fallback, LLM off, UI/CLI, privacy
  redaction, adversarial prompt injection, full regression and golden prescriptions.
- **Data/schema:** existing append-only prescription/run_event; any additional evaluation table
  is a separate additive decision.
- **Safety/privacy:** explicit approval; no autonomous writes; auth/privacy review before remote
  use.
- **Exit:** owner reviews prospective outcomes and gate results; a new decision is required
  before any autonomy beyond opt-in approval.

## 11. Expected repository areas (future; not implemented now)

| Area | Future responsibility |
|---|---|
| agents/context.py | deterministic context/evidence builder and hash/version |
| agents/contracts.py (or equivalent) | typed capability/permission/output contracts and validators |
| agents/analyst.py | analyst prompt/call/validation orchestration |
| agents/explainer.py | prescription explanation prompt/call/validation |
| agents/proposal.py | extend the existing structured proposal path; do not fork it |
| features/, prescribe/ | facts/validation reused; no agent imports; no new calculations in agents |
| store/, trace/ | provenance and append-only records; schema changes only by separate decision |
| web/, cli.py | read-only reports/explanations; approval flow in Phase 5; parity |
| tests/ | contract, adversarial, fallback, UI/CLI and regression coverage |

## 12. Relationship to existing decisions

- DEC-LLM-01 remains: raw model output is a run_event, not an artifact. An approved proposal is
  a rebuilt deterministic prescription with provenance, not the model text.
- DEC-LLM-04 remains: structural edits are rebuilt and validated; computed-number keys are
  rejected; safety-downgraded sessions are closed to proposals.
- DEC-LLM-05 remains: menu choices are Python-computed; the model may choose, not calculate.
- DEC-LLM-06 remains: essential/main-lift substitutions keep their explicit rules.
- DEC-SELECT-* and the deterministic selection engine remain; only the minimal selector LLM
  path is scheduled for retirement.
- New decisions DEC-LLM-07..11 record this future direction; they do not change current
  behaviour.

## 13. Owner decisions required before implementation

1. **Provider/privacy tier:** is the configured external provider allowed to receive the
   minimal structured context, or must analyst/explainer run only against a local model for
   notes/symptoms? Default: minimal structured data only; exclude free-text notes unless opted
   in.
2. **Persistence:** should analyst/explainer reports be ephemeral UI/CLI results, or append-only
   local artifacts for later comparison? Default: run_event/local cache first; no new artifact
   table.
3. **Proposal gates:** approve the provisional shadow/opt-in thresholds in section 9 before
   Phase 5.
4. **Approval UX:** whether the proposer is a side-by-side panel in Workflow, a separate
   Suggest workout action, or both. Default: side-by-side baseline/proposal in Workflow with
   explicit approval; no new page.
5. **Selector retirement:** confirm that the deterministic selection engine remains and only
   the minimal LLM chooser is removed after Phase 5. Default: yes.

## 14. Documentation discrepancies and resolutions

The review found four documentation/implementation mismatches worth recording:

- **ARCHITECTURE.md** said computed numbers arrive by tool call. The current client is
  text-in/text-out and has no tool protocol. The text now says numbers are supplied facts or
  Python-computed menus, and a future tool call would only be another transport for the same
  Python-owned value.
- **AGENTS.md** invariant 2 used the same tool-call wording. It now states that the transport
  may be facts, a menu or a future tool call; the invariant is that Python owns the number.
- **V0-SCOPE.md** describes the original v0 LLM interface only; it is a historical scope record
  and is not being rewritten. Section 1 of this plan records the current capabilities.
- **WEB-UI.md / UI-CLI-PARITY.md** correctly said proposals are CLI-only today. They now also
  point to this plan's future surfaces, while explicitly retaining the current limitation.

No historical decision is edited or silently superseded. DEC-LLM-01, DEC-LLM-04, DEC-LLM-05
and DEC-LLM-06 continue to govern current behaviour; DEC-LLM-07..11 describe the future intent.

## 15. Definition of done for this planning task

- This plan and the ROADMAP workstream exist and agree.
- New decisions are appended; no historical decision is overwritten.
- Current runtime, prompts, API, schema, dependencies and training rules are unchanged.
- No test claims cover unimplemented capabilities.
