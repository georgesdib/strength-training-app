# ROADMAP

The resume point for this project. If you are picking this up cold — human or agent — read
this file first, then [`AGENTS.md`](AGENTS.md) for the rules of the codebase.

**This file is forward-looking only.** Completed work lives in
[`ROADMAP-DONE.md`](ROADMAP-DONE.md); work that was retired or decided against lives in
[`ROADMAP-RETIRED.md`](ROADMAP-RETIRED.md). Do not add completed or retired material here.

Last updated: 2026-11-26 · forward work only. The v1.x releases, the resolver structure
WP0–WP9, the read-only Training Intelligence layer and AFC-2–AFC-4 are recorded in
[`ROADMAP-DONE.md`](ROADMAP-DONE.md); withdrawn or retired work is in
[`ROADMAP-RETIRED.md`](ROADMAP-RETIRED.md).

---

## 1. How to resume

    cd strength-training-app
    .venv/bin/python -m pytest            # default suite
    .venv/bin/python tools/profile_data.py   # data profile (needs data/raw/)
    .venv/bin/python tools/baseline.py       # strength baseline

Then read, in order:

1. [`USER-GUIDE.md`](USER-GUIDE.md) — how to use what exists
2. **this file** — what is open and what is next
3. [`docs/DECISIONS.md`](docs/DECISIONS.md) — decisions that are expensive to reverse
4. [`docs/OPEN-QUESTIONS.md`](docs/OPEN-QUESTIONS.md) — what is still ambiguous, with defaults
5. [`ROADMAP-DONE.md`](ROADMAP-DONE.md) — delivered history (audit only, not a default read)
6. [`ROADMAP-RETIRED.md`](ROADMAP-RETIRED.md) — retired/decided-against work (audit only)
7. [`docs/V0-SCOPE.md`](docs/V0-SCOPE.md) — the agreed scope and its exclusions
8. [`AGENTS.md`](AGENTS.md) — invariants, layering, definition of done

**Resume rule:** update the status table in the same commit as any phase change. Completed
items move to `ROADMAP-DONE.md`; retired or decided-against items move to
`ROADMAP-RETIRED.md`; neither stays in this file. If the table disagrees with the code, the
table is wrong — fix it before adding features.

## 2. Status

Only open and future work is listed. Released versions and completed phases are in
[`ROADMAP-DONE.md`](ROADMAP-DONE.md).

| # | Work | Status | Gate / next action | Where |
|---|---|---|---|---|
| Phase 5A | Prospective validation | **active; 2026-10-30 to 2027-01-22** | review gate 2027-01-22; monitored instruments stay frozen | §2A |
| Phase 5B | Evidence-driven implementation | **gated; not approved** | starts only after the Phase 5A gate and explicit approval | §2A |
| — | Weakness/injury-targeted selection | **gated; earliest after v1.3 / ~April 2027** | `DEC-SELECT-05`; no implementation now | §4.20.3 |
| — | Exercise-level symptom research (Phase 3) | **planned; unscheduled** | pre-registration and a separate owner decision | §4.28 |
| — | AFC-5 evidence-gated prescription adaptation | **scoped, docs only; gated** | separate decision and evidence | §4.33a |
| — | Training Intelligence remaining work | **INT-9 waits for iOS 27.3; aggregate evidence producers deferred; T-3a optional; multi-tool orchestration deferred** | see §4.34a | §4.34a |
| — | Symptom-region mapping review | **implemented; follow-up open** | review the broad mappings (core, hamstring) after real flares; `LIM-78` | §4.35 |

## 2A. Phase 5 — prospective validation and evidence-driven improvements

Phase 5 is split into two gated stages. Only Phase 5A is active. Phase 5B must not begin
until the 22 January 2027 review gate is completed and the user explicitly approves it.

### Phase 5A — Prospective validation

| Item | Value |
|---|---|
| Status | **active next stage** |
| Observation start | 2026-10-30 |
| Formal review date | 2027-01-22 |
| Duration | 12 weeks |
| Today follow-up | `phase5a_review` — Phase 5A — Prospective validation review |

Objective: evaluate the existing monitoring system prospectively on real training data
collected during normal use.

During Phase 5A:

- do not change monitoring model parameters, thresholds, metric definitions or eligibility;
- do not change calibration factors/logic or prescription/optimisation behaviour;
- do not introduce predictive models or tune thresholds to observations;
- do not treat correlations as causal or silently change a metric because its result is unexpected;
- data-integrity or incorrect-calculation bug fixes are permitted only when documented,
  justified and tested;
- AFC (§4.33a; the delivered AFC-2–AFC-4 record is in ROADMAP-DONE.md §4.33) is read-only composition and must not change `attendance.pct`, the flags in
  `features/prospective.py`, monitoring/exposure/calibration configuration, or the end-screen
  capture controls for session RPE, duration and productivity ([`AFC plan`](https://github.com/georgesdib/strength-app/blob/main/docs/plans/AFC.md) §5).

Evaluate/classify every metric using the existing monitoring analysis infrastructure:

- data quality: completeness, missingness, consistency, provenance;
- measurement reliability: stability and repeatability;
- metric behaviour: distributions, variability, sensitivity, responsiveness;
- calibration: evidence supporting the existing approach;
- training response: plausible correspondence with performance and exposure, without causal claims;
- practical utility: interpretability without overstated certainty.

Evidence classes: **supported**, **provisionally supported**, **insufficient evidence**,
**not validated**, **not applicable**, each with rationale.

**22 January 2027 review gate:** document the evidence and choose exactly one:

A. proceed to Phase 5B;
B. extend Phase 5A once by approximately four weeks, documenting the missing evidence;
C. close Phase 5A without Phase 5B, documenting which metrics remain unvalidated.

**Documentation at the same gate:** fold the maintainer-only monitoring design history
(docs/design/) into [docs/MONITORING-ANALYSIS.md](docs/MONITORING-ANALYSIS.md) and retire or mark
the separate design trail; tracked in §4.19. Do it only after this review classifies the metrics.

Completing the Today follow-up requires an explicit decision; it never starts Phase 5B or
changes monitoring automatically.

**Closed-item check:** parent/variant e1RM ratios remain closed as weakness, injury or automatic-selection measures (DEC-SELECT-09). The configured relative-strength ratios in Performance are descriptive only and do not reopen that decision. See DEC-MON-03.

### Phase 5B — Evidence-driven implementation (gated)

| Item | Value |
|---|---|
| Status | **gated; not approved or underway** |
| Start | only after the Phase 5A gate and explicit user approval |
| Initial duration | 4–8 weeks |

Each proposed change must identify the Phase 5A finding, evidence, expected effect,
unintended consequences, acceptance criteria, tests and documentation/limitations updates.
Changes must be classified as measurement/data-quality correction, metric-definition
correction, calibration improvement, threshold/classification adjustment, new analytical
capability, or rejected proposal. Rejected proposals are documented with reasons.

Phase 5B is complete only when every Phase 5A finding is assessed, supported changes are
implemented or explicitly rejected, tests pass, no critical data-integrity/monitoring defect
remains, and validated versus unvalidated capabilities are clearly distinguished.

Phase 5B must not introduce predictive/prescriptive behaviour merely from a descriptive
association without separate justification and validation.

## 3. Completed and retired archives

Completed v0.1–v1.x work — including every released version, the resolver structure WP0–WP9,
the read-only Training Intelligence layer, AFC-2–AFC-4 and the delivered cardio/longevity
work — is recorded in [`ROADMAP-DONE.md`](ROADMAP-DONE.md). Work that was retired, withdrawn
or explicitly decided against is recorded with its reason in
[`ROADMAP-RETIRED.md`](ROADMAP-RETIRED.md). Both are audit records, not a default read.

## 4. Forward work (open items)

### 4.19 Open next actions

| priority | action | status |
|---|---|---|
| P1 | Record **≥3 measured tests per main lift** so `MOD-E1RM-001` can calibrate the formula (the bias question is data-starved, not mechanism-starved) | **next** — `e1rm tests-needed` reports counted tests per main lift against the gate (the Athlete page shows the same table); `e1rm calibrate` shows the ratio and CI; record from the Athlete page, an Exercises row or the post-workout panel |
| P2 | Fold the monitoring design history into docs/MONITORING-ANALYSIS.md | **scheduled 2027-01-22, with the Phase 5A review gate** — summarise `docs/design/` into the canonical document and retire or mark the separate trail. Do not do it earlier: Phase 5A classifies each metric, and the design must not be presented as settled first |
| P2 | Weakness/injury-targeted selection | deferred to after v1.3 / ~April 2027; gates in §4.20.3 and `DEC-SELECT-05` |

**Standing validation gate:** no model enters a frozen prospective period until it beats the
fixed/persistence baseline in a retrospective walk-forward; the current continuity and fatigue
candidates failed and remain fixed or shadow-only. A prospective run is 8–12 weeks / 24–36
sessions with no retuning and no load effect.

Completed actions that used to sit in this table are recorded in
[`ROADMAP-DONE.md`](ROADMAP-DONE.md) under §4.19.

### 4.20 Weakness/injury targeting — open item

The review, parent-variant closure and open-decision register are in
ROADMAP-RETIRED.md §4.20. The only live piece is the test plan below.

#### 4.20.3 Weakness targeting test plan  (plan only; unscheduled)

[WEAKNESS-TARGETING-PLAN.md](docs/WEAKNESS-TARGETING-PLAN.md) defines the full test:

1. **Data:** 12 sessions for the target lift across 12 weeks, with snapshots, RIR and symptoms.
2. **Definition:** own-lift recent baseline minus current trend, with a pre-registered noise-aware
   threshold; never a parent-variant ratio or population norm.
3. **Retrospective screen:** fixed selection vs the targeting rule on the same chronological
   dates; screening only, not causal proof.
4. **N-of-1:** opt-in alternating fixed/targeted blocks, at least three pairs or report unknown,
   with stop rules for symptoms and guardrail lifts.
5. **Decision:** keep fixed, display-only, or bounded opt-in targeting after the N-of-1 result.
   Injury targeting stays unscheduled; injury remains exclusion/penalty/ceiling only.

No implementation, no automatic substitution and no load effect follows from this plan.

### 4.28 Exercise-level symptom research (Phase 3)  (planned; unscheduled)

**Status:** planned research, not approved for implementation and not scheduled. No code,
schema, model or behaviour change exists in this phase. Today follow-up:
`injury_attribution_phase3`.

**Question.** Does a particular exercise show a different rate of later regional symptoms
than comparable sessions without it, after plausible confounders? This is a descriptive
association question, not a causal or diagnostic one.

**Data.** Mechanical exposure from `clean_set` working sets through the region links in
`config/injuries.v1.yaml`; the existing 0–3 regional symptom readings and follow-up window;
and the training-day/fragment grouping. Athlete attribution is **not** the label source; at
most it is a separate interpretability label.

**Method.** Pre-register the question, outcome window, confounders, missingness rules and
analysis before looking at results. Report exposure and symptom counts, missingness,
uncertainty and sparse-data states. The result stays descriptive.

**Out of scope.** No predictor, risk score, diagnosis, suitability rating, constraint,
selection, load or prescription change. No new symptom scale. No automatic adoption; any
later use needs a separate decision and validation.

**Prerequisites.** Enough prospective symptom and exposure data, a written pre-registration
and a separate owner decision to start. Phase 3 is independent of the closed Phase 1–2 plan
and is not a reason to reopen it.

### 4.33a AFC-5 — evidence-gated prescription adaptation  (scoped 2026-11-13; docs only; gated)

AFC-5 is the only remaining AFC phase: it would adapt prescriptions from AFC evidence, only
after a separate decision and a prospective result. It has no code, schema or approval, and it
does not block or reopen AFC-2 to AFC-4. The second cut of AFC-3 — stagnation and "improving
performance with stable effort" — is deferred into AFC-5 (`DEC-AFC-07`).

The delivered AFC-2, AFC-2i, AFC-3 and AFC-4 record is in
[`ROADMAP-DONE.md`](ROADMAP-DONE.md) §4.33; the canonical plan is the
[AFC plan](https://github.com/georgesdib/strength-app/blob/main/docs/plans/AFC.md).

### 4.34a Training Intelligence — remaining work

Delivered: INT-1 to INT-8, INT-10, INT-11 and INT-13; their implementation and operational
record is in [`ROADMAP-DONE.md`](ROADMAP-DONE.md) §4.34. The retired parts — the constrained
proposer/write path (`DEC-LLM-09`), PCC (INT-4c) and web search/RAG (INT-12) — are in
[`ROADMAP-RETIRED.md`](ROADMAP-RETIRED.md) §4.24.

Still open:

- **INT-9** (Siri, Shortcuts, HomeKit and Action button surfaces) waits for iOS 27.3.
- **Aggregate evidence producers** for the aggregate capabilities remain deferred.
- **T-3a** (optional further session-details latency work) is not started; the T-3 first pass
  is closed.
- **Multi-tool orchestration** is deferred by owner decision.

### 4.35 Symptom-region mapping review  (open; evidence-driven)

**Delivered already:** eleven regions, character and side logging, exposure links, the
per-region policy switch, the region-scoped reactive deload and the flare-only ceiling (see
ROADMAP-DONE, 2026-11-28). What is open is whether each mapping is *narrow enough*.

**Question.** A region's link set is a mechanical claim, and some are broad: `core` reaches 65
catalogue exercises, so a core flare takes 40% off squats; `knee`, `hip_groin` and `hamstring`
sit near 60. Is that proportionate to how those regions behave in this athlete's training, or
is it a blanket reaction? Should forearm grip coverage stay an explicit exercise list, or become
a taxonomy flag? Do eleven regional review prompts add signal or noise?

**Trigger.** A handful of real flaring episodes observed with both the ceiling and the local
deload active. This is a config review, not an implementation: how to change a mapping, and
what moves when you do, is [INJURY-CONFIG.md](docs/INJURY-CONFIG.md).

**Not in scope.** Per-region fuzzy matching, symptom-weighted scoring, or any predictor. The
mapping stays a mechanical exposure statement (`ASSUMPTION-10`).

## 5. Known gaps and risks

This section keeps **no list**. Every accepted limitation is registered with an id, a status and
a "revisit when" in [`docs/LIMITATIONS-REGISTER.md`](docs/LIMITATIONS-REGISTER.md); forward-looking
work lives in §4.19 and the open items in §4.33a and §4.34a. The table that used to sit here was folded into
that register on 2026-10-26 — `LIM-45`–`LIM-49` are its new rows, and the rest already existed
(`LIM-07`/`LIM-10` duration and timestamps, `LIM-14` spinal cost, `LIM-24`/`LIM-43` e1RM bias).
Two rows that described *planned work* were not limitations and did not move: calibration
comparability is tracked in ROADMAP-RETIRED.md §4.14, and the cardio impulse (ROADMAP-RETIRED.md §4.13a A2/A3) was retired on 2026-11-18
(`DEC-LONGEVITY-03`).

## 6. Idea backlog (not approved, not scheduled)

Recorded so genuinely open ideas are not lost; these are explicitly **not** commitments.
Delivered and rejected ideas are recorded in `ROADMAP-DONE.md` and `ROADMAP-RETIRED.md`.

- Personalised volume-response model — **closed as a controller** (2026-11-24): no rule was
  built, and the retrospective mechanism analysis stopped. A future attempt is unapproved and
  must satisfy a strict trigger: roughly 25–30 eligible app workouts with stored velocity
  targets, and a prospective design (alternating blocks or a pre-registered N-of-1). Fixed
  budget and safety guards remain authoritative. See
  [`docs/archive/PERFORMANCE-PERSISTENCE-PLAN.md`](docs/archive/PERFORMANCE-PERSISTENCE-PLAN.md).
- Athlete Feedback & Coaching (AFC) — the remaining AFC-5 work is in §4.33a; the delivered
  AFC-2 to AFC-4 work is in `ROADMAP-DONE.md` §4.33.

## 7. How to change this roadmap

- Phase status changes go in the table, in the same commit as the work.
- New phases get a number and an acceptance criterion before any code is written.
- **Completed work moves to [`ROADMAP-DONE.md`](ROADMAP-DONE.md); retired or
  decided-against work moves to [`ROADMAP-RETIRED.md`](ROADMAP-RETIRED.md). This file must
  stay forward-looking.**
- Anything that changes a rule, a threshold that affects a load, or a recorded decision must
  also append to [`docs/DECISIONS.md`](docs/DECISIONS.md).
- Personal goals, injuries and preferences are **not** recorded here — this repository is
  public. They live in the git-ignored `private/`.

## Related

- **Roadmap:** this file
- **Completed work:** [ROADMAP-DONE.md](ROADMAP-DONE.md)
- **Retired work:** [ROADMAP-RETIRED.md](ROADMAP-RETIRED.md)
- **UI surface:** [docs/UI-MAP.md](docs/UI-MAP.md)
- **Evidence:** [docs/REFERENCES.md](docs/REFERENCES.md)
- **Decisions:** [docs/DECISIONS.md](docs/DECISIONS.md)
- **Open questions:** [docs/OPEN-QUESTIONS.md](docs/OPEN-QUESTIONS.md)
