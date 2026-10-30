# ROADMAP

The resume point for this project. If you are picking this up cold — human or agent — read
this file first, then [`AGENTS.md`](AGENTS.md) for the rules of the codebase.


Last updated: 2026-10-30 · **v1.0 beta released; v1.1 planned** · version `1.0.0b2` · **1025 public tests passed**


---

## 1. How to resume

```bash
cd strength-training-app
.venv/bin/python -m pytest            # 794 locally, including the 15 private integration tests
.venv/bin/python tools/profile_data.py   # data profile (needs data/raw/)
.venv/bin/python tools/baseline.py       # strength baseline
```

Then read, in order:

1. [`USER-GUIDE.md`](USER-GUIDE.md) — how to use what exists
2. **this file** — where we are and what is next
3. [`docs/DECISIONS.md`](docs/DECISIONS.md) — decisions that are expensive to reverse
4. [`docs/OPEN-QUESTIONS.md`](docs/OPEN-QUESTIONS.md) — what is still ambiguous, with defaults
5. [`docs/V0-SCOPE.md`](docs/V0-SCOPE.md) — the agreed scope and its exclusions
6. [`AGENTS.md`](AGENTS.md) — invariants, layering, definition of done

**Resume rule:** update the status table below in the same commit as any phase change. If the
table disagrees with the code, the table is wrong — fix it before adding features.

## 2. Status

| # | Phase | Status | Artifacts |
|---|---|---|---|
| 0 | Design + approval | **done** | `docs/ARCHITECTURE.md`, `DATA-MODEL.md`, `DATA-QUALITY.md`, `RULES-FORMAT.md`, `VBT-CALIBRATION.md`, `MODULE-LAYOUT.md`, `V0-SCOPE.md`, `OPEN-QUESTIONS.md`, `SANITY-CHECKS.md`, `TRAINING-GUIDELINES.md` |
| 1 | Ingest (clean + sessions) | **done** | `ingest/clean.py`, `ingest/sessions.py`, `config/templates/inference.v1.yaml` |
| 2 | Derived features + VBT calibration | **done** | `features/derived.py`, `features/baseline.py`, `features/vbt_calibration.py`, `domain/e1rm.py`, `domain/load.py`, `domain/rir.py` |
| 3 | Store (SQLite, append-only) | **done** | `store/migrations/0001_initial.sql`, `store/db.py`, `store/repositories.py`, `store/importer.py` |
| 4 | Rules loader + policy engine | **done** | `rules/loader.py`, `registry.py`, `context.py`, `policy.py`; predicates for all five rules |
| 5 | Prescription engine (four session types) + deterministic fallback | **done** | `prescribe/templates.py`, `config.py`, `loads.py`, `engine.py`, `fallback.py`; `config/thresholds.v1.yaml` |
| 5.5 | Athlete state — DATA-MODEL §11 tables | **done** | `store/migrations/0003_athlete_state.sql`, `prescribe/constraints.py`, `cli state` / `cli block`; hard constraints veto |
| 6 | Critique rubric + trace | **done** | `critique/facts.py`, `critique/rubric.py`, `trace/run.py`; 7 measurable items; velocity loss remains unmeasured, imported duration unavailable |
| 7 | LLM layer (narrative only) | **done** | `agents/client.py`, `config.py`, `narrative.py`; `config/llm.example.toml`, `tools/llm_check.py` |
| 8 | Backtest harness + labelled eval set | **done** | `eval/harness.py`, `eval/labels.py`, `tools/eval_prepare.py`, `tools/backtest.py`; small high-confidence labelled set; exact counts private |
| 9 | CLI (`run` / `review` / `calibrate` / `import`) | **done** | `cli.py`; prescriptions persisted; `review --pending` catches up; calibration loop closed |
| v0.2 | Input flexibility + programme view | **done** | readiness entry/score/devices/settings + gate (§4.1/4.9), continuity (§4.6), injury signal (§4.7), local web UI with import/state editing/Programme/Cardio/Terminal/calibration (§4.10/4.11), cardio capture + weekly summary (§4.13), labelled set (§4.14), session RPE/length, recent stress, per-lift readiness, e1RM calibration + bounded correction + age decay |
| v0.3 | Strength/data depth | **done** | manual logging via live workout mode (§4.2/§4.21, closed), import adapters closed (§4.3), learned readiness weights evaluated and closed (§4.9), LLM proposal view closed as CLI-only (§4.11), continuity calibration (§4.12; calibrated factor rejected, fixed fallback), exercise selection apply + comparability + display-only history (§4.15; weakness/ratios in §4.20), strength fitness-fatigue shadow model (§4.16; retrospective rejected), rolling session types / upper-body balance / set reduction / volume management v1 / under-MEV accessory progression / warm-up ramp / 3RM cadence / descriptive progress dashboard (§4.17), live workout mode (§4.21, closed), read-only 4/8/12-week outcomes review, longevity context, prescription-modifier provenance and quick readiness presets/context and readiness feedback, UI prescription persistence (A0/A/B/C/E), minimum effective sessions (D) the methodology/privacy docs (F), W1/W7 attendance metrics and the session-time cap |
| v0.4 | Audit, documentation and form closeout | **done 2026-10-25** | form assessment/prospective follow-up, fatigue diagnostic closure, UI documentation P0–P4, parent-ratio evidence review, weakness test plan, calibration milestone (§4.22) |
| v1.0 beta | Workable app + guided Workflow UI | **released 2026-10-27** | full strength loop, guided readiness → preview → workout → post-workout, effective volume accounting, template editor, schedule fallback/rebalance; user testing in progress |
| v1.1 | Beta removal + cardio + calibration depth | **planned; plan at §4.13a** | drop the beta label after user testing; pending: cardio capture audit, reproducible impulse, shadow cardio load (§4.13); comparable calibration depth (§4.14) |
| future | LLM integration: analyst, explainer, constrained proposer | **Iteration 1 planned after v1.1; Iteration 2 conditional** | phased workstream at §4.24; architecture, iteration gate and selector retirement in [`docs/LLM-INTEGRATION-PLAN.md`](docs/LLM-INTEGRATION-PLAN.md); no implementation in this pass |
| — | 2026-10-26 pass | **done 2026-10-26** | declared breaks — append-only range, `break` CLI, Athlete panel, freeze in the trained-week cycle (`DEC-CONTINUITY-04`, `LIM-50`); P1 measured-test coverage view (`e1rm tests-needed` + Athlete table); symptom settling made fail-safe — a level-1 reading without a recorded 48 h settlement is a flare (`DEC-SYMPTOM-04`, Q25 closed) and `docs/SYMPTOM-LOGGING.md` documents the episode workflow; minimum-session target shown against the measured clock (`DEC-MIN-02`, `LIM-47` mitigated); gaps table folded into `docs/LIMITATIONS-REGISTER.md` |
| — | 2026-10-28 fatigue signals Phase 0 | **done 2026-10-28** | five decisions (`DEC-EXPOSURE-02`, `DEC-DEMAND-01`, `DEC-RESIDUAL-01`, `DEC-SELECT-12`, `DEC-SHADOW-01`), five assumptions, `LIM-56`, ACWR doc drift corrected; `docs/FATIGUE-SIGNALS.md` maps Parts A–D onto the real engine stages and `docs/EXERCISE-DEMANDS.md` defines the companion catalogue. No code, no behaviour change |
| — | 2026-10-28 audit fixes | **done 2026-10-28** | independent beta audit: continuity calibration **accepted** and the decision rewritten (`DEC-CONTINUITY-06`); injury ceiling applied independently of readiness, low back excluded (`DEC-INJURY-04`); readiness set cut takes precedence over the under-MEV top-up (`DEC-VOLUME-33`); browser mutations require loopback Host + same Origin + JSON content type and the CLI refuses non-loopback `--host` (`DEC-WEB-01`); Terminal removed (`DEC-WEB-02`); rubric calibration filtered to the current version (`DEC-EVAL-06`); programme horizon 1–26 weeks and one job per database (`DEC-PROGRAMME-09`) |
| Phase 5A | Prospective validation | **active next stage; 2026-10-30 to 2027-01-22** | `phase5a_review` Today follow-up; see §2A |
| Phase 5B | Evidence-driven implementation | **gated; not approved or underway** | starts only after Phase 5A gate and explicit approval; see §2A |
| — | 2026-10-30 monitoring Phase 4 | **done 2026-10-30** | read-only calibration observation layer around the active calibration; formula/method version and current-as-of semantics exposed; reusable descriptive dose/lag/missingness analysis service with Performance UI and GET /api/monitoring-analysis; CLI remains a thin wrapper; no calibration calculation/application changes, no model adoption and no schema change |
| — | 2026-10-30 monitoring Phase 3 | **done 2026-10-30** | Performance view and API/CLI for raw e1RM observations, rolling median, series breaks and dose; functional session-type/deload/quality filters; degraded observations shown separately; explicitly configured relative-strength ratios with eligibility-aware history; comparable-session descriptive summary; no target ratios, diagnosis, decay or calibration. Equipment breaks remain undetectable because equipment is not stored |
| — | 2026-10-30 monitoring Phase 2 | **done 2026-10-30** | completed-workout descriptive summary (completion, raw strength, dose, special exposure, feedback) with API/CLI/end-screen; approved append-only `session_feedback.productivity` 1–5 migration preserving existing rows; no ratios, longitudinal trends or prescription control |
| — | 2026-10-28 knee-flexion accessory | **done 2026-10-28** | `lying_leg_curls` 3×8-12 added to the squat and hinge sessions with `nordic_curl` as an opt-in candidate; `knee_flexion` is a managed ledger key (MEV 3 / MAV 4–8 / MRV 10, target 6/week, cap 4) and the `hamstring_eccentric` pattern maps onto it; weekly total 57→63, effective 68.25→74.25; programme summary regenerated; remaining unprescribed groups recorded as accepted gaps (`LIM-54`) (`DEC-KNEEFLEX-01`, `ASSUMPTION-50`) |
| — | 2026-10-27 audit follow-up | **done 2026-10-27** | back-flare alignment (`DEC-SPINE-07/08`), quality-limited power (`DEC-POWER-02/03`), same-date plan accounting (`DEC-VOLUME-30/31/32`), readiness RIR re-solve (`DEC-READINESS-18`), generated programme summary; independent audit report [`docs/AUDIT-FOLLOW-UP-REPORT.md`](docs/AUDIT-FOLLOW-UP-REPORT.md); `LIM-53` closed; **audit fully closed 2026-10-27, no open follow-ups** |
| — | 2026-10-25 corrective pass | **done 2026-10-25** | e1RM selector + plausibility advisory (`DEC-E1RM-SOURCE-01`, `DEC-E1RM-PLAUS-01`), `MOD-SPINE-001` spinal trim, group-level volume status (`DEC-VOLUME-05`), technique throttle in the API and Prescribe form (`MOD-TECH-001`), e1RM overrides in Exercises and post-workout; legacy A/B/C labels removed from rule scopes and taxonomy `day_roles`; squat loading kept out of the spinal cap as a recorded scope decision (`DEC-SPINE-04`, later superseded by `DEC-SPINE-05`); constitution 1.13.1 (`DEC-RIR-04`; `MOD-TECH-001`/`MOD-MIN-001` declared) |
| — | Post-workout form assessment | **done 2026-10-25** | optional per-lift 1–5; Workout + History edit; rubric 1.2.0 |
| v0.1 | Complete | **done** | 3.1-3.4, 3.6-3.7 done; 3.5 video descoped; 3.8 labelled set moved to §4.14 |
| — | UI | **local web done; hosted UI deferred** | `strength_coach/web/`, `docs/WEB-UI.md`, `http://127.0.0.1:8000`; Settings tab for LLM and browser defaults |
| — | Engine audit W0–W12 | **closed 2026-10-23** | `docs/AUDIT-CLOSEOUT.md`; open items in `docs/LIMITATIONS-REGISTER.md` |

### Version plan (2026-10-25)

| version | boundary | status |
|---|---|---|
| v0.2 | readiness, continuity, injury, web UI, cardio capture, measurements, session RPE/length, recent stress, per-lift readiness, e1RM calibration/decay | **done** |
| v0.3 | everything strength/data-depth that is not cardio: manual logging, adapters closed, LLM proposal view CLI-only, continuity calibration, exercise selection, strength fitness-fatigue model | **done** |
| v0.4 | audit/documentation/form closeout: form assessment, fatigue diagnostic, UI docs P0–P4, ratio review, weakness plan, calibration milestone | **done 2026-10-25** |
| v1.0 beta | workable app, guided Workflow UI and the current strength/volume feature set | **released 2026-10-27; beta** |
| v1.1 | beta removal plus cardio depth and comparable calibration data | **planned; see §4.13a** |
| — | post-workout form assessment | **done 2026-10-25** |
| future | LLM integration: analyst, explainer, constrained proposer | **Iteration 1 planned after v1.1; Iteration 2 conditional (§4.24)** |

**Rule:** cardio work does not enter v0.3; video is descoped. The strength model (§4.16) is
strength-only and closed with v0.3. Audit/documentation/form closeout is v0.4. v1.0 is the beta
release for user testing; v1.1 drops the beta label and adds cardio depth and comparable
calibration data.

### What works end to end today

A real export can be cleaned, flagged, quarantined, grouped into sessions, given a programme
day guess, calibrated for velocity targets, and **persisted**: one import writes `raw_row`,
`clean_set`, `session` and `quarantine` inside a replayable `run`/`run_event` trace, and
re-importing the same file writes no duplicate rows. The constitution can now be evaluated
against that history: `rules` parses the YAML into hash-bearing `Rule` objects, the registry
supplies one predicate per `check.fn`, and `policy` returns a verdict per rule with citable
evidence. A session for **each of the four rolling session types is now generated**: loads solved from a selected e1RM — a 28-day median by default, `best_usable` or `most_recent` by config (`DEC-E1RM-SOURCE-01`) — or from double
progression for accessories, rounded down to the athlete's 0.5 kg microplates, with
MOD-FAT-001 reducing loads when sleep or energy is <= 2. Every item cites a rule id and a
stored set, and the prescription refuses to be executable if a load, the RIR window, the
erector-day rule or the weekly spinal cap would be broken. At the weekly cap (the normal cycle
sits exactly on it) a non-essential erector slot is trimmed rather than left dead
(`MOD-SPINE-001`); essential overages still veto and name the exposures. A main-lift load whose
e1RM sits far above the lift's recent median raises a display-only advisory rather than a load
change (`DEC-E1RM-PLAUS-01`). The web UI exposes the one-session technique throttle on the Prescribe
form (`MOD-TECH-001`) and appends e1RM overrides from an Exercises row or the ended-workout
panel, where a recorded test feeds the measured/formula calibration. A performed session can now be
**critiqued**: seven rubric items score it (RIR adherence, progression adherence, weekly spinal
cost, essential work, redundancy, rotation and measured live-session duration) with evidence
references. Imported-session duration and within-set velocity loss remain `measurable = 0`
because the export cannot support them. The critique is persisted append-only inside a `run` trace. An **optional narrative** can explain
either artifact: the model receives the facts as JSON, may not compute, and its output is
recorded as a `run_event` rather than written into a prescription or a score. With no model
configured (`NullLLM`) the run is structurally identical and loses only the prose. There is
**the full v0 slice runs**: `strength-coach run --date` imports if needed, critiques the
last session, prescribes the date, persists both inside a run trace, and prints a rationale
that cites a rule or a stored fact. `review` is the calibration loop: it shows the session
beside the rubric's scores, takes marks, stores them append-only, and reports running
agreement immediately. Two of the three marks are reconstructed from memory and excluded;
agreement is reported against the remembered marks; exact counts are private (`DEC-EVAL-03/04`).

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
  justified and tested.

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

## 3. v0.1 — complete

v0 is complete (see §2 and the user guide). This is the agenda for the next version, in
dependency order. Nothing here blocks using v0 as it stands.

### 3.1 Athlete state — the §11 tables  (done)

Scope: `athlete_profile`, `athlete_constraint`, `exercise_suitability`, `metric_definition`,
`symptom_log`, as numbered migration `0003_athlete_state.sql`, plus writers and a CLI to
enter them.

Why it is first: it is the only way goals, injuries and preferences become *state* rather than
something an agent remembers. Until it exists, no hard constraint can veto anything and an
empty table is indistinguishable from "no constraint".

Acceptance: the five tables exist; a `hard_exclude` constraint vetoes a proposed exercise
deterministically (tested); `exercise_suitability.will_do = 0` is surfaced as a warning, never
a silent drop and never a safety veto; unrecorded state reports `none_recorded` and a warning,
never "nothing is wrong".

Delivered: all five tables append-only; `strength-coach state [--import FILE]` and
`strength-coach block --date`; `prescribe/constraints.py` applies constraints and suitability
inside the engine's validation. `constraint` became `athlete_constraint` because the former is
a reserved SQL keyword (`DEC-STATE-01`). The athlete's answers are imported from
`private/athlete-state.yaml`: longevity goal, three resolved monitor-severity back tweaks, and
14 exercises all rated can-do/will-do. Also delivered: **manual e1RM overrides**
(`e1rm set/list`, append-only, optional expiry) so a tested value outranks the computed
estimate and is cited in the prescription.

Input: `private/docs/INFO-REQUESTS.md` §1-3, read back for confirmation before being written.
**Status: the core answers are collected in `private/docs/ATHLETE-STATE.md`** (goals, back
history, suitability, equipment, schedule). Two consequences are already decided: `longevity`
was the recorded goal at the time (the goal fields were later retired, `DEC-STATE-02`), and
training-log gaps are recorded as **non-adherence**, never as symptoms.

### 3.2 Squat-led and bench-led templates (legacy Days A/C)  (done)

Depends on 3.1. The SSB question (H1) is answered: the bar is available. The erector-ramp
anchor is also settled in principle — **the athlete declares the official start, and can reset
it at any time** (`DEC-RAMP-01`), so the anchor is stored, never inferred.

Scope: squat-led and bench-led templates; `block start [--date]` command that sets or resets week 1 as
a new profile row (never an edit); **a reset restarts the ramp at week 1** (`DEC-RAMP-02`), not
just the calendar; the ramp reads that row.

Acceptance: a template per session type with its own essential lifts; `PRG-SCHED-001` enforced
(no erector work on the hinge session, erector work allowed on squat-led/bench-led); a golden
prescription per canonical type (`tests/fixtures/golden_session_types.yaml`).

Delivered: squat-led and bench-led templates with erector + accessory work; `run --session-type T`;
golden fixtures for the canonical types. Core work was added on 2026-10-20 (`ab_wheel` on the
squat-led type, `hanging_leg_raise` on the bench-led type, `DEC-CORE-01`;
`docs/CORE-TRAINING.md`). The squat-led type opens with a power slot (`box_jump`,
`DEC-POWER-01`); the hinge type carries the vertical-pull variant slot (`pull_up` /
`lat_pulldown`, `DEC-PULL-01/02`; `docs/LONGEVITY-REVIEW.md`).
Bodyweight erector work is prescribed at load 0 with an explicit warning, never as a 0.5 kg
"progression". The athlete declares the block start whenever they choose, so the ramp stays
`unknown` until then.

Consequence: `PRG-DP-001` should stop being `unknown`. It was unknown because its scope
includes accessories that no single day prescribes, so the per-day rep-range map always lacked
one exercise. Fixed in Q16 by pooling rep ranges across all three templates; see
`docs/CORE-TRAINING.md` §5.4.

### 3.3 Symptom input  (done)

Depends on 3.1 (`symptom_log`). This is the missing safety input (Q4): a manual `--back 0-3`
per session, with `settled_within_48h`.

Timing is **pre-session only** and it is **one number for the whole back** for now; per-region
detail is deferred (`DEC-SYMPTOM-01`).

Acceptance: `PRG-EREC-001` and `MOD-BACK-001` evaluate instead of returning `unknown`; the
stability gate uses real entries; every verdict cites the symptom rows it used.

Delivered: `symptom --level 0-3 [--settled yes|no] [--date]` and `symptom --show`; the rules
context derives the flare and the block week; `PRG-EREC-001` returns a real verdict once a
reading and a declared block exist, citing `symptom:<date>`; a flare makes `MOD-BACK-001`
transform the prescription (erector back to the weeks 1-3 dose, main lifts at RIR 3). Multiple
entries per day are allowed, latest wins (migration 0005).

### 3.4 The LLM may tweak the prescription — within the rules  (done)

Today the model only narrates. In the next version, with `--llm on`, it may also *propose* a
modified hinge session, subject to the same policy engine that judges a performed one. The
standing rule (AGENTS.md §3.3) is what makes this safe: **the policy engine may veto or
downgrade the model; the model may never veto the rules.**

What it may propose:

- substitute an accessory for one with the same movement pattern and compatible properties;
- choose between the day's allowed bench variants;
- adjust set counts within configured bounds;
- drop a non-essential item, or reorder items.

What it may **not** do:

- supply a raw load — every load is re-derived by the Python solver from the proposal's
  structured intent (AGENTS.md §3.2). The proposal schema has no field for a number on the bar;
- push RIR outside the rule window;
- add direct erector work on the hinge day (`PRG-SCHED-001`) or push the week over the spinal
  cap;
- invent an exercise outside the taxonomy, or one the athlete's constraints exclude.

How it is checked:

- the proposal is structured (exercise ids plus bounded deltas), never prose;
- `rules.policy` evaluates the *proposed* session against the constitution;
- `veto` → the deterministic fallback is used; `downgrade` → the reduction is applied;
  `warn`/`advisory` → recorded;
- `prescription.approved_by = "llm+policy"`, and the proposal plus its verdicts are stored in
  the `run` trace so the decision is replayable;
- with the model off or failing, the deterministic prescription is byte-identical.

Why it waits for 3.1: a substitution is only safe once the athlete-state tables say which
exercises are excluded or merely unwelcome. Without them the model would be choosing from a
pool that includes movements the athlete cannot or will not do.

Consent: the athlete wants **both substitutions and adjustments, but shown before applying**.
No proposal is applied silently — `run --llm on` prints the difference and asks; a `--yes` flag
covers scripting.

Decision needed at implementation time: this *narrows* `DEC-LLM-01` — prose stays event-only,
but a structured proposal that passes policy may become the prescription. That needs a new
`DEC-LLM-04` recording exactly which fields the model may influence and which it may not.

Acceptance:

- an illegal swap (erector work on the hinge day) is vetoed, the deterministic prescription is
  used, and the veto is visible in the trace;
- a legal substitution is accepted, persisted with `approved_by = llm+policy`, and its loads
  still come from the solver;
- a proposal carrying a raw load or an out-of-window RIR is rejected by validation before it
  reaches the engine;
- nothing is applied without an explicit confirmation, and declining leaves the deterministic
  prescription untouched;
- the existing LLM-off equivalence test passes unchanged;
- the golden fixture gains an accepted-proposal case and a vetoed one.

Delivered: `run --propose [--yes]` (requires `--llm on`). Parsing rejects any
computed-number key — load, weight, RIR, percentage or velocity — anywhere in the payload, so a
confused model cannot inject a weight. Substitutes are narrowed to the same movement pattern
and filtered by stored constraints; the replacement is rebuilt by the engine's own
`build_item`, so the load comes from the same solver as the deterministic path. The result is
judged by `validate_prescription` and the constraint check before anything is stored.
Acceptance is explicit (`--yes` for scripting), `approved_by = llm+policy` marks the artifact,
and the proposal, verdict and reasons are `run_event`s. Proposals are not attempted on a
session a safety modifier already changed. A proposal may also name one of a small menu of
Python-computed options (keep/easier/harder/heavier/lighter); the menu's RIR width is the
rule's window, so a documented window change widens it without a code change. `DEC-LLM-04/05`
record the contract.

### 3.5 Video analysis — descoped

Video capture and vision-model commentary are not planned. The post-lift form assessment in
§4.8 is the replacement, and it stores no video.

### 3.6 Another athlete, or a fresh start  (done)

The tool should be usable by someone else with their own export, and by the athlete after a
year away, without editing code or mixing data. This is **not** multi-tenancy: one database
per person.

Scope: document the first-run path for a new athlete (export → state file → block start);
verify nothing personal is baked into config or defaults; keep `--db` as the only switch
needed; keep the exercise taxonomy editable so a different exercise vocabulary is a YAML edit.

Acceptance: a second database with a different athlete's synthetic history runs `import`,
`run`, `review` and `calibrate` with no code change and no access to the first database; no
personal value appears in any committed file; the user guide has a "new athlete" checklist.

Delivered: `tests/test_portability.py` runs the whole loop on two databases with different
lifts, dates and days, and asserts neither sees the other's artifacts; a tracked-file test fails
if anything under `private/` or `data/` (except the folder README) is committed; the guide has
section 12 with the checklist, and `config/athlete-state.example.yaml` is a placeholder state
file with no personal values. `DEC-PORT-01` records the one-database-per-person rule.

### 3.7 VBT prescription wiring  (done)

Deferred by `DEC-VBT-01`. The calibration (band, sparsity ladder, versioning) already exists
and is tested; what is missing is the rule that turns a band into a target:

- which rep in the set is targeted — the first, the last, or a mean;
- what tolerance counts as "on target" before a set is flagged;
- what to prescribe when the band is wide, or when the lift is `uncalibrated`.

Acceptance: `PrescriptionItem` carries `velocity_target` and `vbt_basis`;
`prescription.calibration_ids` cites the rows used; an uncalibrated lift says so explicitly;
the golden fixture gains velocity columns.

Do not start this before those three questions have answers — inventing them is what the
deferral exists to avoid.

### 3.8 Labelled set — moved to §4.14

This is now a v0.2 item; the content and acceptance are in §4.14. v0.1 is complete.

### 3.9 Deliberately not planned

- A UI (deferred by request).
- Several athletes in one database, or a hosted service: local-first, one database per person
  (3.6 covers portability; video is descoped).
- RAG over the programme: rules are cited by id, and exact lookup beats semantic search here.
- Automatic rubric retuning: the report proposes, a person decides.

## 4. v0.2 — input flexibility and the programme view

v0.1 assumes three things that the athlete has now explicitly challenged: that input arrives
as one CSV in one known shape, that only one day is prescribed at a time, and that readiness
is only available on days the export happened to record. v0.2 loosens all three.

Nothing here changes the constitution or the append-only rule. Missing data still yields
`unknown`, never a default.

### 4.1 Readiness on demand — daily, occasional, partial  (done)

The fatigue modifier is only as good as the readiness it sees. Today those rows come from a
single exported CSV, so a missing day silently means *no modifier*, which is easy to mistake
for *fresh*. That is the failure this item removes.

Scope: `readiness set --date ... --sleep --energy --soreness ...` accepting **any subset** of
fields; bulk entry through `state --import`.

Precedence (decided): a manual value wins **per field**, the imported row fills the fields it
does not provide, and the merge note records both values and which source won. Nothing is
silently overridden.

Which fields drive the modifier is config (decided): MOD-FAT-001 reads sleep and energy today,
and the list is a config value so it can grow. Other fields are recorded and reported, but do
not move a load.

Robustness rule: an absent input never becomes a value. A prescription for a date without
readiness says *"readiness unknown for <date>; fatigue modifier not applied"*. A partial row
applies only the fields it has.

Acceptance: a day with 2 of 7 metrics applies the modifier on those two only; a day with none
leaves it unapplied **and says so**; a week-long gap changes nothing else; re-logging a date
appends a version rather than editing it.

Data: `readiness_day` is currently one upserted row per date. This needs an append-only
`readiness_entry` with latest-wins reads, so history is preserved.

Delivered: `readiness set` with any subset of fields, bulk entry through `state --import`,
append-only `readiness_entry`, per-field manual-over-import precedence with a `sources` map,
and the explicit *readiness unknown* warning. The derivation is in
[`docs/READINESS.md`](docs/READINESS.md); the changeable parts are config in
`config/readiness.v1.yaml` (`DEC-READINESS-04`).

### 4.2 Logging workouts three ways  (v0.3; manual path closed)

Three input paths, one downstream shape:

1. **the same export file** — already supported and idempotent by content hash;
2. **manual post-workout entry** — **per set** (decided): `log set --date --exercise
   --weight --reps --rir`, repeated per set. No exercise-level shorthand: the set is the unit
   of record everywhere else, and expanding a summary into sets would invent detail. Must
   produce exactly the same `clean_set` / `session` rows as an import;
3. **another file format** — see 4.3.

Manual entry is also the only path that can capture **session duration**, because the export
has no timestamps. `session.duration_min` becomes measurable (`duration_basis = measured`),
and the rubric's `SESSION_DURATION` flips from `measurable = 0` to a real score — the first
time that item can move.

Manual entry must pass the same gates as cleaning: unknown exercise names are quarantined or
reported (never dropped), `RIR 6` is a warm-up, and seconds-vs-reps follows the taxonomy.

Capture post-session fatigue (1-5) with the session; it feeds §4.12 and is not a rubric item.

**Status 2026-10-23:** manual logging is closed through live workout mode — Start from a
prescription with the seven required readiness fields, manual/imported sets, inline correction,
measured/editable duration, sRPE or not-recorded, end/abandon, plan overrides, materialisation
into `clean_set`/`session`, and rubric/review. The standard dated training export remains the
backfill path; the separate adapter work is §4.3.

Acceptance: a manually logged session is indistinguishable downstream from an imported one
(same tables, same critique); concluding a workout also catches up unreviewed sessions via
`review --pending`; duration is stored when given and stays `unavailable` when not
— never estimated; the rubric scores duration only when it exists.

### 4.3 Column-mapping adapters for other exports  (CLOSED 2026-10-23 — not needed)

**Status: closed.** The standard dated training export is the backfill path, and the workout
CSV is imported in-workout. No additional adapter registry is needed. Unknown exercise names are
still reported/quarantined, and extra raw columns remain in `raw_row`; neither justifies a second
mapping layer.

### 4.4 Programme output — a rolling horizon, not a block  (done: CLI + web)

Today `run` emits one day. The athlete wants either **the whole programme** or **what remains**
of it.

Decided: there is **no fixed training block**. Training is continuous. A deload can be
**scheduled** every six weeks from the declared block anchor or **reactive** when the data
asks for it; the schedule is configurable and the reactive triggers still override it. That
makes "remaining programme" simply "from today onward".

Scope: `programme --weeks N [--remaining] [--start-session-type T]` prints a rolling horizon. The horizon is a
forecast, not a commitment, and `--remaining` starts from today. The declared
`block_start_date` anchors the erector ramp and the scheduled deload; it does not bound the programme.

Scheduled deload: every six weeks from `block_start_date` by default, presented as a
**suggestion** at workout time (default no; non-interactive default no). One set per item
(minimum two), 10% load reduction and one RIR under `MOD-DELOAD-001`. Reactive deload triggers
remain **automatic**: two consecutive weeks over the spinal cap, **or** two consecutive
flaring sessions. A reactive deload emits `fallback_level = fatigue_reduced` and cites the
trigger. The six-week interval is an assumption, not a scientific claim.

Planned loads (decided): **recomputed on the day**. A plan is a forecast; the day's
prescription uses the current e1RM, readiness and symptoms. Planned rows are superseded when
the day arrives, never edited.

Rules: progression between weeks uses the existing double-progression decisions for
accessories and e1RM-derived loads for main lifts; the weekly spinal cap and the erector ramp
apply across the horizon.

Acceptance: `programme --weeks N` prints a dated session-type forecast with canonical session types; `--start-session-type T` sets the first session; `--remaining` starts today;
every planned session carries its rationale refs; the day's prescription recomputes and
supersedes the plan; scheduled and reactive deloads fire on the configured triggers and say why; printing
a programme needs no LLM.

### 4.5 Decisions taken (2026-10-17)

| question | decision |
|---|---|
| Block length and deload | **No fixed block. Deload is scheduled every six weeks or reactive**, configurable; the reactive triggers remain |
| Planned loads | **Recomputed on the day**; a plan is a forecast and is superseded, not edited |
| Manual logging granularity | **Per set**; no exercise-level shorthand that would invent detail |
| Readiness fields for the modifier | **Sleep and energy, as a config list**; other fields are recorded and reported only |
| Manual vs imported readiness | **Manual wins per field**, import fills gaps, the merge note records both |

These are recorded in the decision log as `DEC-PROGRAMME-01/02/05`, `DEC-LOG-01` and
`DEC-READINESS-02/03`. The deload interval and reactive thresholds are explicit policy and
remain config, not a claimed scientific finding.

### 4.6 Training continuity — missed and planned time off  (done)

The programme must survive real life: a week lost to illness or work, a holiday, a planned
deload, and a deliberate test week. Today nothing distinguishes "trained on Tuesday" from
"did not train at all", so the DUP cycle and the erector ramp advance by calendar only.

Scope:

- **Detect gaps** from stored sessions. A session that was never logged must not be treated as
  a session at the old load; the next prescription should know how long the gap was.
- **Declared breaks.** A `break --from --to [--reason]` record (holiday, deload, test week)
  that freezes the DUP week and the ramp anchor for the duration. An undeclared break is
  inferred from the gap and reported.
- **Re-entry rules**, config-driven and separate for strength and erector work:
  - 7-10 days off: keep the load, add one RIR for the first week back;
  - 14+ days: reduce load ~10% for a week, then resume progression;
  - 28+ days: re-enter the erector ramp at week 1 (or a declared re-anchor) rather than
    pretending the ramp continued.
- **Cycle semantics.** A missed week should not advance the DUP cycle; a declared break should
  pause it. This is the difference between "week 3 of the cycle" and "the third week of
  training".

Acceptance: a missed session does not advance the DUP week; a declared break freezes it; after
a 3-week gap the prescription is a re-entry session with the reason cited; a declared test week
does not count as a training week; no artifact is deleted or rewritten.

Decided: gaps are detected from history (a declared break is optional); thresholds 14/28/56
days; a missed week does not advance the DUP cycle; a test week counts as a trained week; the
prescription states that it is amended because of the gap; the erector ramp pauses during a gap
and steps back one stage after the long break; bodyweight work keeps its load but reduces volume
and adds one RIR. The exact thresholds remain assumptions (`DEC-CONTINUITY-01`).

Delivered: gap detection from stored sessions, `MOD-GAP-001`, trained-week DUP cycle, ramp
step-back after a long gap, bodyweight set reduction, and the message in the prescription.
Open items recorded in Q12.

**Declared break delivered 2026-10-26** (`DEC-CONTINUITY-04`): an append-only range that freezes
its weeks in the trained-week count, exposed as `strength-coach break` and on the Athlete page.
It exists for the week that was trained but must not count — an untrained week is already
skipped. The scheduled-deload clock still counts calendar weeks (`LIM-50`).

### 4.7 Injury signal — per region, informs suitability, never clears it  (done)

The athlete asked whether a back that is "strong and recovered enough" could unlock exercises
like the sumo deadlift. The app has no medical model and must not pretend to; what it can do is
make the relevant history visible and require a human decision.

Scope: derive a **general injury signal plus one per region** from data already stored —
symptom-free streak, flare count and settlement, whether recent sessions loaded the region and
whether a later reading showed no flare, the erector-ramp stage, and the lifts that load the
region. Surface it next to an unrated exercise and next to a proposal to change a main lift.

Hard rule: the signal **suggests a review, never a rating**. It cannot set
`exercise_suitability`, cannot clear a constraint, and cannot substitute a lift. The athlete
rates; the model may explain; the engine obeys.

Acceptance: the signal cites the symptom rows, window and tolerated count it used; an unrated
lift shows "needs review" with that evidence; no automatic state change occurs; the athlete can
rate in one command (`state --rate`).

Decided (`DEC-BACKSIGNAL-01`, amended in scope by `DEC-INJURY-01`): symptom-free **with
tolerated loaded sessions** may recommend a rating; readiness is excluded; rest alone earns no
credit; no data is **unknown**; the signal is always disclaimed and may recommend, never set, a
rating. `DEC-INJURY-02` scales the window with prior flares; `DEC-INJURY-03` defines a
tolerated session as loaded **and** followed by a reading with no flare.

Delivered (2026-10-19): `features/injury_signal.py` + `config/injuries.v1.yaml`, low back,
biceps and knee, per-region status and scaled window, `unverified` sessions counted separately,
`state`/prescription/web display, region-scoped symptom logging (`symptom --region`), and an
advisory warning when a prescription loads a flaring non-back region. Evidence and definitions:
`docs/INJURY-SIGNAL.md`. Q13 is answered; the remaining uncertainty is calibration
(`ASSUMPTION-08/09/10`).

### 4.8 Post-workout form assessment (done 2026-10-25)

After a lift, the athlete may rate its form on a **1–5 scale** (5 = best). This is optional,
one rating per exercise, and can be corrected later in **History → Edit**.

- Workout: a **Form** column in the editable plan table;
- History: a form-rating table in the edit sheet;
- imported sessions: ratings can be added through History;
- storage: append-only `workout_form_rating`, materialised to `session_form_rating`;
- rubric **1.2.0**: `FORM_ASSESSMENT` at weight 0.05, averaged over rated lifts;
- unrated lifts are ignored, not zero;
- no load, set, RIR or exercise effect.

The imported `Form` column is not reused: its scale/direction is unconfirmed. This rating is a
separate, explicitly directed measure.

**User-declared technique throttle (2026-10-25).** `MOD-TECH-001` applies a 90% load cap and
an RIR floor of 3 for one session when the athlete explicitly asks for it
(`run --technique-throttle`, Prescribe UI). It is not driven by `form_rating`, stores no state
and cannot latch. The automatic variant proposed as `MOD-FORM-001` was rejected for the
reasons in [`docs/FORM-USE-EVIDENCE.md`](docs/FORM-USE-EVIDENCE.md); see
[`docs/TECHNIQUE-THROTTLE.md`](docs/TECHNIQUE-THROTTLE.md).

### 4.9 Readiness score and follow-ups  (core + devices done; learned weights closed)

Implemented (2026-10-19/20):

- global 0.00-1.00 score from sleep, energy, mood, stress and soreness, with a three-field
  minimum and a sleep/energy requirement;
- category scores; the injury signal is a ceiling, never an average;
- global/category overrides at the score scale, append-only, reason required; override wins over
  computed readiness and changes the load, but never bypasses constraints or injury ceilings;
- 20% cap on combined readiness + continuity reduction (guardrail, no direct evidence);
- readiness-required gate for current/future CLI and web workouts;
- calibration report against the 306 black-box legacy labels, with main-lift load features,
  date split and baseline; report only, no auto-apply;
- baseline-relative HRV/RHR at 0.5 weight, only with 7 readings in the previous 28 days;
- optional device-computed wearable readiness (0-100) at a 10% blend.

Full design and evidence: [`docs/READINESS-SCORE.md`](docs/READINESS-SCORE.md) and
[`docs/READINESS-WEIGHT-EVIDENCE.md`](docs/READINESS-WEIGHT-EVIDENCE.md).

#### 4.9.1 HRV and RHR in the score — done

Baseline-relative HRV/RHR are in the global score: 28-day median, minimum 7 readings, gap
or direction handled explicitly, weight 0.5 each. Missing baseline is shown, not guessed.

#### 4.9.4 Optional wearable score — done

A 0-100 score from a device such as Bevel is an optional 10% blend. It cannot override the
subjective score, constraints or the injury ceiling.

#### 4.9.2 Per-athlete score settings — done

Baseline window, minimum readings, HRV/RHR slopes and weights are append-only athlete rows,
with athlete > config > code precedence. The effective source is shown in the score.

#### 4.9.5 Shadow baseline comparison — done

`readiness shadow` compares the rolling-median baseline with a log-linear trend projection.
It reports the normalised difference; it never changes a score or load.

#### 4.9.3 Learned weights — closed

The constrained comparison (current equal weights, sleep-heavy, HRV-low) found no improvement
in the held-out late period. The performance association was essentially zero in that window
and sRPE associations were weak. Keep fixed transparent weights; do not fit individual weights
from this dataset. Full method/results: [`docs/READINESS-WEIGHT-EVIDENCE.md`](docs/READINESS-WEIGHT-EVIDENCE.md)
and `DEC-READINESS-10`.

### 4.10 Local web UI  (done)

A browser front end over the same core, so routine interactions do not require the CLI. The
CLI remains the automation surface.

- `strength-coach web` serves on **127.0.0.1:8000** by default, no authentication, no external
  assets; docs are rendered locally.
- Pages: Today, Prescribe, Programme, Review, Readiness, Import, Athlete, Docs. (Terminal was
  removed 2026-10-28, `DEC-WEB-02`.)
- The API only serialises and routes; every load/score/warning still comes from the core.
- Tests cover the API round trips, docs rendering and the readiness/review writes.

Done: import, state editing, manual logging, Programme, Terminal. LLM proposal view closed as CLI-only; video is descoped; post-lift form assessment is done.

**Documentation layer P0–P4 (completed 2026-10-25).** Docs support deep links (`#docs?doc=...&anchor=...`),
Markdown headings have stable IDs and duplicate handling, and [`docs/UI-MAP.md`](docs/UI-MAP.md)
is the canonical view/panel → doc/evidence/decision/question/roadmap map. The reusable
`.section-help` pattern is applied to every view-level `h2` panel (P1) and every nested
`h3`/dialog (P2, 2026-10-25), with verified deep-link anchors. Every UI-linked doc now has a
`Related` footer (P3) and an automated coverage/link checker (P4, 2026-10-25) now enforce
the documentation contract.

### 4.11 Web UI parity  (CLOSED for v0.3)

**Status: closed 2026-10-23; amended 2026-10-28.** The **Terminal** was removed
(`DEC-WEB-02`), so the parity gaps that used it as a fallback are CLI-only. Manual logging,
state editing, import, Programme, exercise editing and calibration are in the UI. The LLM proposal view is deliberately **not**
built: `run --propose` stays CLI-only, and the deterministic prescription, warnings and review
remain the UI path. `workout start` is UI-only because it needs the full readiness form. Both are
documented exceptions, not open items.

The local UI covers Today, Prescribe (rolling session types), Programme, Review, Readiness, Import, an editable
Athlete page, an editable **Exercises** catalogue, Terminal and Docs. This item brings the remaining interactive CLI actions into the browser. The CLI stays
as the automation interface; the UI must call the same core functions, never re-implement them.

Planned surfaces, in suggested order:

1. **Import** — **done**. Standard dated training/readiness CSVs and the in-workout workout CSV.
2. **State editing** — **done**. Profile, constraints, suitability ratings, e1RM overrides,
   strength tests, block start and symptoms; append-only, with an exercise picker and the
   current tables shown beside the forms.
3. **LLM proposals** — **closed as CLI-only.** `run --propose` keeps the proposal view, citations,
   warnings and policy veto in the terminal; the web UI does not duplicate it.
4. **Manual workout logging** (4.2) — **done** via Workout mode: per-set entry, plan overrides,
   import, end, review and calibration.
5. **Programme view** (4.4) — **done**. Rolling session-type horizon with recomputation on the day; canonical session types are the only label.
6. **Post-lift form** (4.8) — optional 1–5 per exercise, editable in History, rubric-only.
7. **Readiness settings** (4.9) — **done**. Baseline window, minimum readings, slopes and
   weights; shadow baseline report.
8. **Terminal** — **done**, then **removed 2026-10-28** (`DEC-WEB-02`): a browser surface that
   could mutate state without authentication.
9. **Exercise catalogue** — **done**. Full taxonomy table, search/filter, all fields per row,
   edit/add form writing `config/exercises/overrides.v1.yaml`; ids immutable, log-name
   collisions refused; API tests and CLI `exercise list`/`exercise set`.

Constraints:

- all writes go through the same functions as the CLI; no business logic in JavaScript;
- destructive or diagnostic actions (import, overwrite, conclude) require an explicit
  confirmation step and show the resulting rows;
- uploads stay under private/ and are never committed; no arbitrary filesystem paths;
- the server stays local-only; adding authentication is out of scope for a single-user tool;
- every action reports warnings and refusals as part of the result, not as a toast that hides
  the reason;
- browser mutations require a loopback `Host`, a same-origin `Origin` and a JSON content type
  (`DEC-WEB-01`); the CLI refuses a non-loopback `--host`.

Acceptance: every interactive CLI action has a browser path or a documented exception; the
same inputs produce the same database rows and warnings through either surface; a failed
action leaves no partial write; API tests cover each new write; no load, score or threshold is
computed in the browser.

**Later UI and functionality work:** the UI-04/UI-08 brief and the final functionality/code
audit are consolidated in [`docs/UI-IMPROVEMENT-PLAN.md`](docs/UI-IMPROVEMENT-PLAN.md); closed
2026-10-27 (implemented and merged into `main`; merge `db1cc8f`, lint `49a49cd`).

**Mobile UI audit (2026-10-28):** the consolidated iPhone/form-control audit lives in
[`docs/UI-MOBILE-AUDIT.md`](docs/UI-MOBILE-AUDIT.md). Checkpoints 1–4 fixed the P0 contract
failures, canonical athlete/exercise choices, the active-workout/readiness presentation, mobile
cards, searchable pickers, touch/dialog/safe-area rules and the accessibility/field-error gaps.
The owner completed the native-iPhone pass and the full automated suite is green; the audit is
closed.

**Deferred UI follow-ups (not scheduled).** The plan's O1–O10 are kept here so they are not
lost; details and evidence live in the plan's §14:

- **O1 — Settings extraction** after Exercises.
- **O2 — view registry** for `setView`; once at least two features have moved.
- **O3 — migrate `history.js`/`workout.js` to core**; once a third feature needs the helpers.
- **O4 — streaming/multipart imports** if 40 MiB parse memory becomes a problem.
- **O5 — read timeouts** for slow bodies (slowloris); local-only, lower priority.
- **O6 — HTTP/1.1 and keep-alive**; only with close/drain handling and tests.
- **O7 — limit tuning** (64 vs 96 MiB) after a rejected legitimate import.
- **O8 — 411/413 error copy**; friendly UI text.
- **O9 — markdown scheme allowlist**; block `javascript:` targets.
- **O10 — browser coverage** for import preview/apply and more failure paths.

### 4.12 Continuity calibration from real returns  (v0.3, implemented; calibrated factor rejected)

Estimate per-athlete return retention from actual returns. The fixed 14/28/56 bands remain per-band
fallbacks until that band has enough returns and a tight bootstrap interval; when it does, the
calibrated factor is used and cited in the prescription warning/notes.

**Capture** for every return:

- gap length and the last pre-gap session;
- first session back: load, reps, RIR, whether the planned work was completed;
- symptoms and readiness around the return;
- **post-session fatigue** on a 1-5 scale (1 fresh, 5 spent) as a separate session observation,
  not a rubric item — it is context, not execution quality.

**Estimate** two curves separately:

- **strength** — load at a fixed RIR versus days away;
- **capacity** — sets/reps tolerated without a flare or excessive fatigue versus days away.

Start descriptive (per gap band), then fit a simple retention curve with shrinkage toward the
current defaults. Require a minimum number of returns before showing a suggested multiplier.

**Output**: per-band retention median, bootstrap 95% interval, return count, fixed factor,
applied factor and status. The prescription keeps `MOD-GAP-001` and adds the calibrated factor
in its warning/notes. A band with too few returns, a wide interval, or calibration disabled uses
the fixed factor.

**Retrospective walk-forward (2026-10-20):** a small number of returns; the calibrated-factor
ratio error was worse than the fixed rule, so the calibrated factor **lost** and the fixed
fallback stays in use. Exact counts are in the private audit record.
This is retrospective, not prospective. See [RETROSPECTIVE-VALIDATION.md](docs/RETROSPECTIVE-VALIDATION.md).

Acceptance: `strength-coach continuity` and `GET /api/continuity` show observed returns versus
the fixed rule; the minimum-data rule is explicit; a sparse band keeps the fixed factor; a
well-observed band applies the calibrated factor; the prescription cites the applied rule.

### 4.13 Cardio workouts and an impulse fatigue model  (capture v0.2 done; cardio model v1.1; strength model is §4.16)

The app currently measures resistance training only. Cardio is a separate exposure with a
different fatigue signature, and a single "fatigue score" would hide that. This item adds the
data and a model, initially advisory and in shadow mode.

**Delivered 2026-10-20 (`DEC-CARDIO-01`):** append-only `cardio_log` with modality, duration,
average/max HR, distance and sRPE; `strength-coach cardio` (log with `--date`, `--minutes`,
`--avg-hr`, `--max-hr`, `--distance-km`, `--srpe`; `--show --weeks`); a Cardio page and
`GET/POST /api/cardio`; a weekly summary with the WHO reference as context. No prescription
reads it and no fatigue model exists yet.

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

**Open questions**

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

### 4.13a v1.1 plan — cardio depth and calibration  (approved 2026-10-25)

**Goal:** make cardio a first-class, reproducible exposure; add only a shadow cardio-load
context; and deepen calibration enough to decide whether any rubric definition should change.
No automatic cardio load effect and no parent-variant/weakness implementation in this phase.

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
| B1. Review the measurable items | Inspect RIR, weekly spinal cost, redundancy and rotation disagreements first | A written review identifies whether disagreements are rubric, measurement or data-coverage problems |
| B2. Reach the item gate | Priority gaps: progression, essential work, duration and velocity loss | No rubric retune until each targeted item has enough comparable observations; unknowns stay unknown |
| B3. Rubric decision | Change a definition/weight only after the gate and a pre-declared review | Decision recorded in DECISIONS; no automatic tuning from the latest report |

**Sequence and timing**

- **Weeks 1–2:** A0, A1, B0.
- **Weeks 3–4:** A2, A3; start the shadow load display.
- **Weeks 5–12:** collect cardio and comparable workout data; B1 review at the midpoint.
- **Week 12+:** A4 model decision and B2/B3 rubric decision, only if the gates are met.
These are planning windows, not promises; missing data pauses the dependent phase.

**Success criteria**

- Cardio coverage is measured and most sessions have a labelled impulse method.
- The shadow context is reproducible and changes no prescription.
- No cardio session silently counts as resistance volume, and no cardio session is invisible
  to an explicit injury-region tag.
- Calibration reports per-item comparable n, not only high-confidence mark counts.
- Any future load effect has a retrospective baseline win and a frozen prospective test.

**Out of scope**

- Parent-variant e1RM ratios and weakness/injury targeting — parent ratios remain unscheduled,
  display-only at most; see [PARENT-VARIANT-WEAKNESS-EVIDENCE.md](docs/PARENT-VARIANT-WEAKNESS-EVIDENCE.md).
- A single combined cardio/strength fatigue score.
- Optimiser, ML, automatic programme generation.
- Automatic cardio-driven load or RIR changes.

**First actions**

1. Run the A0 cardio data audit and record coverage/method gaps.
2. Confirm the cardio modalities and resting-HR source with the athlete.
3. Add the A2 impulse contract and fixed test cases before any model work.
4. Keep collecting live workouts and per-rep data for B0 in parallel.

### 4.14 Labelled calibration set  (v1.1; moved from v0.3)

No code. Continue reviewing sessions while they are fresh; the rubric report needs roughly ten
*remembered* sessions per item before changing a definition or weight (DEC-EVAL-03,
DEC-EVAL-04). Reconstructed marks are stored but excluded from agreement.

Current state (2026-10-25): **10 high-confidence reviewed sessions**, with **10 high-confidence marks for every rubric item**. The 2026-10-20 session was completed to 8/8. Headline calibration: 40 comparable items, 75% agreement, MAE 0.19; progression and velocity loss remain non-comparable in the report, and rotation is the weakest measurable item. The label-count gate is met; any rubric retune is still a separate decision.

**Next action (2026-10-25):** do not retune yet. Review the comparable items first
(RIR n=7, weekly spinal n=10, redundancy n=10, rotation n=9); progression (n=0), essential
work (n=3), duration (n=1) and velocity loss (n=0) lack enough engine comparisons because most
sessions are imports without a prescription snapshot or per-rep detail. Use Workout mode, and
the optional per-rep CSV, to build comparable sessions before changing a rubric definition or
weight.
The web Review page has the **Run rubric calibration** button; the CLI remains
`strength-coach calibrate`.

Acceptance: ten high-confidence marks per item before a rubric change; every review appends,
never edits; the report states the sample size and excludes low-confidence marks.
### 4.15 Exercise selection adapted to readiness and fatigue  (v0.3; apply + comparability done)

**Status: apply + comparability implemented 2026-10-20; tax metadata, accessory candidates and symptom/readiness suggestions implemented. Plan closed at suggestions + explicit apply; automatic withholding deferred to the 8-week/30-session review.** The selector now carries tax metadata and `symptom` / `stress_readiness` triggers; substitutions remain explicit. See [`READINESS-EXERCISE-SELECTION-PLAN.md`](docs/READINESS-EXERCISE-SELECTION-PLAN.md) and `DEC-SELECT-06`.

**Current implementation:** `prescribe/selection.py` ranks the configured and catalogue variants per slot from readiness, recent stress, rotation and preference; the rejected fitness-fatigue state is no longer an input; constraints and `can_do: false` exclude a candidate; injury is a penalty, not a veto. Candidates carry an A/B/C comparability class: A applies automatically, B requires confirmation, C is hidden by default and never automatic; the selected lift's own history is always used. A display-only own-history e1RM ratio is shown, but it does not enter the score. See `DEC-SELECT-03` and [SELECTION-COMPARABILITY.md](docs/SELECTION-COMPARABILITY.md). It is exposed as `strength-coach select` and a Prescribe panel. With the explicit **Apply selection** toggle, the chosen candidate replaces the slot exercise and the load is re-solved from that lift's own history (`MOD-SELECT-001`). Without the toggle nothing changes. All synthetic raw variant names were canonicalised and their history rewritten (migration 0014, 114 entities, 3,607 audited remaps; migration 0015 split close-grip pulldown); trap-bar date-scoping and back-extension equivalence are preserved.

**Weakness/injury tailoring — deferred.** No positive weakness/injury targeting. Injury remains
an exclusion/penalty/ceiling. Earliest review is after v1.1 and ~April 2027, and only with 12
sessions per target lift over 12 weeks, a pre-registered own-trend metric, a retrospective
baseline win, and an opt-in N-of-1/alternating test; injury targeting remains unscheduled.
See [WEAKNESS-INJURY-SELECTION.md](docs/WEAKNESS-INJURY-SELECTION.md),
[WEAKNESS-TARGETING-PLAN.md](docs/WEAKNESS-TARGETING-PLAN.md), `DEC-SELECT-04/05`, Q22.

**Later phase — variant-group e1RM ratios.** Variants stay distinct entities for now. A future
model may express a variant's e1RM as a ratio of a parent lift (illustrative: front squat ≈60%
of squat — a fictitious number, not a proposal). Any ratio must be a configured,
per-athlete/phase prior with a CI, learned from paired sessions where possible, used only when
the variant's own history is too sparse, and never presented as a measured e1RM. This needs a
formal `variant_of` relation and a validation rule; it is not implemented.

**Load handling — bands/chains.** The log's weight figure already includes band/chain load, so
the current total-load treatment is accepted for now and no prescription change is made. A
future item should define whether an e1RM uses the total logged load, how band tension varies
through range, and whether these variants need a separate comparison rule.

**Goal.** Choose among evidence-permitted exercises for a slot using the per-lift readiness
score (`docs/LIFT-READINESS.md`), the recent-stress decay (option B), the strength
fitness-fatigue state (§4.16), injury links, equipment, rep range and rotation — without
letting an unvalidated model override safety.

**Default: Python, deterministic.** Score each allowed candidate:

- hard filters — constraint veto, `can_do: false`, injury region active, equipment missing;
- per-lift readiness and recent stress (lower readiness → prefer a lower-skill or less
  fatiguing variant, not a harder one);
- recent stress and the cached fitness-fatigue state;
- rotation/history (avoid repeating the same variant indefinitely);
- a preference/suitability tie-break (adherence is a real outcome).

Only one substitution per slot, cited as `MOD-SELECT-001`; the deterministic candidate list and
scores are shown. Applying a substitution is explicit (UI/CLI toggle) and remains
reviewable; it is never automatic.

**Optional LLM (`--select=llm`).** The model receives the **already-filtered candidate list**
and returns one candidate plus a reason; Python validates and logs the choice. The LLM may not
invent an exercise, a load, a rep count or a veto, and a missing/invalid answer falls back to
the deterministic choice. Off by default; provenance recorded.

**Evidence and limits.** Specificity and adherence support stable exercise choices; there is no
trial showing that algorithmic selection outperforms a fixed programme. Autoregulation
evidence supports adjusting load/effort, not swapping exercises. Injury/suitability links are
exposure maps, not causal (ASSUMPTION-10). Treat selection as a conservative, explainable
preference, not an optimiser.

**Dependencies:** per-lift readiness (done), recent stress (done), session RPE/length (done),
§4.16 model, exercise suitability state, taxonomy metadata.

**Acceptance:** constraints always win (done); selection is reproducible (done); LLM proposals
are validated and cannot override policy (done); shadow mode changes no prescription (done); UI
shows the chosen exercise and why (done); tests cover vetoes, ties, missing metadata and LLM
fallback (done); explicit apply toggle and re-solve (done).

### 4.16 Strength fitness-fatigue model  (v0.3; shadow only; retrospective rejected)

**Status: closed 2026-10-25 — rejected as a predictor; descriptive only.** Prototype implemented
2026-10-20; retrospective check failed 2026-10-20; Phase-1 diagnostic run 2026-10-25. `features/fatigue_fitness.py` fits a
per-lift linear performance model from fixed fitness/fatigue half-lives and the athlete's own
e1RM observations; it reports fitness, fatigue, state, R², condition and refuses sparse or
ill-conditioned fits. It is exposed as `strength-coach fatigue` and on the Prescribe page.
**No load reads it.** Option B (recent stress) and session RPE/length remain inputs.

**Scope.** Strength only. Cardio keeps its own impulse item (§4.13); do not collapse both into
one fatigue scalar. Model per **lift**, with partial pooling across a movement family / muscle
group, rather than a separate free model for every exercise with sparse data.

**Candidate state model.** Per lift (or family), an observed e1RM performance is a slow
fitness term plus a fast fatigue term; training load is built from hard sets × proximity to
failure, with session RPE × duration as a cross-check. Parameters are hierarchical and
partially pooled; intervals are mandatory. The model must state when it is not identifiable.

**Phased plan.**

1. **Inputs**: session RPE/length (done), per-lift readiness (done), recent stress (done),
   e1RM calibration report (done), RIR/VBT. Add a per-lift soreness/readiness rating only if
   it earns its place.
2. **Shadow fit — done for this phase**: fixed half-lives + linear fit on stored e1RM series,
   approximate 95% intervals, family-slope shrinkage, and a chronological 80/20 backtest against
   a naive baseline; an **overall** relative-e1RM row pools lifts. No load change. **Still open:**
   a frozen-parameter prospective test on future sessions. **Retrospective walk-forward:** a small number of lift-session predictions; relative error was substantially worse than persistence (skill −112%), so the model lost and no load or adoption follows. Exact counts are private. **Phase-1 diagnostic:** rolling median beat persistence and the full model on SSB squat (MAE 9.39 vs 19.18) and bench (7.23 vs 15.01); fitness-only and full were identical, so the fatigue term added nothing. Keep descriptive only; do not freeze a prospective test for this form. Volume has no predictive model; selection has no counterfactual.
3. **Prospective validation**: **closed** — not started for this form. The Phase-1 diagnostic
   showed the model loses to rolling median; no candidate is frozen.
4. **Optional use**: only after validation, and only downward (extra caution), never to raise a
   load from an unvalidated model.

**Evidence and limits.** Direct strength evidence is one small weight-lifter study (Busso 1990);
parameters are ill-conditioned and the fatigue term did not improve out-of-sample prediction in
a 2025 re-analysis (Marchal 2025); load metric choice changes the fit (Vermeire 2021/2022); RIR
and e1RM are noisy. Recovery after failure/volume is 24–72 h (Morán-Navarro 2017; Sousa 2024),
which the current RIR window and 48–72 h spacing already manage. See
[`docs/FATIGUE-FITNESS.md`](docs/FATIGUE-FITNESS.md) refs 93–100.

**Open questions.** Which load metric (hard sets, volume load, sRPE)? Per lift vs family? How
many measured tests make a parameter identifiable? Does the model beat readiness-only
prospectively? Does it change any decision in shadow mode?

**Acceptance:** reproducible fit with approximate intervals (done); refuses to show parameters
when unidentified (done); shadow mode changes no prescription (done); per-lift, family-shrunk and
overall views done; chronological backtest done; UI shows inputs, state, intervals, backtest and
“not identifiable” honestly (done); no cardio in the strength model (done); frozen-parameter
prospective test remains open.

### 4.17 Rolling session types and strength-programme balance  (v0.3; volume management v1 done)

**Status: implemented 2026-10-20.** The rigid A/B/C calendar is replaced for new prescriptions by
four session types:

| type | main work | upper body | direct erector |
|---|---|---|---|
| `squat` | SSB squat + power | bench support + row | yes |
| `hinge` | trap-bar deadlift | narrow/pause bench + row + pull | no |
| `bench_squat` | bench + squat support | overhead press + row | no |
| `bench_hinge` | bench + sumo deadlift | overhead press + row + pull | no |

The rolling rule targets two squat, two hinge and two bench-emphasis sessions per six, uses the
recent `session_type` history plus forecast choices, and falls back to the preferred emphasis
cycle when the counts are tied. A missed session shifts the deficit; it does not advance a
calendar. The legacy A/B/C fields and overrides were removed by migration 0023 (`DEC-SESSION-01`); imported sessions without enough evidence stay `unknown`.

**Balance changes:** every session includes bench or another upper-body press/pull, plus a
horizontal row. After the 2026-10-20 review, squat-emphasis SSB is 5×3–5, the bench+squat
squat support is 4×3–5 of **competition squat** (`DEC-PROGRAMME-08`: a second SSB exposure
repeated the squat session's main lift), and the trap-bar hinge is 5×3–5. This restores ~7 squat
sets/week and keeps the trap-bar hinge at ~5 sets/week; the bench+hinge session adds a 3×3–5
sumo deadlift (~1.5 sets/week) as a second heavy hinge exposure. Back extension stays at 3
sets/week. Only the squat-emphasis session carries direct erector work; a normal week is 4/6
(bench+squat) or 5.5/6 (bench+hinge) against the cap. Poor readiness can remove one accessory
set; main-lift set reduction is opt-in (`include_essential: false` by default),
and the Readiness page exposes that **volume valve**.
A weekly **hard-set ledger** reports sets per movement pattern against broad MEV/MAV/MRV
landmarks; non-essential sets are trimmed only when the recent week plus the proposed session
exceeds MRV (`MOD-VOL-001`). Under-MEV adds one accessory set after three weeks below MEV
(`MOD-VOL-002`), while main lifts are unchanged by that rule; poor readiness can remove one
main-lift set when opted in, or an accessory set. Main lifts carry a 50/70/85 warm-up ramp, and `test --status`
reports the 10-week 3RM/5RM cadence. Power work is bodyweight/implement-only.

**Acceptance (done):** session templates parse; every session has a row and an upper-body
push/pull; hinge sessions contain no direct erector work; the two-week sequence balances
squat/hinge/bench; canonical types resolve for history; the rolling forecast and UI expose the
selected type; set reduction is cited in the `MOD-FAT-001` warning; power carries no external
load; full tests pass.

**Volume management v1 boundary (done 2026-10-20).** The evidence check, hard-set ledger,
configured MEV/MAV/MRV landmarks, conservative MRV cap, readiness volume valve and UI/CLI/API
are complete. The following are explicitly **not** claimed as done:

- individual MRV calibration — closed as not estimable (`DEC-VOLUME-04`);
- main-lift volume titration below MEV;
- a fully autoregulated deload (a scheduled/reactive policy now exists);
- per-muscle rather than movement-pattern volume;
- set quality/load/tonnage rather than raw hard sets;
- prospective validation against e1RM or performance;
- a forecast-aware cap that accounts for planned-but-not-performed future sessions.

These are documented boundaries, not implied claims; individual MRV is closed and the rest stay
open or deferred.

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
kept as the original idea record.

**Next-phase design:** the final lean non-cardio fatigue-management plan is **closed**
([`docs/NEXT-PHASE-FATIGUE-PLAN.md`](docs/NEXT-PHASE-FATIGUE-PLAN.md)). It used the existing
data plus an sRPE/duration backfill for descriptive calibration and implemented the optional
deload plus four deterministic programme changes, and closed individual MRV as not estimable.
No programme experiments, no individualised MRV and no randomised deload trial. The remaining
deferred items stay listed in §4.19.

### 4.19 Open next actions

Completed and closed items were removed from this list on 2026-10-25; the status table,
[`CHANGELOG.md`](CHANGELOG.md) and [`docs/DECISIONS.md`](docs/DECISIONS.md) keep the record.

| priority | action | status |
|---|---|---|
| P1 | Record **≥3 measured tests per main lift** so `MOD-E1RM-001` can calibrate the formula (the bias question is data-starved, not mechanism-starved) | **next** — `e1rm tests-needed` reports counted tests per main lift against the gate (the Athlete page shows the same table); `e1rm calibrate` shows the ratio and CI; record from the Athlete page, an Exercises row or the post-workout panel |
| P2 | Web authentication + per-user data | **backlog; overkill for now** — CLI-only user provisioning, auth DB, per-user coach DB, login/session/CSRF, password reset, birthdate/gender/timezone onboarding, TLS reverse proxy and home-network host. Temporary no-auth HTTP bind is accepted under `LIM-57` |
| P2 | Parent-variant e1RM ratios | unscheduled; display-only at most (§4.20.2) |
| P2 | Weakness/injury-targeted selection | deferred to after v1.1 / ~April 2027; gates in §4.20.3 and `DEC-SELECT-05` |
| P2 | Main-lift upward-revision ratchet | **deferred, not scheduled** — rejected as a controller in `DEC-E1RM-PLAUS-01`; revisit only if calibration cannot close the bias |
| P2 | Volume-ledger denominator and zero-week coverage | **implemented** — calendar-window denominator, complete-coverage zero-fill, break/deload reset for under-MEV; live profile coverage complete; design in VOLUME-MODULATION-PLAN §14, Q29 |
| P2 | Step 8 effective-set accounting | **implemented and live 2026-10-27** — 0.25 map, target 68.25, landmarks unscaled, effective budget/ledger, raw UI column, `hard`/`effective` switch; rollback one profile change (VOLUME-MODULATION-PLAN §15–16) |
| P2 | Volume modulation: weekly target + session cap | **complete/closed 2026-10-27** — steps 1, 2, 2b, 9a and 9b implemented: read-only budget, per-group accessory budget behind the off-by-default profile flag (`MOD-VOL-003`, constitution 1.17.0), opt-in main-lift `reduce`, compensation preview, and opt-in additive compensation application (`MOD-VOL-004`, executable load required, high-band guarded); **9c-1 drop engine** and **9c-2 identity/UX** implemented (labels/API/UI, startable empty technique, derived review, forecast actual types, migration 0038; `MOD-VOL-005`/constitution 1.18.0); **9c-3 confirmation/settings** implemented (Settings/API, local overlay, per-session confirmation); **7a settings registry/snapshot** implemented (deload reactive constants moved to config); **step 4 settings profile** implemented (append-only versions, budget wiring, snapshots); **7b profile-backed feature wiring** implemented (DUP, deload, volume, readiness, e1RM, plausibility); **step 5 Settings UI/guarded settings** implemented; **5b modality registry/UI** implemented (11 modules, CLI/API/UI parity); **step 6 budget-aware forecast/weekly panels**, **5c remaining modules** and **step 8 effective-set accounting** implemented and live; the plan is closed. Step 3 is a standing Today-page review follow-up, not a plan milestone. The programme forecast now supports 1–5 sessions/week; 4 uses Mon/Wed/Fri/Sun and 5 uses Mon/Tue/Thu/Fri/Sun. Design in `docs/VOLUME-MODULATION-PLAN.md` |
| v1.1 | Fatigue signals: exposure, substitution, advisories | **Phase 0 done 2026-10-28** (five decisions; `docs/FATIGUE-SIGNALS.md`, `docs/EXERCISE-DEMANDS.md`). **Phase 1 done 2026-10-28**: `config/exercises/demands.v1.yaml` populated for **28/63** reachable ids (4 in-scope dimensions at 55.6 % known, 2 `supported` claims, 4 evidence entries). **Rating path done 2026-10-28**: git-ignored `config/exercises/demands.local.yaml` overlay merged over the reviewed file, with `exercise demands report|unrated|set|clear` and automatic rollback on a rejected write (digest covers both files). **Phase 2 done 2026-10-28**: `features/exposure.py` (7/28-day ratio, coverage, gap/deload/break abstention, exposure dedup, per-group ratios), `exposure ratio` CLI, `GET /api/exposure`, Prescribe **Exposure ratio** panel and the Part D low-exposure advisory; report-only, trim not implemented. **Demand display done 2026-10-28**: Exercises rows show `rated/4` and the details dialog shows the profile with confidence, reason, catalogue digest and overlay state; the same form rates or clears a dimension (`POST /api/exercises/demands`, same `set_claim` as the CLI). **Phase 3 done 2026-10-28**: `MOD-EXP-001` (constitution 1.20.0) trims at most one non-essential accessory set per affected group (≤2/session, floor 1) when `athlete_profile.exposure_trim_enabled` is on (default off), skipping main lifts, essential items, readiness cuts and under-MEV additions; `shadow_decision` table + repository exist (append-only triggers). Shadow writes and the review report land in Phase 6 so forecast builds never write rows. **Phase 4 done 2026-10-28**: `prescribe/fatigue_selection.py` suggests at most one accessory substitution when the exposure signal is high, the candidate is A/B comparable, covers the current lift's primary muscles and is rated strictly lower on an in-scope demand dimension; `GET /api/substitution`, the Exercise-selection panel block and `select --fatigue` expose it. Suggest-only; abstains when the trim already acted or the metadata is unknown. **Phase 5 done 2026-10-28**: `features/residual.py` computes the VBT-only execution residual (observed minus prescribed velocity) from linked workout sets, lift-scoped, 84-day window, with the ≥5 signal and ≥20/8-week/two-lift evaluation gates; `residual`, `GET /api/residual` and the Prescribe panel expose it. Shadow only. **Phase 6 done 2026-10-28**: `prescribe/shadow.py` writes exposure + substitution rows only when a prescription is persisted; `features/shadow_report.py` and `shadow`/`GET /api/shadow`/Prescribe **Shadow review** expose counts, abstentions, conflicts and the four gate checks. The gate never enables anything (`activation_allowed: false`); the fatigue-signals specification is fully implemented. |
| v1.1 | Cardio depth and shadow cardio load | planned (§4.13a, Q14) |
| v1.1 | Deeper labelled calibration set | planned (§4.14) |
| future | LLM integration: analyst, explainer, constrained proposer | Iteration 1 planned; Iteration 2 conditional (§4.24; selector retirement is Phase 1b) |
| future | Personalised volume-response model | idea only; shadow/gated (§13, Q28) |
| future | Nicer UI, adherence encouragement and KPIs | placeholder only (§4.23) |

### 4.19.1 Deferred: web authentication and per-user data

**Status: backlog, not implemented. Temporary state: unauthenticated home-LAN HTTP (`DEC-WEB-03`, `LIM-57`).** The owner judged the full design overkill for now; this section is the agreed implementation proposal, not a claim that any part exists.

- **Auth store:** `data/auth.db` with `app_user` (id, username, password hash, `must_change_password`, disabled, timestamps), `session` (hashed token, user id, CSRF token, expiry, last seen) and `login_attempt` for rate limiting. Passwords use scrypt or Argon2id with a unique salt.
- **Private data:** one coach database per user at `data/users/<user-id>/coach.db`; no `user_id` columns added to the clinical schema. The authenticated request resolves the user's database. Move the existing `data/coach.db` into the first user's directory after a backup, never copy it into a shared store.
- **CLI-only provisioning:** `user create`, `user list`, `user enable/disable`, and `user reset-password <username>`. Reset requires **no old password**; it prompts for the new one twice or accepts `--password-stdin`, invalidates all sessions, and may set `must_change_password`. Local shell access is the admin boundary.
- **First user:** provisioned through the CLI with a temporary password, forced change at first login, and onboarding for birth date, gender and timezone. **Never commit the actual username, password, birth date or other profile values**; use placeholders in design docs.
- **Login and sessions:** username + password; server-side session token in the auth DB; `HttpOnly`, `SameSite=Lax`, `Secure` cookie when TLS is active; CSRF token; rate-limited failed logins; logout and password change invalidate sessions; unauthenticated APIs return `401`.
- **Profile onboarding:** require birth date and gender after first login. Store birth date (not age), gender as the agreed dropdown with `prefer not to say`, and IANA timezone. Do not use gender to compute load or volume; age remains wording/priority evidence only.
- **Home access/TLS:** Caddy or nginx terminates HTTPS; the app stays on loopback behind it or gains built-in TLS. Only the configured home hostname/origin is accepted. HTTPS is required before non-loopback credentials are accepted; no public-internet exposure.
- **Isolation and logs:** every API, import, export, backup and log query resolves the authenticated user. The current global Logs page must become per-user or admin-only.
- **Acceptance tests:** CLI create/reset/disable, hash verification, login/logout, forced password change, session expiry/invalidation, CSRF, rate limiting, per-user database isolation, profile onboarding, TLS/origin configuration, and non-loopback access.

### 4.20 Post-review follow-ups  (unscheduled)

Moved out of the strength-programme review so it can close. These are **not** v0.3 work.

1. **Prospective validation gate.** No current candidate. A model may enter a frozen prospective
   period only after it beats the fixed/persistence baseline in a retrospective walk-forward.
   The current continuity and fatigue models failed; they remain fixed/shadow-only. A prospective
   run is 8–12 weeks / 24–36 sessions with no retuning and no load effect.
2. **Parent-variant e1RM ratios.** Evidence review 2026-10-25: a ratio is a relative performance
   profile, **not** a weakness or injury measure. It may later be a descriptive prior/display
   aid with uncertainty, never a silent load conversion or targeting rule. Needs a formal parent
   relation and paired data. No schedule. See
   [PARENT-VARIANT-WEAKNESS-EVIDENCE.md](docs/PARENT-VARIANT-WEAKNESS-EVIDENCE.md).
3. **Weakness/injury targeting.** No positive targeting. A display-only own-history context is
   implemented. A gated testing plan is in
   [WEAKNESS-TARGETING-PLAN.md](docs/WEAKNESS-TARGETING-PLAN.md). Weakness targeting is gated by
   DEC-SELECT-05 (earliest after v1.1 / ~April 2027); injury targeting is unscheduled and remains
   constraint/penalty/ceiling only.

### 4.20.3 Weakness targeting test plan  (plan only; unscheduled)

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

**Open decisions register**

| decision | state | where |
|---|---|---|
| Prospective validation of a future continuity/fatigue candidate | gate only; current candidates rejected | §4.20.1, DEC-VALIDATION-01 |
| Parent-variant e1RM ratios | unscheduled; display-only profile/prior, not weakness | §4.20.2; `PARENT-VARIANT-WEAKNESS-EVIDENCE.md` |
| Weakness targeting | plan only; deferred to after v1.1 / ~April 2027 | §4.20.3, `WEAKNESS-TARGETING-PLAN.md`, Q22, DEC-SELECT-05 |
| Selection A/B boundary (pause/narrow, SSB/high-bar) | dormant policy decision; current default is conservative (A only same exercise) | Q21, docs/SELECTION-COMPARABILITY.md |
| Cardio model | v1.1 | §4.13, Q14 |
| Low-bar competition squat and the weekly spinal cap | **closed 2026-10-25**: counts cost 1; cap raised 3 → 6; bench+hinge uses sumo 2.5 | `DEC-SPINE-05`, Q24, LIM-44 |

### 4.21 Live workout mode  (v0.3, CLOSED 2026-10-23)

**Status: closed.** The approved workout flow is implemented; the only remaining parity exception is
`workout start` in the CLI, because starting requires the full pre-workout readiness form and the
displayed prescription. That is not part of this plan.

| slice | scope | status |
|---|---|---|
| 1 | Schema/state machine, Start form with required readiness, manual sets, timer, duration/sRPE, End/Abandon, API/UI | **done** |
| 2 | Materialise workout sets into `clean_set`/`session`; actual-vs-prescribed comparison | **done** |
| 3 | CSV import inside workout: paste/file, preview, conflicts, RPE→RIR, replace/undo; add recognised new exercises to the plan; optional per-rep CSV detail | **done** |
| 4 | Plan overrides: swap/add/remove exercise and sets | **done** |
| 5 | Deterministic rubric review + human marks; post-processing pipeline | **done** |

Workout sets materialise into `session`/`clean_set` on completion. The end screen compares actual
vs the modified plan and the original prescription, runs the deterministic rubric, and closes on
review marks. Actual-set edit, plan overrides, in-workout CSV import with conflict preview/undo,
and the exercise-details popup are done. The standard dated training export remains the backfill
path. CLI workout commands are partial (no start).

### 4.22 v0.4 — audit, documentation and form closeout  (done 2026-10-25)

**Status:** complete. This release packages the post-v0.3 audit and documentation work; it is
not the cardio release and does not implement weakness targeting.

| workstream | outcome | artifact |
|---|---|---|
| Post-workout form assessment | optional 1–5 per lift; Workout/History; rubric 1.2.0; prospective follow-up opened, still collecting | §4.8, `docs/FORM-ASSESSMENT.md` |
| Fatigue model | Phase-1 diagnostic; full model rejected as a predictor; descriptive only | §4.16, `docs/FATIGUE-FITNESS.md` |
| UI documentation | P0–P4 complete: deep links, help on every panel, Related footers, automated checker | `docs/UI-MAP.md`, `tools/check_ui_docs.py` |
| Parent-variant ratios | evidence review: relative performance, not weakness or injury | `docs/PARENT-VARIANT-WEAKNESS-EVIDENCE.md` |
| Weakness targeting | gated test plan only; no targeting | §4.20.3, `docs/WEAKNESS-TARGETING-PLAN.md` |
| Calibration | 10 high-confidence sessions; every item at n=10; comparable items still uneven | §4.14 |
| Naming/consistency | legacy A/B/C wording removed; docs/test counts reconciled | commits c0c8d80..83c0180 |

**Not in v0.4:** cardio prescription/model, comparable calibration depth, weakness targeting,
parent-ratio implementation, and any new model load effect. Those move to v1.1 or remain
unscheduled.

**v1.1:** see §4.13a. First actions are the cardio data audit, capture completion, impulse
contract, and comparable workout data collection.

### 4.23 Nicer UI, adherence encouragement and KPIs  (future; not scheduled)

**Status:** placeholder only. No implementation date, no approved design, no rule change.

The goal is to make the local UI easier to use and to make adherence visible without turning
training into a streak contest. Planned scope:

- **UI polish:** clearer visual hierarchy, less repetitive form work, better empty/loading/error
  states, and a guided path from readiness to review.
- **Adherence encouragement:** weekly planned-vs-completed view, gentle nudges, and explicit
  handling of planned breaks, illness and deloads so they are not counted as failure.
- **KPI panel:** planned sessions, completed sessions, adherence %, set completion, skipped or
  voided sessions, and volume target hit/miss, with the same definitions exposed by the CLI/API.
  Adherence is descriptive, never a reason to override pain, readiness or a safety rule.
- **No new prescription controller:** KPIs and nudges are read-only; they do not add sets, change
  loads, or punish a legitimate break.

Design reference: [`docs/UI-IMPROVEMENT-PLAN.md`](docs/UI-IMPROVEMENT-PLAN.md). This placeholder
does not schedule that plan; it records the next UI/adherence direction for a future pass.

### 4.24 Future LLM integration workstream  (planned; dependency-ordered after v1.1)

**Status: planned, not implemented, not scheduled to a date.** No prompt, source, schema, API,
UI or training-rule change is part of this workstream yet. The detailed architecture, contracts,
privacy rules, evaluation gates and per-phase acceptance criteria live in
[`docs/LLM-INTEGRATION-PLAN.md`](docs/LLM-INTEGRATION-PLAN.md); this section is the roadmap
summary and must stay consistent with it.

The future architecture separates three capabilities that share one deterministic evidence
layer but have different permissions:

- **Athlete analyst** — read-only progression, programme-status and priority-coverage reports,
  with evidence links and explicit data-quality limits.
- **Programme explainer** — concise and expandable explanations of the actual persisted
  prescription, its modifiers and its warnings; no prescription change.
- **Constrained proposer** — structured structural proposals from canonical ids and allowed
  choices; Python resolves loads and re-validates; the deterministic baseline remains visible;
  the user must explicitly approve; shadow/opt-in rollout only.

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
| 1 | Architecture and contracts: capability boundaries, permissions, context/evidence schema, prompt/schema versions, privacy, iteration boundary | owner approval | **planned** |
| 1b | **Retire the minimal LLM exercise selector** as a separate work item: remove only selector-specific chooser/CLI/API/UI/engine/tests/docs plumbing; preserve shared LLM client/config, narrative/proposal, deterministic selection, taxonomy, comparability, class-B confirmation and history; acceptance in plan §8.2 | phase 1; **independent of the proposer** | **planned** |
| 2 | **New** shared context/evidence builder + athlete analyst: lift progression, programme status, strength/power/longevity review | phase 1; existing features/repositories/provenance | **planned** |
| 3 | Programme explainer: persisted prescription, modifiers, baseline/previous comparison, concise + detailed | phase 2; prescription provenance | **planned** |
| 4 | Constrained proposer in shadow: structured schema, deterministic validation, Python load resolution, baseline comparison; no application | phases 1–3; existing proposal/validator path | **planned** |
| 5 | Opt-in approval + evaluation: diff UI/CLI, explicit approval, provenance, shadow/opt-in gates; no selector work | phase 4; phase 1b; approved gates; privacy review | **planned** |
| exit | Iteration 1 exit gate: selector retired; analyst/explainer accepted; proposer shadow/opt-in gates green; no-LLM path tested | phases 1, 1b and 2–5 | **gate** |

**Dependency order:** v1.1 cardio/calibration work, then phase 1, then 2 → 3 → 4 → 5; phase 1b
runs after phase 1, in parallel with 2/3 if useful, and must finish before the Iteration 1 exit.
No capability code starts before the owner approves its contracts. Phases 4–5 do not run on
sessions already downgraded by a safety modifier (`DEC-LLM-04`); any relaxation is a new
decision.

**Selector retirement is not a refactor and not a proposer dependency.** The deterministic
selection engine, taxonomy, movement-family classifications, comparability rules, validation,
class-B `selection_confirmed` confirmation and history remain. Only the minimal LLM chooser is
removed. The new proposer is decision `DEC-LLM-09`; it is not a continuation of the chooser.

### Iteration 2 — evidence retrieval and advanced architecture (conditional)

Iteration 2 begins only after the Iteration 1 exit gate. It starts with a needs assessment, not
with technology adoption. RAG, semantic/hybrid retrieval, a vector database, advanced
orchestration/tool use and an owner-operated MCP server over Tailscale are candidates, not
requirements; any one may be rejected. A vector database is permitted only if the retrieval
benchmark shows a simpler deterministic/keyword or hybrid approach is insufficient. The MCP
server is owner intent only: Tailscale is network reachability, not application authentication,
and no app integration is implemented or approved.

| phase | scope | depends on | status |
|---|---|---|---|
| 6 | Needs assessment: recurring gaps, trusted corpus, retrieval requirements, simpler alternatives, MCP/Tailscale tool boundary and authorization, benchmark, cost/latency/privacy/maintenance case | Iteration 1 exit gate; owner authorisation | **conditional** |
| 7 | Advanced component trial: one approved component at a time (RAG, hybrid retrieval, bounded orchestration or MCP transport), off by default, baseline comparison | phase 6 decision; privacy review | **conditional** |

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

## 5. Known gaps and risks

This section keeps **no list**. Every accepted limitation is registered with an id, a status and
a "revisit when" in [`docs/LIMITATIONS-REGISTER.md`](docs/LIMITATIONS-REGISTER.md); forward-looking
work lives in §4.19 and the v1.1 plan in §4.13a. The table that used to sit here was folded into
that register on 2026-10-26 — `LIM-45`–`LIM-49` are its new rows, and the rest already existed
(`LIM-07`/`LIM-10` duration and timestamps, `LIM-14` spinal cost, `LIM-24`/`LIM-43` e1RM bias).
Two rows that described *planned work* were not limitations and did not move: calibration
comparability is tracked in §4.14 and the cardio impulse in §4.13a A2/A3.

## 6. Idea backlog (not approved, not scheduled)

Recorded so good ideas are not lost, explicitly **not** commitments. Delivered ideas were
removed on 2026-10-25; their record is in `CHANGELOG.md`.

- `sets_per_muscle_group_per_week` feature, so volume is audited in sets rather than sessions.
- Readiness composite driven by `metric_definition` (not delivered: the table is used for
  measurements; dynamic readiness needs weight/role/baseline metadata and shadow validation).
- Rotation scoring split by session provenance (app-assigned vs self-directed).
- Grip-strength left/right asymmetry as a readiness input and a unilateral-work trigger.
- Per-lift manual velocity overrides with expiry.
- Top set + back-off sets — **evidence review only**; a specific overview plus indirect
  high-load/multiset and autoregulation evidence, but no direct trial against the current
  4-5 × 3-5 @ RIR 2-3 prescription. Do not replace the programme yet
  ([TOP-SET-BACKOFF-EVIDENCE.md](docs/TOP-SET-BACKOFF-EVIDENCE.md)).
- Personalised volume-response model — future, shadow-only: estimate productive/tolerable
  volume per group/lift with calibrated uncertainty and a pre-registered prospective gate; no
  prescription change until validated. Fixed budget and safety guards remain authoritative.
  Idea only; see `docs/VOLUME-MODULATION-PLAN.md` §13 and Q28.
- Nicer UI, adherence encouragement and KPI panel (placeholder §4.23; not scheduled).
- LLM integration workstream (planned §4.24; analyst, explainer, constrained proposer; not started).
- Wider proposal licence (more than one increment on the menu) once the menu has proved itself
  in real sessions.

## 7. How to change this roadmap

- Phase status changes go in the table, in the same commit as the work.
- New phases get a number and an acceptance criterion before any code is written.
- Anything that changes a rule, a threshold that affects a load, or a recorded decision must
  also append to [`docs/DECISIONS.md`](docs/DECISIONS.md).
- Personal goals, injuries and preferences are **not** recorded here — this repository is
  public. They live in the git-ignored `private/`.

## Related

- **UI surface:** [docs/UI-MAP.md](docs/UI-MAP.md)
- **Evidence:** [docs/REFERENCES.md](docs/REFERENCES.md)
- **Decisions:** [docs/DECISIONS.md](docs/DECISIONS.md)
- **Open questions:** [docs/OPEN-QUESTIONS.md](docs/OPEN-QUESTIONS.md)
- **Roadmap:** this file
