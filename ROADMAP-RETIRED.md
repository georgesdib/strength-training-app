# ROADMAP — retired and decided-against work

This is the retired half of the roadmap. It records work that was **retired, withdrawn or
explicitly decided against**, with the decision and date where one exists. It is an audit
record, not a to-do list: reopening any item needs a new owner decision, not a revived plan.
Completed work remains in [ROADMAP-DONE.md](ROADMAP-DONE.md); open and future work is in
[ROADMAP.md](ROADMAP.md).

Section numbers are preserved so older references still resolve.

---

## 1. Register

- **Rubric scoring, the backtest harness and the labelled calibration set** — retired
  2026-11-13 (`DEC-EVAL-09`). No session is scored; historical rows stay read-only. See §4.14
  and `ROADMAP-DONE.md` §4.23.
- **Video analysis** — descoped. The post-lift form assessment replaced it; see §3.5.
- **Manual cardio logging and the cardio impulse/fatigue model** — manual capture removed
  2026-11-17; the impulse, shadow load and model decision retired 2026-11-18
  (`DEC-LONGEVITY-03`). See §4.13 and §4.13a.
- **LLM constrained proposer / any model write path** — withdrawn 2026-11-17
  (`DEC-LLM-09`); PCC (INT-4c) withdrawn 2026-11-24; web search/RAG and the vector store
  (INT-12) withdrawn 2026-11-24. Any revival needs a new decision. See §4.24 and the retired
  iterations below.
- **Parent-variant repeated-pair e1RM profile** — closed 2026-11-25. The descriptive display
  remains; the repeated-pair profile with an uncertainty band is not pursued. See §4.20.2.
- **Main-lift upward-revision ratchet** — closed 2026-11-24. It was rejected as a controller in
  `DEC-E1RM-PLAUS-01`; the display-only plausibility advisory remains. See §4.19 history.
- **Web authentication and per-user data** — not pursued (`DEC-WEB-03`/`DEC-WEB-04`); the
  server stays a single-user home-LAN tool. See §4.19 history.
- **Grip-strength readiness input** — rejected (`DEC-GRIP-01`); grip remains a periodic
  measurement. See §6.1.
- **Learned readiness weights** — evaluated and closed; the fixed weights remain. See
  `ROADMAP-DONE.md` §4.9.
- **Per-lift readiness validation** — closed 2026-11-25 as a design choice (`LIM-62`,
  `DEC-LIFT-READY-01`): the downward-only score is accepted as a second opinion behind the global
  score, not a validation target. See §4.9.6.
- **Continuity calibrated factor** — rejected; the fixed fallback remains. See
  `ROADMAP-DONE.md` §4.12.
- **Strength fitness-fatigue model adoption** — retrospective validation rejected; the model
  stays shadow-only/descriptive. See `ROADMAP-DONE.md` §4.16.
- **Column-mapping adapters for other exports** — closed 2026-10-23, not needed; see §4.3.
- **Nicer UI placeholder** — retired 2026-11-13; UI polish shipped in P0–P3 and the remaining
  adherence scope moved to AFC. See §4.23.
- **Per-lift velocity override with expiry** — dropped; per-set/per-rep overrides were
  delivered instead. See `ROADMAP-DONE.md` §6.1 history.
- **Deeper labelled calibration set** — retired with the rubric (`DEC-EVAL-09`).
- **LLM proposal view / minimal exercise selector** — the CLI-only proposal view was closed and
  the minimal selector was retired in Phase 1b; the deterministic selector remains. See
  `ROADMAP-DONE.md` §4.11.

## 2. Moved from ROADMAP-DONE.md

The sections below were retired items that had been archived with completed work. Their
headings and numbers are unchanged.

### 3.5 Video analysis — descoped

Video capture and vision-model commentary are not planned. The post-lift form assessment in
§4.8 is the replacement, and it stores no video.

### 3.9 Deliberately not planned

- A UI (deferred by request).
- Several athletes in one database, or a hosted service: local-first, one database per person
  (3.6 covers portability; video is descoped).
- RAG over the programme: rules are cited by id, and exact lookup beats semantic search here.
- Automatic rubric retuning: the report proposes, a person decides.

### 4.3 Column-mapping adapters for other exports  (CLOSED 2026-10-23 — not needed)

**Status: closed.** The standard dated training export is the backfill path, and the workout
CSV is imported in-workout. No additional adapter registry is needed. Unknown exercise names are
still reported/quarantined, and extra raw columns remain in `raw_row`; neither justifies a second
mapping layer.

### 4.9.6 Per-lift readiness validation  (closed 2026-11-25 — accepted as a design choice; moved 2026-11-26)

**Status: closed, not planned.** The per-lift score is implemented and downward-only
(`DEC-LIFT-READY-01`). On 2026-11-25 it was accepted as a transparent second opinion behind the
global score and the category overrides, not a validated instrument, and `LIM-62` closed as a
design choice. Validation is therefore **not planned**: a lift-specific pre-session rating, a
fixed-load velocity check, more measured e1RM tests and a prospective outcome test would all be
needed, and [`docs/LIFT-READINESS.md`](docs/LIFT-READINESS.md) §6 records them as an explicit option
rather than a schedule. Reopening needs a new owner decision, not a revived roadmap item.

The policy is unchanged: the score can only lower a lift's load, never raise it, and never replaces
the global readiness score or a category override.

### 4.14 Labelled calibration set  (retired 2026-11-13; `DEC-EVAL-09`)

No code. **Retired since 2026-11-13** (`DEC-EVAL-08` dormant loop, `DEC-EVAL-09` removal): the
rubric no longer scores a session, the `rubric_labels` review prompt is gone, and AFC is the
canonical post-workout adherence evaluation. The historical sample below stays readable and
nothing is rewritten or deleted. The loop previously aimed at roughly ten *remembered* sessions
per item before changing a definition or weight (DEC-EVAL-03, DEC-EVAL-04); reconstructed marks
stay stored but excluded from agreement.

Current state (2026-11-07): **12 high-confidence reviewed sessions**, every rubric item has a
mark; **61 comparable items, 84% agreement, MAE 0.12**. RIR 9/89%, weekly spinal 12/92%,
redundancy 12/92%, rotation 11/64%, form 11/100%; essential work 4/25%, duration 2, progression 0,
velocity loss 0. **B1 review closed 2026-11-07**: rotation is a definitional split
(app-assigned labels score neutral), essential work is coverage-limited (imports without a
snapshot), and no rubric weight or definition is changed. See
[`docs/RUBRIC-CALIBRATION.md`](docs/RUBRIC-CALIBRATION.md).

**Next action (2026-11-13):** none. The engine and its tooling are removed, no marks are
requested and no B3 decision is pending; B2/B3 stay gated to the 2027-01-22 review and no rubric
retune is planned before it. `GET /api/review/<session>` still renders the stored rows. Reviving
the loop would be a new decision, not a re-enable of removed code.

Acceptance: the B1/B2/B3 gate — a pre-declared review and enough comparable observations per
targeted item before a rubric change; every review appends, never edits; the report states the
sample size and excludes low-confidence marks.

### 4.23 Nicer UI, adherence encouragement and KPIs  (retired 2026-11-13; scope moved to §4.33)

**Status:** closed as a placeholder. It never had an implementation date or an approved design.

Its two halves did not belong together:

- **UI polish** was delivered by the P0–P3 UI redesign, which closed on 2026-11-06
  (`docs/archive/UI-DESIGN-IMPLEMENTATION-PLAN.md`). It is no longer open work.
- **Adherence encouragement, gentle nudges and the KPI panel** are now AFC-4, composed from metrics
  that already exist. The planned-vs-completed and skipped-session items are **not** carried over:
  `DEC-W7-01` keeps attendance target-based and no planned-session calendar is stored.

Design reference retained for history: [`docs/archive/UI-IMPROVEMENT-PLAN.md`](docs/archive/UI-IMPROVEMENT-PLAN.md).
Canonical AFC scope: §4.33 and [`AFC plan`](https://github.com/georgesdib/strength-app/blob/main/docs/plans/AFC.md).

## 3. Moved from ROADMAP.md

The sections below were removed from the live roadmap on 2026-11-25. Delivered phases are
summarised in `ROADMAP-DONE.md` §8; the retired plans and decisions are kept here.

### 4.13 Cardio workouts and an impulse fatigue model  (capture v0.2 done; cardio model v1.5; strength model is §4.16)

**Capture retired 2026-11-17.** Manual cardio logging (`cardio_log`, the web form, the `cardio` CLI
command) was removed in favour of the imported corpus; the portfolio cardio stage plan is the
canonical account and closed on 2026-11-18 at release 1.6.0. That stage deferred the web
time-in-zone chart and HealthKit deletion detection (replaced by hiding a workout); its test debt is
recorded there. The impulse item below was retired on 2026-11-18 (`DEC-LONGEVITY-03`); the
[longevity assessment plan](https://github.com/georgesdib/strength-app/blob/development/docs/plans/LONGEVITY-ASSESSMENT.md) replaces it with sample-based time-in-zone,
which adds no load model.

The app currently measures resistance training only. Cardio is a separate exposure with a
different fatigue signature, and a single "fatigue score" would hide that. This item adds the
data and a model, initially advisory and in shadow mode.

**Delivered 2026-10-20 and superseded 2026-11-17.** The first cut was an append-only `cardio_log`
with a `cardio` CLI command and `GET/POST /api/cardio`. It never held a row, and the imported
corpus replaced it: `cardio_log`, the command, the routes and the form are gone (`0069`), the
longevity review reads the corpus, and hiding a workout replaces manual correction. The model below
was never built and was retired on 2026-11-18 (`DEC-LONGEVITY-03`); no prescription reads cardio
data.

**Priority:** the longevity review ranks cardio capture as the largest gap between the
programme and the primary goal — cardiorespiratory fitness is the strongest modifiable
mortality signal, and the app currently records none of it
([`docs/LONGEVITY-REVIEW.md`](docs/LONGEVITY-REVIEW.md)). Capture is useful before the fatigue
model exists; the model stays shadow-mode until there is data.

**Scope**

1. **Cardio capture** — modality, duration, average/max HR, HR zones, distance or power where
   available, session RPE, notes. Append-only; no free-text parsing in the core.
   **Done (migration 0011):** modality, duration, average/max HR, distance and sRPE; HR zones
   and power are not captured yet.
2. **Training impulse** — compute a documented impulse per session: HR-based TRIMP where the
   data supports it, otherwise session-RPE × duration. Say which one was used and why.
3. **Fatigue model** — start with an impulse-response / fitness-fatigue model:
   - a fitness (positive, slow-decaying) and fatigue (negative, faster-decaying) term;
   - at least two systems: cardiovascular and neuromuscular/spinal, rather than one global
     impulse;
   - time constants and weights are config, per athlete when enough data exists;
   - the model reports a **fatigue state**, not a diagnosis.
4. **Interaction with the existing layers** — cardio fatigue may inform readiness and load
   selection, but it must not override constraints, the injury signal or readiness overrides.
   Cardio that loads the knees/low back must be linked to the injury regions so it is not
   invisible exposure. Avoid double-counting the same session as both resistance and cardio.
5. **Shadow first** — compute and display the impulse and fatigue state for weeks without
   changing a prescription. Only then consider a load/RIR effect.

**Evidence and limits**

- The Banister impulse-response model relates training impulses to performance, but its
  parameters are ill-conditioned and unstable; a good fit does not make the parameters
  identifiable ([Hellard 2006](https://doi.org/10.1080/02640410500244897)).
- A single impulse reduces different training types to one number; the proposed
  three-dimensional model separates energy-system-specific adaptation, which is the direction
  this item should take rather than one global fatigue scalar
  ([Kontro 2026](https://doi.org/10.1371/journal.pone.0341721)).
- HRV, sRPE and subjective wellness can be inputs to an impulse-response model, but the
  relationships are not a validated individual prescription
  ([Piatrikova 2021](https://doi.org/10.1123/ijspp.2020-0201)).
- Fitness-fatigue models need longitudinal individual data; a generic parameter set is a
  prior, not a measurement ([Wang 2025](https://doi.org/10.1371/journal.pone.0337824)).

**Open questions (historical — the item was retired 2026-11-18; none of these is live)**

1. Which cardio modalities are in scope (walking, cycling, rowing, running, intervals)?
2. Is TRIMP available from the athlete's devices, or is sRPE the only usable impulse?
3. Should the model have two systems (cardio/neuromuscular) or three (add metabolic/energy
   system), and how do they interact?
4. Do cardio sessions link to injury regions by pattern (e.g. running → knee) or only by
   explicit tags?
5. Does fatigue modify load, RIR, volume or only the displayed readiness context?
6. How many weeks of data before an individual time constant is shown?
7. Can a cardio session count as readiness/load evidence without a symptom follow-up?

**Acceptance**

A cardio session can be recorded and cited; its impulse is reproducible and labelled by
method; the fatigue state is displayed with inputs and time constants; a shadow period changes
no prescription; constraints and injury ceilings remain vetoes; no cardio session silently
counts as resistance volume or vice versa.

**Note:** A0, A1, B0 and B1 were delivered and are recorded in `ROADMAP-DONE.md` §4.13a; the phases below were retired.

### 4.13a v1.6 plan — cardio depth  (deferred from v1.2; approved 2026-10-25)

**Goal:** make cardio a first-class, reproducible exposure; add only a shadow cardio-load
context; and deepen calibration enough to decide whether any rubric definition should change.
No automatic cardio load effect and no parent-variant/weakness implementation in this phase.

**Status 2026-11-18 — A0 and A1 are delivered; the impulse stays here.** The A0 data audit is measured and
published in the portfolio cardio stage plan
([C0 audit](https://github.com/georgesdib/strength-app/blob/development/docs/plans/CARDIO-C0-AUDIT.md),
[plan](https://github.com/georgesdib/strength-app/blob/development/docs/plans/CARDIO-STAGE.md)): 1,431
HealthKit workouts, 546 k usable HR samples, 320 of 378 sessions with a single same-day workout
candidate, and exactly one historical exact identifier. Capture completion (A1) shipped with that stage,
which closed on 2026-11-18 at release 1.6.0. The impulse/shadow load (A2/A3) and the model decision
(A4) were **retired the same day** (`DEC-LONGEVITY-03`): TRIMP, sRPE impulse, acute:chronic ratios
and unified fatigue scores are closed as product direction, and A5 (interaction review) follows them.
The replacement is the [longevity assessment plan](https://github.com/georgesdib/strength-app/blob/development/docs/plans/LONGEVITY-ASSESSMENT.md): deterministic aerobic adequacy, VO₂max
status and per-pattern headroom, with sample-based time-in-zone as the only new cardio computation.
Nothing reads cardio data to change a prescription.

**Principles**

1. Capture and data quality before modelling.
2. Impulse must be reproducible and labelled by method.
3. Cardio and strength fatigue stay separate; no single global fatigue scalar.
4. Shadow first; a model may not change a load, RIR, set or selection until it beats a simple
   baseline and completes a frozen prospective period.
5. Calibration changes are separate from model changes and require the existing per-item gate.
6. No optimiser, ML model, LLM programme generation, parent-variant targeting or weakness
   targeting.

**Workstream A — cardio**

| phase | deliverable | gate / acceptance |
|---|---|---|
| A0. Scope and data audit | Confirm modalities (walking, cycling, rowing, running, intervals), available HR fields, resting-HR source and explicit injury-region tags; measure current coverage | A short audit states how many sessions have duration, average/max HR, sRPE and modality; unresolved questions are recorded, not guessed |
| A1. Capture completion | Close only the gaps the audit proves necessary; keep append-only; no free-text parsing in the core | A cardio session can be recorded with its method-relevant fields and cited from the UI/CLI |
| A2. Impulse v1 | Compute one documented impulse: HR-based TRIMP where average HR, resting/max HR and duration exist; otherwise sRPE × duration. Store the method and inputs | Fixed test cases reproduce the impulse; every value says which method was used and why |
| A3. Shadow load context | Show 7-day and 28-day cardio load and a separate cardio/neuromuscular context; do not fit a fitness–fatigue model yet | Display includes inputs, method coverage and time window; no prescription reads it |
| A4. Model decision | Only after at least 12 weeks and ~24 cardio sessions: fit a cardio fitness/fatigue candidate and compare with the simple 7/28-day load and readiness-only baselines | No model is fitted on readiness as if it were performance; if it loses, keep descriptive load only |
| A5. Interaction review | Decide whether cardio context may inform readiness display, never constraints/injury/loads | Any load/RIR effect is a separate decision after a prospective result |

**Workstream B — calibration depth**

| phase | deliverable | gate / acceptance |
|---|---|---|
| B0. Comparable data | Use Workout mode so prescriptions have snapshots; collect optional per-rep CSV where available | Comparable counts are reported per item, not just mark counts |
| B1. Review the measurable items | **done 2026-11-07** — written review in [RUBRIC-CALIBRATION.md](docs/RUBRIC-CALIBRATION.md); rotation is a definitional split (app-assigned neutral), essential work is coverage-limited | Acceptance met: the review classifies the remaining disagreements as rubric, measurement or data-coverage; no retune |
| B2. Reach the item gate | **retired 2026-11-13** — the loop ended before the gate was reached (`DEC-EVAL-09`) | No further marks are collected; the historical counts stay in RUBRIC-CALIBRATION.md |
| B3. Rubric decision | **not taken; retired with the rubric** (`DEC-EVAL-09`) | No definition or weight change; this is closed, not deferred |

**Sequence and timing**

- **Weeks 1–2:** A0, A1, B0.
- **Weeks 3–4:** A2, A3; start the shadow load display.
- **Weeks 5–12:** collect cardio and comparable workout data; B1 review at the midpoint.
- **Week 12+:** A4 model decision; the B2/B3 rubric decision was retired with the rubric
  (`DEC-EVAL-09`).
These are planning windows, not promises; missing data pauses the dependent phase.

**Success criteria**

- Cardio coverage is measured and most sessions have a labelled impulse method.
- The shadow context is reproducible and changes no prescription.
- No cardio session silently counts as resistance volume, and no cardio session is invisible
  to an explicit injury-region tag.
- Calibration reports per-item comparable n, not only high-confidence mark counts.
- Any future load effect has a retrospective baseline win and a frozen prospective test.

**Out of scope**

- Parent-variant e1RM ratios and weakness/injury targeting — parent ratios are **closed
  (2026-11-25)**: the descriptive display is delivered and the profile is not pursued; see
  [PARENT-VARIANT-WEAKNESS-EVIDENCE.md](docs/PARENT-VARIANT-WEAKNESS-EVIDENCE.md).
- A single combined cardio/strength fatigue score.
- Optimiser, ML, automatic programme generation.
- Automatic cardio-driven load or RIR changes.

**First actions**

1. Run the A0 cardio data audit and record coverage/method gaps.
2. Confirm the cardio modalities and resting-HR source with the athlete.
3. Add the A2 impulse contract and fixed test cases before any model work.
4. Keep collecting live workouts and per-rep data for B0 in parallel.

### 4.18 LLM-guided suggested programme  (future; not scheduled)

**Idea:** the model could eventually propose a *suggested programme* — session emphasis, exercise
choices, weekly volume allocation and progression structure — rather than only narrating a
Python-built prescription.

This is explicitly future work, not a v0.3 deliverable. The existing invariants still apply:

- the model receives a structured state/evidence summary and a bounded menu of allowed
  exercises, sessions and volume bands;
- it may propose **choices**, never loads, reps, RIR, percentages or safety vetoes;
- Python validates every proposal against the constitution, constraints, injury signal, volume
  landmarks and comparability classes;
- a suggested programme is shown as a diffable proposal with evidence and assumptions, and is
  never applied without explicit approval;
- every proposal and approval is audited; the deterministic programme remains the fallback;
- the proposal must not invent evidence or hide uncertainty.

**Prerequisite:** a stable programme schema, a validated volume/selection policy and enough
reviewed sessions to evaluate whether the suggestions are better than the fixed programme.
**Status:** idea only; no implementation. It is now developed as the two-iteration workstream
in §4.24 and [`docs/LLM-INTEGRATION-PLAN.md`](docs/LLM-INTEGRATION-PLAN.md); this subsection is
kept as the original idea record. Its forward planning is now §4.34 and the portfolio Training
Intelligence plan; the proposer part is deferred/unscheduled.

**Next-phase design:** the final lean non-cardio fatigue-management plan is **closed**
([`docs/archive/NEXT-PHASE-FATIGUE-PLAN.md`](docs/archive/NEXT-PHASE-FATIGUE-PLAN.md)). It used the existing
data plus an sRPE/duration backfill for descriptive calibration and implemented the optional
deload plus four deterministic programme changes, and closed individual MRV as not estimable.
No programme experiments, no individualised MRV and no randomised deload trial. The remaining
deferred items stay listed in §4.19.

**Note:** the live weakness-targeting plan remains in `ROADMAP.md` §4.20.3; the rest of §4.20 is archived here.

### 4.20 Post-review follow-ups  (unscheduled)

Moved out of the strength-programme review so it can close. These are **not** v0.3 work.

1. **Prospective validation gate.** No current candidate. A model may enter a frozen prospective
   period only after it beats the fixed/persistence baseline in a retrospective walk-forward.
   The current continuity and fatigue models failed; they remain fixed/shadow-only. A prospective
   run is 8–12 weeks / 24–36 sessions with no retuning and no load effect.
2. **Parent-variant e1RM ratios — closed 2026-11-25.** Evidence review 2026-10-25: a ratio is a
   relative performance profile, **not** a weakness or injury measure. The descriptive display
   shipped in 2026-11: three configured relationships in Performance, each gated by a 14-day pair
   gap, 42-day age and two observations per side, with no target and no load conversion
   (`DEC-MON-03`). The **repeated-pair profile** — comparable rep/RIR/equipment conditions, a
   minimum number of pairs, a bootstrap or credible interval and a formal parent relation — is
   **not pursued**: display-only at most, and variants are trained in blocks so comparable pairs
   are rare. Reopen only with a new owner request and enough pairs to make an interval
   meaningful. See
   [PARENT-VARIANT-WEAKNESS-EVIDENCE.md](docs/PARENT-VARIANT-WEAKNESS-EVIDENCE.md).
3. **Weakness/injury targeting.** No positive targeting. A display-only own-history context is
   implemented. A gated testing plan is in
   [WEAKNESS-TARGETING-PLAN.md](docs/WEAKNESS-TARGETING-PLAN.md). Weakness targeting is gated by
   DEC-SELECT-05 (earliest after v1.3 / ~April 2027); injury targeting is unscheduled and remains
   constraint/penalty/ceiling only.

**Open decisions register**

| decision | state | where |
|---|---|---|
| Prospective validation of a future continuity/fatigue candidate | gate only; current candidates rejected | §4.20.1, DEC-VALIDATION-01 |
| Parent-variant e1RM ratios | **closed 2026-11-25**: descriptive display delivered; repeated-pair profile not pursued; never a weakness measure | §4.20.2; `PARENT-VARIANT-WEAKNESS-EVIDENCE.md` |
| Weakness targeting | plan only; deferred to after v1.3 / ~April 2027 | §4.20.3, `WEAKNESS-TARGETING-PLAN.md`, Q22, DEC-SELECT-05 |
| Selection A/B boundary (pause/narrow, SSB/high-bar) | dormant policy decision; current default is conservative (A only same exercise) | Q21, docs/SELECTION-COMPARABILITY.md |
| Cardio model | v1.6 | §4.13, Q14 |
| Low-bar competition squat and the weekly spinal cap | **closed 2026-10-25**: counts cost 1; cap raised 3 → 6; bench+hinge uses sumo 2.5 | `DEC-SPINE-05`, Q24, LIM-44 |

### 4.24 Future LLM integration workstream  (superseded in part 2026-11-14; see §4.34)

**Status: superseded in part 2026-11-14; not implemented.** The read-only half of this workstream —
architecture and contracts, the shared context/evidence builder, the athlete analyst, the programme
explainer, the MCP server and the Apple-platform work — is specified in §4.34 and the portfolio
[Training Intelligence plan](https://github.com/georgesdib/strength-app/blob/main/docs/plans/TRAINING-INTELLIGENCE.md).
Rows 1–3 and the exit gate below are superseded; the MCP clause of Iteration 2 is superseded; the
constrained proposer (rows 4–5) was **withdrawn 2026-11-17** and needs a new decision. Phase 1b, the
outbound-data inventory (plan §8.1) and the evaluation gates (plan §9) remain in force. No prompt,
source, schema, API, UI or training-rule change is part of what remains; the detailed requirements,
privacy rules and acceptance criteria live in
[`docs/LLM-INTEGRATION-PLAN.md`](docs/LLM-INTEGRATION-PLAN.md), whose status banner records the same
scope. The analysis below is kept as the historical record of the boundary.

The future architecture separates three capabilities that share one deterministic evidence
layer but have different permissions:

- **Athlete analyst** — read-only progression, programme-status and priority-coverage reports,
  with evidence links and explicit data-quality limits.
- **Programme explainer** — concise and expandable explanations of the actual persisted
  prescription, its modifiers and its warnings; no prescription change.
- **Constrained proposer** — structured structural proposals from canonical ids and allowed
  choices; Python resolves loads and re-validates; the deterministic baseline remains visible;
  the user must explicitly approve; shadow/opt-in rollout only.

AFC (§4.33, [`AFC plan`](https://github.com/georgesdib/strength-app/blob/main/docs/plans/AFC.md)) is the deterministic producer of the metrics,
observations and evidence these capabilities consume. The shared context/evidence builder in
Iteration 1 phase 2 serialises AFC evidence ids; it does not recompute adherence, VBT, readiness or
volume metrics. There is one evidence schema, defined in the AFC plan §6 and section 4 above.

The deterministic engine, taxonomy, comparability rules, history and prescription validation
remain authoritative. If no LLM is configured, the analyst/explainer/proposer functions are
simply unavailable; deterministic training is unchanged. External calls require the
field-level outbound-data inventory and sensitive-field safeguards in
[`docs/LLM-INTEGRATION-PLAN.md`](docs/LLM-INTEGRATION-PLAN.md) §8.1; structured injury,
symptom and health data are not assumed non-sensitive.

### Iteration 1 — practical capabilities, minimal infrastructure

Iteration 1 reuses the existing LLM client, structured proposal path, feature calculations,
repositories, prescription provenance, validators and trace. The shared deterministic
context/evidence builder is **new Phase 2 work**, not an existing component. Iteration 1 does
**not** require a vector database, RAG, embeddings, tool framework or autonomous agent
framework.

| phase | scope | depends on | status |
|---|---|---|---|
| 1 | Architecture and contracts: capability boundaries, permissions, context/evidence schema, prompt/schema versions, privacy, iteration boundary | owner approval | **superseded by INT-1** (portfolio plan) |
| 1b | **Retire the minimal LLM exercise selector** as a separate work item: remove only selector-specific chooser/CLI/API/UI/engine/tests/docs plumbing; preserve shared LLM client/config, narrative/proposal, deterministic selection, taxonomy, comparability, class-B confirmation and history; acceptance in plan §8.2 | the approved Training Intelligence contracts (INT-0/INT-1); **independent of the proposer** | **planned** |
| 2 | **New** shared context/evidence builder + athlete analyst: lift progression, programme status, strength/power/longevity review | phase 1; existing features/repositories/provenance; the AFC evidence contract (AFC-2/AFC-3) | **superseded by INT-2/INT-3** |
| 3 | Programme explainer: persisted prescription, modifiers, baseline/previous comparison, concise + detailed | phase 2; prescription provenance | **superseded by INT-2 (facts) + INT-5 (narration)** |
| 4 | Constrained proposer in shadow: structured schema, deterministic validation, Python load resolution, baseline comparison; no application | phases 1–3; existing proposal/validator path | **deferred/unscheduled** (write capability; new decision required) |
| 5 | Opt-in approval + evaluation: diff UI/CLI, explicit approval, provenance, shadow/opt-in gates; no selector work | phase 4; phase 1b; approved gates; privacy review | **deferred/unscheduled** with row 4 |
| exit | Iteration 1 exit gate: selector retired; analyst/explainer accepted; proposer shadow/opt-in gates green; no-LLM path tested | phases 1, 1b and 2–5 | **superseded** (INT-1 to INT-8 carry their own gates) |

**Dependency order (superseded for the read-only work):** v1.5 cardio/calibration work, then phase 1,
then 2 → 3 → 4 → 5; phase 1b runs after phase 1, in parallel with 2/3 if useful, and must finish
before the Iteration 1 exit. The current read-only order is INT-1 → INT-2 → INT-3 (§4.34); phase 1b
still precedes any server-side narration phase.
No capability code starts before the owner approves its contracts. The former proposal phases
4–5 are withdrawn with `DEC-LLM-09`; no write path runs.

**Selector retirement is not a refactor and not a proposer dependency.** The deterministic
selection engine, taxonomy, movement-family classifications, comparability rules, validation,
class-B `selection_confirmed` confirmation and history remain. Only the minimal LLM chooser is
removed. The proposer was withdrawn 2026-11-17; `DEC-LLM-09` is closed, not deferred.

**Wider proposal licence — withdrawn.** With the proposal surface removed there is no menu or
approval path to extend. If a write capability is ever revisited, it needs a new decision and the
same structural-only boundary.

### Iteration 2 — evidence retrieval and advanced architecture (conditional)

Iteration 2 begins only after the Iteration 1 exit gate. It starts with a needs assessment, not
with technology adoption. RAG, semantic/hybrid retrieval, a vector database, advanced
orchestration/tool use and an owner-operated MCP server over Tailscale are candidates, not
requirements; any one may be rejected. A vector database is permitted only if the retrieval
benchmark shows a simpler deterministic/keyword or hybrid approach is insufficient. **Superseded
in part (2026-11-14):** the MCP server is no longer an Iteration 2 candidate — it is planned as
INT-1/INT-2 (§4.34) with application authentication, and Tailscale remains reachability only. The
vector-store and RAG retrieval candidates were withdrawn with INT-12 (2026-11-24); bounded
orchestration remains conditional.

| phase | scope | depends on | status |
|---|---|---|---|
| 6 | Needs assessment: recurring gaps, trusted corpus, retrieval requirements, simpler alternatives, MCP/Tailscale tool boundary and authorization, benchmark, cost/latency/privacy/maintenance case | Iteration 1 exit gate; owner authorisation | **conditional** (MCP clause superseded by INT-1) |
| 7 | Advanced component trial: one approved component at a time (bounded orchestration; RAG/hybrid retrieval withdrawn with INT-12; MCP transport superseded by INT-1), off by default, baseline comparison | phase 6 decision; privacy review | **conditional** (MCP transport clause superseded by INT-1) |

**Proceed criteria for any Iteration 2 component:** documented recurring need; simpler
alternative tested; measurable benefit on a pre-registered evaluation set; acceptable cost,
latency, privacy and maintenance; no safety or deterministic-fallback regression; owner approval
and a new decision. Any MCP component must also be tailnet-only, application-authenticated,
read-only until separately approved, and prohibited from direct writes/prescription commitment.
No dates are assigned.

**Non-goals:** autonomous workout replacement, LLM arithmetic, LLM vetoes, unsupervised tool
use, self-directed database writes, adopting RAG/vector databases/agent frameworks merely
because they exist, a new provider/dependency without a demonstrated need, and any change to the
fixed programme methodology. Analyst and explainer outputs do not change training; proposer
changes require explicit approval.

**Exit gates:** Iteration 1 as above; Iteration 2 phase 6 owner disposition; phase 7 measured
benefit and no regression. No phase claims that prose quality or acceptance rate proves better
coaching.

### Closed items from §4.19 (moved 2026-11-25)

**Closed 2026-11-24: the main-lift upward-revision ratchet.** It will not be built. It was rejected
as a controller in `DEC-E1RM-PLAUS-01`: a cap on the per-session e1RM increase bounds the change, not
the level, and at 2 % of a 180 kg e1RM it would brake ordinary progression. The display-only
plausibility advisory remains the guard, and the idea is not to be revisited.

**Closed 2026-11-25: parent-variant e1RM ratios.** The descriptive display remains — three
configured relationships in Performance, date/gap-gated, no target and no load conversion — but the
repeated-pair profile with an uncertainty band is **not pursued**. It is display-only at most, and
variants are trained in blocks, so comparable pairs are rare. Reopen only with a new owner request, a
formal parent relation and enough pairs to make an interval meaningful.

**Closed 2026-11-25: web authentication and per-user data.** Not pursued. The server stays a
single-user tool on a trusted home LAN over HTTP (`DEC-WEB-03`, `LIM-57`): no auth store, sessions,
login UI, per-user databases, profile onboarding or TLS is planned (`DEC-WEB-04`). The work would
cost roughly 10-15 sessions across the backend and iOS, plus a data move and a re-pair, for a
benefit that only appears with multiple users or access beyond the LAN. Reopen only with a new
owner decision if either happens.

### Backlog item — personalised volume-response model

- Personalised volume-response model — **closed as a controller** (2026-11-24): the retrospective
  mechanism analysis stopped and the continuous persistence follow-up is descriptive only, so no
  rule was built. A future attempt must satisfy the data and prospective-design trigger in the
  future backlog row above; fixed budget and safety guards remain authoritative. See
  `docs/archive/VOLUME-MODULATION-PLAN.md` §13 and Q28.

### Backlog item — grip-strength readiness input

- Grip-strength readiness input — rejected (`DEC-GRIP-01`); grip remains a periodic
  measurement, not a daily readiness input.
