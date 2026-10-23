# ROADMAP

The resume point for this project. If you are picking this up cold — human or agent — read
this file first, then [`AGENTS.md`](AGENTS.md) for the rules of the codebase.

Last updated: 2026-10-20 · **v0 complete, v0.1 done, v0.2 done, v0.3 in progress** · version `0.3.1-dev` · **604 public tests** (619 with the 15 private integration tests)

---

## 1. How to resume

```bash
cd strength-training-app
.venv/bin/python -m pytest            # 619 locally, including private integration
.venv/bin/python tools/profile_data.py   # data profile (needs data/raw/)
.venv/bin/python tools/baseline.py       # strength baseline
```

Then read, in order:

1. [`USER-GUIDE.md`](USER-GUIDE.md) — how to use what exists
2. **this file** — where we are and what is next
2. [`docs/DECISIONS.md`](docs/DECISIONS.md) — decisions that are expensive to reverse
3. [`docs/OPEN-QUESTIONS.md`](docs/OPEN-QUESTIONS.md) — what is still ambiguous, with defaults
4. [`docs/V0-SCOPE.md`](docs/V0-SCOPE.md) — the agreed scope and its exclusions
5. [`AGENTS.md`](AGENTS.md) — invariants, layering, definition of done

**Resume rule:** update the status table below in the same commit as any phase change. If the
table disagrees with the code, the table is wrong — fix it before adding features.

## 2. Status

| # | Phase | Status | Artifacts |
|---|---|---|---|
| 0 | Design + approval | **done** | `docs/ARCHITECTURE.md`, `DATA-MODEL.md`, `DATA-QUALITY.md`, `RULES-FORMAT.md`, `VBT-CALIBRATION.md`, `MODULE-LAYOUT.md`, `V0-SCOPE.md`, `OPEN-QUESTIONS.md`, `SANITY-CHECKS.md`, `TRAINING-GUIDELINES.md` |
| 1 | Ingest (clean + sessions) | **done** | `ingest/clean.py`, `ingest/sessions.py`, `config/templates/days.v1.yaml` |
| 2 | Derived features + VBT calibration | **done** | `features/derived.py`, `features/baseline.py`, `features/vbt_calibration.py`, `domain/e1rm.py`, `domain/load.py`, `domain/rir.py` |
| 3 | Store (SQLite, append-only) | **done** | `store/migrations/0001_initial.sql`, `store/db.py`, `store/repositories.py`, `store/importer.py` |
| 4 | Rules loader + policy engine | **done** | `rules/loader.py`, `registry.py`, `context.py`, `policy.py`; predicates for all five rules |
| 5 | Prescription engine (Day A/B/C) + deterministic fallback | **done** | `prescribe/templates.py`, `config.py`, `loads.py`, `engine.py`, `fallback.py`; `config/thresholds.v1.yaml` |
| 5.5 | Athlete state — DATA-MODEL §11 tables | **done** | `store/migrations/0003_athlete_state.sql`, `prescribe/constraints.py`, `cli state` / `cli block`; hard constraints veto |
| 6 | Critique rubric + trace | **done** | `critique/facts.py`, `critique/rubric.py`, `trace/run.py`; 6 measurable items + 2 unmeasured |
| 7 | LLM layer (narrative only) | **done** | `agents/client.py`, `config.py`, `narrative.py`; `config/llm.example.toml`, `tools/llm_check.py` |
| 8 | Backtest harness + labelled eval set | **done** | `eval/harness.py`, `eval/labels.py`, `tools/eval_prepare.py`, `tools/backtest.py`; 5 high-confidence sessions, 75% agreement, MAE 0.20 |
| 9 | CLI (`run` / `review` / `calibrate` / `import`) | **done** | `cli.py`; prescriptions persisted; `review --pending` catches up; calibration loop closed |
| v0.2 | Input flexibility + programme view | **done** | readiness entry/score/devices/settings + gate (§4.1/4.9), continuity (§4.6), injury signal (§4.7), local web UI with import/state editing/Programme/Cardio/Terminal/calibration (§4.10/4.11), cardio capture + weekly summary (§4.13), labelled set (§4.14), session RPE/length, recent stress, per-lift readiness, e1RM calibration + bounded correction + age decay |
| v0.3 | Strength/data depth | **in progress** | manual logging (§4.2), adapters (§4.3), learned readiness weights evaluated and closed (§4.9), LLM/manual-logging parity (§4.11), continuity calibration (§4.12; calibrated factor rejected, fixed fallback), labelled set depth (§4.14), exercise selection apply + comparability + display-only history (§4.15; weakness/ratios in §4.20), strength fitness-fatigue shadow model (§4.16; retrospective rejected), rolling session types / upper-body balance / set reduction / volume management v1 / under-MEV accessory progression / warm-up ramp / 3RM cadence / descriptive progress dashboard (§4.17), live workout foundation (§4.21) |
| v0.4 | Cardio prescription and model | **planned** | cardio prescription and cardio impulse/fatigue model (§4.13 remaining) |
| v0.5 | Video analysis | **planned** | video capture/analysis and its UI parity (§4.8, §4.11 video part) |
| v0.1 | Complete | **done** | 3.1-3.4, 3.6-3.7 done; 3.5 video moved to v0.2; 3.8 labelled set moved to §4.14 |
| — | UI | **local web done; hosted UI deferred** | `strength_coach/web/`, `docs/WEB-UI.md`, `http://127.0.0.1:8000` |

### Version plan (2026-10-20)

| version | boundary | status |
|---|---|---|
| v0.2 | readiness, continuity, injury, web UI, cardio capture, measurements, session RPE/length, recent stress, per-lift readiness, e1RM calibration/decay | **done** |
| v0.3 | everything strength/data-depth that is not cardio or video: manual logging, adapters, LLM/manual-logging parity, continuity calibration, deeper labelled set, exercise selection, strength fitness-fatigue model | **in progress** |
| v0.4 | everything cardio: prescription, cardio impulse model, cardio fatigue interaction | **planned** |
| v0.5 | everything video: capture, analysis, UI parity | **planned** |
| future | LLM-guided suggested programme (§4.18) | **idea only; not scheduled** |

**Rule:** cardio work does not enter v0.3; video work does not enter v0.3 or v0.4. The strength
model (§4.16) is strength-only and stays in v0.3.

### What works end to end today

A real export can be cleaned, flagged, quarantined, grouped into sessions, given a programme
day guess, calibrated for velocity targets, and **persisted**: one import writes `raw_row`,
`clean_set`, `session` and `quarantine` inside a replayable `run`/`run_event` trace, and
re-importing the same file writes no duplicate rows. The constitution can now be evaluated
against that history: `rules` parses the YAML into hash-bearing `Rule` objects, the registry
supplies one predicate per `check.fn`, and `policy` returns a verdict per rule with citable
evidence. A session for **any programme day (A, B or C) is now generated**: loads solved from recent e1RM (or double
progression for accessories), rounded down to the athlete's 0.5 kg microplates, with
MOD-FAT-001 reducing loads when sleep or energy is <= 2. Every item cites a rule id and a
stored set, and the prescription refuses to be executable if a load, the RIR window, the
erector-day rule or the weekly spinal cap would be broken. A performed session can now be
**critiqued**: six rubric items score it (RIR adherence, progression adherence, weekly spinal
cost, essential work, redundancy, rotation) with evidence references, and two are stored as
`measurable = 0` because the export cannot support them (session duration, within-set velocity
loss). The critique is persisted append-only inside a `run` trace. An **optional narrative** can explain
either artifact: the model receives the facts as JSON, may not compute, and its output is
recorded as a `run_event` rather than written into a prescription or a score. With no model
configured (`NullLLM`) the run is structurally identical and loses only the prose. There is
**the full v0 slice runs**: `strength-coach run --date` imports if needed, critiques the
last session, prescribes the date, persists both inside a run trace, and prints a rationale
that cites a rule or a stored fact. `review` is the calibration loop: it shows the session
beside the rubric's scores, takes marks, stores them append-only, and reports running
agreement immediately. Two of the three marks are reconstructed from memory and excluded;
on the one remembered session, 60% of items agree within ±0.25 (`DEC-EVAL-03/04`).

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
joins the `primary_goal` enum, and training-log gaps are recorded as **non-adherence**, never
as symptoms.

### 3.2 Days A and C  (done)

Depends on 3.1. The SSB question (H1) is answered: the bar is available. The erector-ramp
anchor is also settled in principle — **the athlete declares the official start, and can reset
it at any time** (`DEC-RAMP-01`), so the anchor is stored, never inferred.

Scope: Day A and Day C templates; `block start [--date]` command that sets or resets week 1 as
a new profile row (never an edit); **a reset restarts the ramp at week 1** (`DEC-RAMP-02`), not
just the calendar; the ramp reads that row.

Acceptance: a template per day with its own essential lifts; `PRG-SCHED-001` enforced on both
(no erector work on the hinge day, erector work allowed on A/C); a golden prescription per
day, in the same style as `tests/fixtures/golden_day_b.yaml`.

Delivered: Day A (squat-led) and Day C (bench-led) templates with erector + accessory work;
`run --day A|B|C`; golden fixtures for both days. Core work was added on 2026-10-20
(`ab_wheel` on A, `hanging_leg_raise` on C, `DEC-CORE-01`; `docs/CORE-TRAINING.md`). Day A
opens with a power slot (`box_jump`, `DEC-POWER-01`) and Day B with a vertical-pull variant
slot (`pull_up` / `lat_pulldown`, `DEC-PULL-01/02`; `docs/LONGEVITY-REVIEW.md`).
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
modified Day B session, subject to the same policy engine that judges a performed one. The
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

### 3.5 Video analysis — moved to §4.8

Video is a v0.2 feature; the full scope and its privacy constraints live in §4.8.

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
  (3.6 covers portability; §4.8 covers opt-in video).
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
[`docs/READINESS.md`](READINESS.md); the changeable parts are config in
`config/readiness.v1.yaml` (`DEC-READINESS-04`).

### 4.2 Logging workouts three ways  (v0.3, partial: workout foundation)

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

**Status 2026-10-20:** the live workout foundation exists — Start from a prescription with the
seven required readiness fields, manual set add/remove, measured/editable duration, sRPE or
not-recorded, end/abandon, and API/UI. It stores draft `workout_set` rows; **materialising them
into `clean_set`/`session`, import merge, plan overrides and review/rubric are still pending**.

Acceptance: a manually logged session is indistinguishable downstream from an imported one
(same tables, same critique); concluding a workout also catches up unreviewed sessions via
`review --pending`; duration is stored when given and stays `unavailable` when not
— never estimated; the rubric scores duration only when it exists.

### 4.3 Column-mapping adapters for other exports  (v0.3)

`utils.io_utils` fixes the column names, so another app's export would need code. v0.2 adds a
mapping file (source column → canonical column, unit, sentinel policy) and a small adapter
registry.

Extra columns are preserved verbatim in `raw_row` and reported, never silently dropped
(AGENTS.md §3.9). A missing *required* column is an explicit error, not a silent null.

Acceptance: a synthetic second-format CSV imports through a mapping file with no code change;
an unmapped required column fails loudly; extra columns survive in `raw_row`; re-import stays
idempotent.

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

Acceptance: `programme --weeks N` prints a dated session-type forecast with legacy A/B/C labels; `--start-session-type T` (or deprecated `--start-day`) sets the first session; `--remaining` starts today;
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

### 4.8 Video analysis (LLM) — moved to v0.5

Allow a video to be attached to a session or a single set for a vision-capable model to
comment on: depth, bar path, tempo, rep count. It is a **commentary** feature, and the
constraints matter more than the feature.

- **Privacy first.** Video is personal data. Files live under `private/` (git-ignored), are
  never committed, and never enter `data/coach.db` as bytes. Sending a video to a hosted
  model is an explicit per-video opt-in, and the output must say that the file left the
  machine. A local model keeps it local.
- **No numbers, no vetoes.** The analysis is stored as a `run_event` (new kind,
  `video_analysis`) with the file hash and model id. It cannot change a load, a rubric score
  or a policy verdict (AGENTS.md §3.2-3.3).
- **The log stays authoritative.** If the model says "8 reps", that is a comment; the logged
  set remains the record.
- **No default dependency.** Frame extraction needs ffmpeg or provider-side video support;
  decide per provider rather than adding a runtime dependency for everyone.

Acceptance: attaching a video produces exactly one event and changes no artifact; a run with
no video, or with `--llm off`, stays byte-identical; video bytes never appear in the
repository; every claim is labelled commentary.

Open questions: which sets get video, retention period, and per-provider capability.

Why v0.2 rather than v0.1: it needs a privacy decision (sending personal video to a hosted
model), a provider-capability check, and a storage/retention policy. None of those belong in a
version whose remaining work is calibration and documentation.

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
- Pages: Today, Prescribe, Programme, Review, Readiness, Import, Athlete, Terminal, Docs.
- The API only serialises and routes; every load/score/warning still comes from the core.
- Tests cover the API round trips, docs rendering and the readiness/review writes.

Done: import, state editing, Programme, Terminal. Remaining: LLM proposals/chat, manual
logging, video.

### 4.11 Web UI parity  (v0.3 for LLM/manual logging; video part v0.5)

**Workout mode exception:** the live workout flow is UI/API first (§4.21); CLI commands for
start/add-set/end are not built yet and must be added before parity is claimed.

The local UI covers Today, Prescribe (rolling session types), Programme, Review, Readiness, Import, an editable
Athlete page, an editable **Exercises** catalogue, Terminal and Docs. This item brings the remaining interactive CLI actions into the browser. The CLI stays
as the automation interface; the UI must call the same core functions, never re-implement them.

Planned surfaces, in suggested order:

1. **Import** — **done**. Upload the training and readiness CSVs, show inserted/existing/
   quarantined counts; files stay in memory and are stored in SQLite.
2. **State editing** — **done**. Profile, constraints, suitability ratings, e1RM overrides,
   strength tests, block start and symptoms; append-only, with an exercise picker and the
   current tables shown beside the forms.
3. **LLM proposals** — a proposal view for `run --propose`: proposed changes, citations and
   warnings, explicit accept/reject, never a numeric field. The engine still validates and may
   veto. Proposal history stays visible.
4. **Manual workout logging** (4.2) — per-set entry, conclude/log, then the review catch-up for
   previous sessions.
5. **Programme view** (4.4) — **done**. Rolling session-type horizon with recomputation on the day; legacy A/B/C is context only.
6. **Video** (4.8) — opt-in attachment, privacy warning, commentary only, never a score.
7. **Readiness settings** (4.9) — **done**. Baseline window, minimum readings, slopes and
   weights; shadow baseline report.
8. **Terminal** — **done**. One `strength-coach` command, no shell; bound to the UI database.
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
- the terminal executes only `strength-coach`, never a shell, and refuses `web`, `--db` and
  interactive `review`.

Acceptance: every interactive CLI action has a browser path or a documented exception; the
same inputs produce the same database rows and warnings through either surface; a failed
action leaves no partial write; API tests cover each new write; no load, score or threshold is
computed in the browser.

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

**Retrospective walk-forward (2026-10-20):** 12 returns; calibrated-factor ratio MAE 0.150
vs fixed-rule 0.128, so the calibrated factor **lost** and the fixed fallback stays in use.
This is retrospective, not prospective. See [RETROSPECTIVE-VALIDATION.md](docs/RETROSPECTIVE-VALIDATION.md).

Acceptance: `strength-coach continuity` and `GET /api/continuity` show observed returns versus
the fixed rule; the minimum-data rule is explicit; a sparse band keeps the fixed factor; a
well-observed band applies the calibrated factor; the prescription cites the applied rule.

### 4.13 Cardio workouts and an impulse fatigue model  (capture v0.2 done; cardio model v0.4; strength model is §4.16)

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

### 4.14 Labelled calibration set  (v0.3; moved from v0.1 3.8)

No code. Continue reviewing sessions while they are fresh; the rubric report needs roughly ten
*remembered* sessions per item before changing a definition or weight (DEC-EVAL-03,
DEC-EVAL-04). Reconstructed marks are stored but excluded from agreement.

Current state: 5 high-confidence sessions, 75% agreement, MAE 0.20; rotation is the weak item.
The web Review page has the **Run rubric calibration** button; the CLI remains
`strength-coach calibrate`.

Acceptance: ten high-confidence marks per item before a rubric change; every review appends,
never edits; the report states the sample size and excludes low-confidence marks.
### 4.15 Exercise selection adapted to readiness and fatigue  (v0.3; apply + comparability done)

**Status: apply + comparability implemented 2026-10-20; tax metadata, accessory candidates and symptom/readiness suggestions implemented. Plan closed at suggestions + explicit apply; automatic withholding deferred to the 8-week/30-session review.** The selector now carries tax metadata and `symptom` / `stress_readiness` triggers; substitutions remain explicit. See [`READINESS-EXERCISE-SELECTION-PLAN.md`](docs/READINESS-EXERCISE-SELECTION-PLAN.md) and `DEC-SELECT-06`.

**Current implementation:** `prescribe/selection.py` ranks the configured and catalogue variants per slot from readiness, recent stress, rotation, preference and the cached fitness-fatigue state; constraints and `can_do: false` exclude a candidate; injury is a penalty, not a veto. Candidates carry an A/B/C comparability class: A applies automatically, B requires confirmation, C is hidden by default and never automatic; the selected lift's own history is always used. A display-only own-history e1RM ratio is shown, but it does not enter the score. See `DEC-SELECT-03` and [SELECTION-COMPARABILITY.md](docs/SELECTION-COMPARABILITY.md). It is exposed as `strength-coach select` and a Prescribe panel. With the explicit **Apply selection** toggle, the chosen candidate replaces the slot exercise and the load is re-solved from that lift's own history (`MOD-SELECT-001`). Without the toggle nothing changes. All synthetic raw variant names were canonicalised and their history rewritten (migration 0014, 114 entities, 3,607 audited remaps; migration 0015 split close-grip pulldown); trap-bar date-scoping and back-extension equivalence are preserved.

**Weakness/injury tailoring — deferred.** No positive weakness/injury targeting. Injury remains
an exclusion/penalty/ceiling. Earliest review is after v0.5 and ~April 2027, and only with 12
sessions per target lift over 12 weeks, a pre-registered own-trend metric, a retrospective
baseline win, and an opt-in N-of-1/alternating test; injury targeting remains unscheduled.
See [WEAKNESS-INJURY-SELECTION.md](docs/WEAKNESS-INJURY-SELECTION.md), `DEC-SELECT-04/05`, Q22.

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

**Status: shadow prototype implemented 2026-10-20; retrospective check failed 2026-10-20.** `features/fatigue_fitness.py` fits a
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
   a frozen-parameter prospective test on future sessions. **Retrospective walk-forward:** 25 lift-session predictions, relative MAE 0.158 vs persistence 0.074 (skill −112%); the model lost, so no load or adoption follows. Volume has no predictive model; selection has no counterfactual.
3. **Prospective validation**: freeze parameters, predict held-out sessions, compare with a
   fitness-only and a readiness-only baseline.
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

| type | legacy label | main work | upper body | direct erector |
|---|---|---|---|---|
| `squat` | A | SSB squat + power | bench support + row | yes |
| `hinge` | B | trap-bar deadlift | narrow/pause bench + row + pull | no |
| `bench_squat` | C | bench + squat support | overhead press + row | no |
| `bench_hinge` | C | bench + single-leg RDL | overhead press + row + pull | no |

The rolling rule targets two squat, two hinge and two bench-emphasis sessions per six, uses the
recent `day_guess` history plus forecast choices, and falls back to the preferred emphasis
cycle when the counts are tied. A missed session shifts the deficit; it does not advance a
calendar. A/B/C remain as legacy labels for historical rules and explicit overrides.

**Balance changes:** every session includes bench or another upper-body press/pull, plus a
horizontal row. After the 2026-10-20 review, squat-emphasis SSB is 5×3–5, the bench+squat
squat support is 4×3–5, and the trap-bar hinge is 5×3–5. This restores ~7 squat sets/week and
raises heavy hinge to ~5 sets/week without a second heavy exposure; back extension stays at 3
sets/week. The hinge gets a second exposure through the single-leg RDL support on the
bench+hinge session, without stacking another high-fatigue spinal lift. Only the squat-emphasis
session carries direct erector work, keeping a normal week at squat 1 + hinge 2 = 3 against the
spinal cap. Poor readiness can remove one accessory or main-lift set (`include_essential: true` by default),
and the Readiness page exposes that **volume valve**.
A weekly **hard-set ledger** reports sets per movement pattern against broad MEV/MAV/MRV
landmarks; non-essential sets are trimmed only when the recent week plus the proposed session
exceeds MRV (`MOD-VOL-001`). Under-MEV adds one accessory set after three weeks below MEV
(`MOD-VOL-002`), while main lifts are unchanged by that rule; poor readiness can remove one
main-lift or accessory set. Main lifts carry a 50/70/85 warm-up ramp, and `test --status`
reports the 10-week 3RM/5RM cadence. Power work is bodyweight/implement-only.

**Acceptance (done):** session templates parse; every session has a row and an upper-body
push/pull; hinge sessions contain no direct erector work; the two-week sequence balances
squat/hinge/bench; legacy A/B/C still resolve for history; the rolling forecast and UI expose the
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
**Status:** idea only; no implementation, no phase assigned.

**Next-phase design:** the final lean non-cardio fatigue-management plan is **closed**
([`docs/NEXT-PHASE-FATIGUE-PLAN.md`](docs/NEXT-PHASE-FATIGUE-PLAN.md)). It used the existing
data plus an sRPE/duration backfill for descriptive calibration and implemented the optional
deload plus four deterministic programme changes, and closed individual MRV as not estimable.
No programme experiments, no individualised MRV and no randomised deload trial. The remaining
deferred items stay listed in §4.19.

### 4.19 Consolidated next actions

| priority | action | status |
|---|---|---|
| P1 | Scheduled deload / broader fatigue-management policy | done — `DEC-PROGRAMME-05` |
| P1 | 3RM/5RM calibration cadence and explicit warm-up prescription | done — 10-week reminder + 50/70/85 ramp |
| P2 | Parent-variant e1RM ratios | moved to §4.20, unscheduled |
| P2 | Weakness/injury-targeted selection | display-only context done; targeting deferred — earliest after v0.5 / ~April 2027; gates in `DEC-SELECT-05` |
| P2 | Strength-review implementation closeout | **review closed**; future work in §4.20 |
| P2 | Individualized MRV / main-lift volume experimentation | **closed** — not estimable; no experiment (`DEC-VOLUME-04`) |
| P2 | Prospective validation of continuity, volume, selection and fatigue models | moved to §4.20 — no candidate; current models failed the retrospective baseline |
| P1 (v0.3) | Live workout mode | **partial** — start/end/manual sets, materialisation, plan overrides, comparisons and rubric/review done; import pending |
| P1 (v0.3) | Manual workout logging and import adapters | not started |
| P1 (v0.3) | LLM/manual-logging parity | not started |
| P2 | Learned readiness weights | **closed** — fixed weights retained (`DEC-READINESS-10`) |
| P1 (v0.3) | Deeper labelled calibration set | in progress |
| v0.4 | Cardio prescription and cardio fatigue interaction | planned |
| v0.5 | Video capture/analysis and UI parity | planned |
| future | LLM-guided suggested programme (§4.18) | idea only |

### 4.20 Post-review follow-ups  (unscheduled)

Moved out of the strength-programme review so it can close. These are **not** v0.3 work.

1. **Prospective validation gate.** No current candidate. A model may enter a frozen prospective
   period only after it beats the fixed/persistence baseline in a retrospective walk-forward.
   The current continuity and fatigue models failed; they remain fixed/shadow-only. A prospective
   run is 8–12 weeks / 24–36 sessions with no retuning and no load effect.
2. **Parent-variant e1RM ratios.** Needs a formal parent relation, enough paired sessions and a
   validated ratio with uncertainty. It is a prior/display aid, never a silent load conversion.
   No schedule.
3. **Weakness/injury targeting.** No positive targeting. A display-only own-history context is
   implemented. Weakness targeting is gated by DEC-SELECT-05 (earliest after v0.5 / ~April
   2027); injury targeting is unscheduled and remains constraint/penalty/ceiling only.

**Open decisions register**

| decision | state | where |
|---|---|---|
| Prospective validation of a future continuity/fatigue candidate | gate only; current candidates rejected | §4.20.1, DEC-VALIDATION-01 |
| Parent-variant e1RM ratios | unscheduled; needs paired data and validation | §4.20.2 |
| Weakness targeting | deferred to after v0.5 / ~April 2027 | §4.20.3, Q22, DEC-SELECT-05 |
| Selection A/B boundary (pause/narrow, SSB/high-bar) | dormant policy decision; current default is conservative (A only same exercise) | Q21, docs/SELECTION-COMPARABILITY.md |
| Cardio model | v0.4 | §4.13, Q14 |
| Fatigue-plan backfill UI, phase cutoff, report format, one-month check | open; decide when that plan resumes | docs/NEXT-PHASE-FATIGUE-PLAN.md §9 |

### 4.21 Live workout mode  (v0.3, in progress)

Phased implementation of the approved workout flow:

| slice | scope | status |
|---|---|---|
| 1 | Schema/state machine, Start form with required readiness, manual sets, timer, duration/sRPE, End/Abandon, API/UI | **done** |
| 2 | Materialise workout sets into `clean_set`/`session`; actual-vs-prescribed comparison | **done** |
| 3 | Import staging inside workout; overwrite/preview/undo; Exercise catalogue completeness | next |
| 4 | Plan overrides: swap/add/remove exercise and sets | **done** |
| 5 | Deterministic rubric review + human marks; post-processing pipeline | **done** |
| 6 | Backfill import handling; duplicate/overlap warnings | pending |

Workout sets now materialise into `session`/`clean_set` on completion, so reports, e1RM and
volume see them. The end screen compares actual vs the modified plan and the original
prescription, runs the deterministic rubric, and closes on review marks. Plan overrides are done;
import remains.

## 5. Known gaps and risks

| gap | impact | mitigation / status |
|---|---|---|
| No persistence | cannot replay a past day; work is lost between runs | **resolved** — `run`/`run_event` trace + append-only tables (phase 3) |
| Erector ramp has no anchor | `PRG-EREC-001` returns `unknown`; Day A/C cannot be prescribed safely | rule implemented; `unknown` names both missing inputs (`OPEN-QUESTIONS` Q3, Q4) |
| No athlete state | no injury, goal or preference can veto a prescription | **resolved** — §11 tables and `state` command |
| No symptom input | back-flare modifier and the ramp's stability gate cannot run | **resolved** — pre-session 0-3 input, `symptom_log`, `MOD-BACK-001` |
| Imported sessions have no timestamps | imported duration unmeasurable; two imported sessions on one date indistinguishable | workout mode measures duration; imports remain date-only (`OPEN-QUESTIONS` Q5) |
| Only Day B can be prescribed | Days A/C are blocked by the erector-ramp anchor (Q3), the SSB question (H1) and the missing §11 tables | **resolved** — Days A/B/C prescribable; the ramp anchor is optional and `unknown` is explicit |
| Only ~45% of dates map to a programme day | day-specific rules cannot be scored on the rest | day inference reports explicit reasons; do not force a bucket |
| Velocity is per-set only | within-set velocity loss not computable | labelled decay proxy; `DEC-VELOCITY-01`; post-hoc rep-level decision in `docs/VBT-REP-LEVEL.md` (`DEC-VBT-03`) |
| Rubric calibrated on **five high-confidence sessions** | 75% agreement, MAE 0.20; rotation is the weak item (40%, n=5); two old marks are reconstructed and excluded | `DEC-EVAL-04`; needs ~10 remembered marks per item before changing weights |
| Spinal cost ignores load and effort | a 50 kg good-morning at RIR 3 counts the same as a maximal one | ASSUMPTION-02 / Q8; a weighted-by-e1RM or RIR version needs the athlete's decision |
| VBT targets not prescribed | a prescription carries no `velocity_target` | **resolved** — 22 targets where trustworthy; trap bar withheld; `DEC-VBT-02` |
| ACWR contested | cannot be a hard rule | advisory only; `DEC-ACWR-01` |

## 6. Idea backlog (not approved, not scheduled)

Recorded so good ideas are not lost, explicitly **not** commitments:

- `sets_per_muscle_group_per_week` feature, so volume is audited in sets rather than sessions.
- Readiness composite with a `metric_definition` table so new metrics need no code change.
- Rotation scoring split by session provenance (app-assigned vs self-directed).
- Grip-strength left/right asymmetry as a readiness input and a unilateral-work trigger.
- Per-lift manual velocity overrides with expiry.
- Regime-change detection (a lift's volume collapsing while a substitute rises).
- LLM-guided suggested programme under the §4.18 guardrails (idea only).
- Wider proposal licence (more than one increment on the menu) once the menu has proved itself
  in real sessions.
- ~~A declared 3RM/5RM test session.~~ **Delivered in v0.1** (`DEC-TEST-01`): `strength-coach
  test`, 3RM/5RM by default, `--max` for a confirmed 1RM. Evidence in `docs/TRAINING-DYNAMICS.md`.
- ~~Rep-scheme menu.~~ **Delivered** (`DEC-REPS-01`): named schemes including `maximal`
  1-3 (main lifts only, not the hinge).
- ~~Weekly undulation (DUP).~~ **Delivered** (`DEC-UNDUL-01`): 4-week cycle keyed to the
  declared anchor, config-disabled by default when no anchor exists.

## 7. How to change this roadmap

- Phase status changes go in the table, in the same commit as the work.
- New phases get a number and an acceptance criterion before any code is written.
- Anything that changes a rule, a threshold that affects a load, or a recorded decision must
  also append to [`docs/DECISIONS.md`](docs/DECISIONS.md).
- Personal goals, injuries and preferences are **not** recorded here — this repository is
  public. They live in the git-ignored `private/`.
