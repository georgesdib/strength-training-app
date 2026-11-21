# ROADMAP — completed work

This is the completed/historical half of the roadmap, split out so the live [ROADMAP.md](ROADMAP.md)
stays readable. It is an audit and past-deliverable record: agents should not read it by
default, only when the task is an audit or asks what was delivered. Section numbers are
preserved; links still resolve from the repository root.

---

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

**Withdrawn 2026-11-17:** the CLI proposal surface described below was removed for CLI/UI
parity. It is retained here as the historical record; no LLM write path remains.

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
`run` and the reporting commands with no code change and no access to the first database; no
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

### 3.7a VBT target analytics  (released as v1.4.0 on 2026-11-13)

Implemented in four reviewed phases, server and local web UI only:

- **Phase 1** — structured, frozen target metadata (band, rep count, RIR band, scope/family,
  sample, method version, calibration id) in plan JSON; deterministic calibration provenance;
  legacy plans stay partial; no migration and no iOS model change.
- **Phase 2** — Prescribe and Active Workout target visibility, dynamic set-group/rep/RIR
  applicability checks and compact post-set feedback; no coaching or termination rule.
- **Phase 3** — completed-workout and History per-set target-versus-actual comparison from
  corrected `clean_set` rows, original-plan fallback for removed items, override priority,
  per-exercise aggregates and explicit exclusion reasons.
- **Phase 4** — Performance VBT dashboard with frozen-target cohorts split by exercise,
  scope/family, rep count and target RIR band; weekly residuals, band/RIR evidence,
  deterministic descriptive bootstrap intervals, reused 5-observation and 20-observation/8-week
  gates, per-set drill-down and separate within-set rep-velocity drift. No cross-exercise score,
  load model, prescription change or autoregulation.

Verification: VBT/unit/API/frontend tests, the default suite, optional regression/slow suites,
docs audit and ruff are green on the final tree. Data/raw integration is intentionally not run.
No schema migration was added. The existing Progress VBT residual remains the shadow-only Part B
signal; the Performance dashboard is a separate descriptive analysis.

### 3.8 Labelled set — moved to §4.14

This is now a v0.2 item; the content and acceptance are in §4.14. v0.1 is complete.

### 3.9 Deliberately not planned

- A UI (deferred by request).
- Several athletes in one database, or a hosted service: local-first, one database per person
  (3.6 covers portability; video is descoped).
- RAG over the programme: rules are cited by id, and exact lookup beats semantic search here.
- Automatic rubric retuning: the report proposes, a person decides.

## 4. Closed v0.2-v1.x subsections

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
and the rubric's (now retired) `SESSION_DURATION` used to flip from `measurable = 0` to a real
score — the first time that item could move.

Manual entry must pass the same gates as cleaning: unknown exercise names are quarantined or
reported (never dropped), `RIR 6` is a warm-up, and seconds-vs-reps follows the taxonomy.

Capture post-session fatigue (1-5) with the session; it feeds §4.12 and is not a rubric item.

**Status 2026-10-23:** manual logging is closed through live workout mode — Start from a
prescription with the seven required readiness fields, manual/imported sets, inline correction,
measured/editable duration, sRPE or not-recorded, end/abandon, plan overrides, materialisation
into `clean_set`/`session`. The standard dated training export remains the
backfill path; the separate adapter work is §4.3.

Acceptance: a manually logged session is indistinguishable downstream from an imported one
(same tables and downstream reports); completion no longer triggers a review step
(`DEC-EVAL-09`); duration is stored when given and stays `unavailable` when not — never
estimated.

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
state editing, import, Programme, exercise editing and calibration are in the UI. The LLM proposal surface **no longer exists**:
`run --propose` was removed on 2026-11-17 for CLI/UI parity, so neither interface offers one and
the deterministic prescription, warnings and review remain the only plan path. `workout start` is UI-only because it needs the full readiness form. Both are
documented exceptions, not open items.

The local UI covers Today, Prescribe (rolling session types), Programme, Review, Readiness, Import, an editable
Athlete page, an editable **Exercises** catalogue, Terminal and Docs. This item brings the remaining interactive CLI actions into the browser. The CLI stays
as the automation interface; the UI must call the same core functions, never re-implement them.

Planned surfaces, in suggested order:

1. **Import** — **done**. Standard dated training/readiness CSVs and the in-workout workout CSV.
2. **State editing** — **done**. Profile, constraints, suitability ratings, e1RM overrides,
   strength tests, block start and symptoms; append-only, with an exercise picker and the
   current tables shown beside the forms.
3. **LLM proposals** — **withdrawn 2026-11-17.** The CLI surface was removed for parity; no
   proposal view exists in either interface and suggestions are display-only.
4. **Manual workout logging** (4.2) — **done** via Workout mode: per-set entry, plan overrides,
   import, end and reports.
5. **Programme view** (4.4) — **done**. Rolling session-type horizon with recomputation on the day; canonical session types are the only label.
6. **Post-lift form** (4.8) — optional 1–5 per exercise, editable in History; captured input,
   not a rubric.
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
audit are consolidated in [`docs/archive/UI-IMPROVEMENT-PLAN.md`](docs/archive/UI-IMPROVEMENT-PLAN.md); closed
2026-10-27 (implemented and merged into `main`; merge `db1cc8f`, lint `49a49cd`).

**Mobile UI audit (2026-10-28):** the consolidated iPhone/form-control audit lives in
[`docs/archive/UI-MOBILE-AUDIT.md`](docs/archive/UI-MOBILE-AUDIT.md). Checkpoints 1–4 fixed the P0 contract
failures, canonical athlete/exercise choices, the active-workout/readiness presentation, mobile
cards, searchable pickers, touch/dialog/safe-area rules and the accessibility/field-error gaps.
The owner completed the native-iPhone pass and the full automated suite is green; the audit is
closed.

**Deferred UI follow-ups (recorded 2026-11-01; not scheduled).** The plan's remaining items
are recorded here as a roadmap table so they are not lost. Details and evidence live in the
plan's §14; every item is a deferred improvement with a trigger, not an open audit finding.

| ID | follow-up | trigger | status |
|---|---|---|---|
| **O1** | Settings extraction after Exercises | Exercises extraction complete; Settings moved to `settings.js` | **done 2026-11-01** |
| **O2** | View registry for `setView` | Two features moved (Exercises, Settings) | **done 2026-11-01** |
| **O3** | Migrate `history.js`/`workout.js` helpers to core | A third feature needs the same helpers | deferred |
| **O4** | Streaming/multipart imports | 40 MiB parse memory becomes a real problem | deferred |
| **O5** | Read timeouts for slow request bodies | Slow-body handling is prioritized; local-only | deferred |
| **O6** | HTTP/1.1 and keep-alive | Close/drain handling and tests exist | deferred |
| **O7** | Limit tuning, 64 vs 96 MiB | A legitimate import is rejected | deferred |
| **O9** | Markdown scheme allowlist | Untrusted docs/links are allowed; block `javascript:` targets | deferred |

**O1 and O2 were implemented 2026-11-01:** Settings is in `settings.js` and `setView` uses a
view-loader registry. **O8 was implemented 2026-11-01:** 411/413 responses now have plain
next-action browser copy. **O10 was removed by the owner on 2026-11-01**; browser coverage
remains an accepted coverage limitation, not a planned follow-up.

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
### 4.15 Exercise selection adapted to readiness and fatigue  (v0.3; apply + comparability done)

**Status: apply + comparability implemented 2026-10-20; tax metadata, accessory candidates and symptom/readiness suggestions implemented. Plan closed at suggestions + explicit apply; automatic withholding deferred to the 8-week/30-session review.** The selector now carries tax metadata and `symptom` / `stress_readiness` triggers; substitutions remain explicit. See [`READINESS-EXERCISE-SELECTION-PLAN.md`](docs/READINESS-EXERCISE-SELECTION-PLAN.md) and `DEC-SELECT-06`.

**Current implementation:** `prescribe/selection.py` ranks the configured and catalogue variants per slot from readiness, recent stress, rotation and preference; the rejected fitness-fatigue state is no longer an input; constraints and `can_do: false` exclude a candidate; injury is a penalty, not a veto. Candidates carry an A/B/C comparability class: A applies automatically, B requires confirmation, C is hidden by default and never automatic; the selected lift's own history is always used. A display-only own-history e1RM ratio is shown, but it does not enter the score. See `DEC-SELECT-03` and [SELECTION-COMPARABILITY.md](docs/SELECTION-COMPARABILITY.md). It is exposed as `strength-coach select` and a Prescribe panel. With the explicit **Apply selection** toggle, the chosen candidate replaces the slot exercise and the load is re-solved from that lift's own history (`MOD-SELECT-001`). Without the toggle nothing changes. All synthetic raw variant names were canonicalised and their history rewritten (migration 0014, 114 entities, 3,607 audited remaps; migration 0015 split close-grip pulldown); trap-bar date-scoping and back-extension equivalence are preserved.

**Weakness/injury tailoring — deferred.** No positive weakness/injury targeting. Injury remains
an exclusion/penalty/ceiling. Earliest review is after v1.3 and ~April 2027, and only with 12
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
parent-ratio implementation, and any new model load effect. Those move to v1.5 or remain
unscheduled.

**v1.5:** see §4.13a. Delivered: the cardio data audit, capture completion and comparable workout data
collection. The impulse contract was retired 2026-11-18 (`DEC-LONGEVITY-03`).

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

### 4.25 Deterministic dynamic template resolver  (implemented; Steps 0–6 complete 2026-11-01/03)

**Status:** Steps 0 (contracts), 1 (settings/policy/provenance), 2 (generator core), 3 (top
set/back-off), 4A–4C (evaluator, beam and pipeline wiring), 5 (Settings -> Resolver and
preview) and 6 (historical hardening, rollout and documentation) are complete 2026-11-01/03; the
4C audit remediation is complete 2026-11-02 and Step 5 remediation is complete 2026-11-03. The
flag-on path now dispatches through candidate pools, the bounded beam and the read-only evaluator;
explicit resolver mode cannot silently fall back, scheduler availability uses the same automatic
candidate/slot matching as the pools, the persisted input fingerprint is canonical and staged
failures are diagnostic, and generated-session provenance is persisted. Step 6 reads the
immutable generated-slot snapshot for critique and volume exemptions, with a legacy-null
blueprint fallback; forecast remains fixed option (c), the resolver flag remains off by default
and the flag-off fixed-template path is unchanged. The generator core was remediated on
2026-11-01 for the review's shared eligibility, power-slot safety, settings, repair, availability,
spinal, history, warning and provenance defects. The current record is
[docs/archive/PROGRAMME-BUILDER-PLAN.md](docs/archive/PROGRAMME-BUILDER-PLAN.md) and
[docs/DECISIONS.md](docs/DECISIONS.md) (DEC-RESOLVER-01 to DEC-RESOLVER-13).
`DEC-RESOLVER-13` (2026-11-06) is a taxonomy-classification change rather than a resolver step:
`conventional_deadlift` is a `primary_compound`, so it passes the top-set classification gate
but remains outside the shipped `top_set.eligible_lifts` list.

The four canonical session identities stay and the shipped four-template YAML remains the
blueprint and fallback. A deterministic **session generator** resolves every slot at generation
time from existing athlete state, constraints, suitability, readiness, fatigue, spinal load,
injury signal, history, pattern coverage and a versioned resolver policy. There is no block-level
exercise pin; the generated session is frozen when the workout starts.

The main lift rotates only within its session pattern family, the secondary within its support
pattern, and accessories are pattern-flexible. Exercise Rotation is a deterministic 0-1 dwell
rule. Eligibility requires explicit can_do; unrated exercises are suggestion/confirmation only.
Step 2 scores with a provisional coverage model plus the existing readiness, fatigue, injury and
spinal signals; Step 4C runs the selected complete assignment through the existing pipeline once
and records the post-budget evaluator result. There is no second scheduler, prescription engine,
volume engine, programme/block lifecycle or pathway selector.

Top set/back-off is an optional main-lift structure, default ask, with DUP/competition RIR
mapping, preserved total sets and a first-class set-group model. `DEC-RESOLVER-14`
(2026-11-17) replaces the straight-set fallback with a ceiling: one readiness or sleep/energy
step is absorbed by the ceiling and the back-offs take the raised RIR, while a two-step drop, a
continuity gap or a back flare still falls back to straight sets. Hinge is allowed on a maximal
week for the prescribed hinge main lifts; the existing accessory/risk exclusions remain. A
competition-date override sets RIR 1 in the peak window and removes the top set in the taper;
an empty date means no override. All resolver configuration lives under Settings -> Resolver;
the shipped YAML remains the blueprint, the policy is a versioned file, and no database
template-version table is added. The forecast shows the blueprint/expected pattern (option c).

Major steps: (0) contracts and decisions, complete 2026-11-01; (1) settings, policy and
provenance, complete 2026-11-01; (2) generator core, complete 2026-11-01; (3) top set/back-off,
complete 2026-11-01; (4) joint evaluator and pipeline integration, 4A–4C complete 2026-11-01;
(5) Settings -> Resolver and generation preview, complete 2026-11-02 and remediated 2026-11-03;
(6) historical hardening, rollout and documentation, complete 2026-11-03. Work happens on the
feature/template-resolver branch, merged to `development` on 2026-11-03. LLM assistance
remains deferred to §4.24 until the deterministic resolver is accepted.

Implementation is released in **v1.2.0** as an opt-in feature. With the resolver flag off
(default), the existing template pathway, golden prescriptions and /api/programme forecast
remain unchanged.

**Acceptance audit:** closed 2026-11-03. The read-only lifecycle audit found no P0 defects;
its P1/P2 findings (Workflow set-group execution and plan/snapshot validation) were fixed in
`7d7ab3a`, `8a63212` and `4dd1705`. The closure record and residual release gates are in
[`docs/archive/RESOLVER-ACCEPTANCE-AUDIT.md`](docs/archive/RESOLVER-ACCEPTANCE-AUDIT.md).

Follow-up verification is complete: deload/top-set, drop contract, same-date fragments, top-set
e1RM, evaluator-to-persisted-plan equality, regression/slow (26 passed), integration (15 passed)
and the owner's manual browser Workflow validation are closed. No resolver implementation,
documentation or acceptance item remains open.

### 4.26 Symptom attribution and injury-signal verification  (closed 2026-11-01)

**Status:** Phase 1 and Phase 2 implemented and closed 2026-11-01. Phase 3 was split into
§4.28. Detailed design, audit and acceptance criteria:
[`docs/INJURY-ATTRIBUTION-PLAN.md`](docs/INJURY-ATTRIBUTION-PLAN.md).

**Phase 1 — verification hygiene (done 2026-11-01).** Corrects how the existing rule is
evaluated without changing the rule itself: symptom rows are deduped to the latest per
`(logged_on, timing)`; a same-day `pre_session` flare marks the session `symptomatic_load`
and denies tolerance; a same-day `post_session` reading counts as follow-up; and
`flared`/`symptomatic_load` are counted separately from `unverified`. The next-day pre-session
rule, the 7-day window and the review gate are unchanged (`ASSUMPTION-09` remains).

**Phase 2 — optional attribution (done 2026-11-01).** A symptom reading may point at one
completed session, at most one lift performed in that session, a required onset date and a
required confidence label (`possible`/`likely`/`strong`). It is display and review only: it
never changes suitability, constraints, selection, load, the signal's status or its
recommendation, and it is not a predictor input. No free-standing exercise field, no
timestamps, no per-session verification, no multiple lifts, no backfill. Migration `0047` adds
the nullable columns.

Phase 3 is no longer part of this plan; it is the separate §4.28 research phase.

### 4.27 Training-day session fragments  (done 2026-11-01)

**Status:** implemented. One local training day may hold multiple existing `session` rows;
they are grouped by `occurred_on` and never merged. Attendance, the weekly budget and the
rolling schedule count training days. Volume, spinal cost and MRV still count every working
set from every fragment once. e1RM produces one best eligible observation per exercise and
day. The second fragment reuses the day plan and the first fragment's readiness snapshot.
History shows one expandable training-day row; the fragment API, edit, void, review and detail
surfaces remain. No schema migration. The specification and acceptance criteria live in
[`docs/TRAINING-DAY-MODEL.md`](docs/TRAINING-DAY-MODEL.md).

### 4.29 Native iPhone client — online-first (Phases 0–4 and the R-series closed)

**Status:** Phase 0 complete (2026-11-07): an empty SwiftUI app is signed and launches on the
owner's iPhone under a personal team, the HealthKit capability is verified, the phone reaches the
server over plain HTTP on the home LAN, and CLI-only pairing was chosen. Phase 1 (native foundation
and read-only views) is **complete 2026-11-07**: the server side is migration `0052_ios_device`,
the `strength-coach ios pair/devices/revoke` CLI, the bearer-authenticated read-only
`/api/ios/v1/` facade and `tests/test_ios_api.py`; the Swift client in the separate
`StrengthApp` repository provides pairing, Today, History and Settings/Forget with Keychain
storage, 29 unit tests and a live UI smoke test. It passed on the iPhone 18 Pro simulator and was
owner-confirmed on the physical iPhone. Phase 2 (online strength workflow) is **complete
2026-11-07**: migration 0053_ios_workflow.sql, the issued-plan/receipt store, the
authenticated readiness/prescription/workout/complete/abandon routes, and 27 contract tests;
the client adds readiness entry, prescription preview, start-by-id, active workout with optional
manual mean velocity, form ratings, RPE/not-recorded completion, abandon and a Progress screen.
The contract is [`https://github.com/georgesdib/strength-app/blob/main/docs/contracts/IOS-PHASE-2-CONTRACT.md`](https://github.com/georgesdib/strength-app/blob/main/docs/contracts/IOS-PHASE-2-CONTRACT.md).
The default server suite is 1685 tests and the client has 102 unit tests after R1/R3/R4/R5 and
Phase 3A; the live UI workflow passed on the iPhone 18 Pro simulator. Physical-iPhone Phase 2
acceptance was owner-confirmed on 2026-11-07 on the iPhone 16 Pro Max (iPhone17,2), iOS 27.2.
Phase 2 is closed. Phase 3A (opt-in HealthKit HRV/RHR/bodyweight readiness) is **implemented and
closed 2026-11-08** under [`https://github.com/georgesdib/strength-app/blob/main/docs/contracts/IOS-PHASE-3A-CONTRACT.md`](https://github.com/georgesdib/strength-app/blob/main/docs/contracts/IOS-PHASE-3A-CONTRACT.md);
physical HealthKit acceptance was owner-confirmed and Phase 3B remains out of scope.
The first useful release is an online, authenticated native strength-training workflow against the
owner's local Python server. Durable offline capture (Phase 4) is closed; reviewed Apple Workout
imports (Phase 3B) and Apple Intelligence are later phases, not first-release dependencies. Phase 3A
HealthKit readiness is closed. PCC may be a separately enabled Apple AI option;
it is disabled by default, user-invoked, never an automatic fallback, and never used for HealthKit
sync. No public cloud service is required for core use. Phase 3B needs a separate approval; no
later phase starts by implication.

The detailed, repository-grounded client plan is in the
[iOS client repository](https://github.com/georgesdib/strength-app/blob/main/docs/plans/IOS-CLIENT-PLAN.md).
Recommendation: a small native SwiftUI client with Python remaining the sole authority for
readiness scores and prescriptions. Phases 0–2, 3A and 4 are complete; Phase 3B needs a separate approval. The SwiftUI client is its own repository (`StrengthApp`), developed alongside this one rather than as
an `ios/` subdirectory here. The first release covers pairing, readiness entry, a server prescription,
online workout capture/completion with session RPE, optional inline form ratings and basic
history/progress. Opt-in read-only HRV/RHR/bodyweight readiness (Phase 3A) and durable offline capture
(Phase 4) are complete; reviewed Apple Workout imports follow, with manual values taking precedence.
The rubric review was retired (`DEC-EVAL-09`); the session report is the post-workout surface.
Apple Foundation Models/PCC are optional later tools, never training authorities.
Third-party Health exporters are not a core dependency; XML is, at most, a later manual history
backfill.

**Phase 1 completion record (2026-11-07).** Server: migration `0052_ios_device`, the
`strength-coach ios pair/devices/revoke` CLI, the read-only `/api/ios/v1/` facade, and
`tests/test_ios_api.py`; the default suite is 1604 tests and `ruff` passes. Client: pairing,
Today, History and Settings/Forget in the separate `StrengthApp` repository, Keychain storage,
29 unit tests and an optional live UI smoke test. The `/progress` facade route is server-only in
Phase 1; the client has no Progress screen (deferred to Phase 2). Verification: the live test
passed on the iPhone
18 Pro simulator against a temporary SQLite database, then the owner confirmed the device checklist
on the physical iPhone. No existing unversioned route, prescription, workout or readiness record
changed. Rollback is additive: drop `ios_device` and `ios_pairing_code`, remove the
`/api/ios/v1/` routes and the `ios` CLI group, and forget/uninstall the client. Residual
limitations: plain HTTP on the trusted LAN only, no writes in Phase 1, no HealthKit or offline
capture, and 7-day personal-team signing.

**Phase 2 completion record (2026-11-07; remediation same day).** Server: migration
0053_ios_workflow.sql, config/ios.v1.yaml, ios_config.py, the issued-plan/receipt store, the
authenticated readiness/prescription/start/add-set/form/complete/abandon routes, and 27 contract
tests in tests/test_ios_workflow.py; the default suite is 1632 tests and ruff passes. The normal
prescription is persisted at issue, the phone starts by issued-plan id only, and every mutation
requires a UUID Idempotency-Key with a 30-day receipt. The receipt lookup and mutation now share
one BEGIN IMMEDIATE transaction, so concurrent duplicates replay the committed response instead
of executing twice; a receipt uniqueness race is rolled back and re-read rather than returning a
500. The server owns readiness, load and set decisions; manual mean velocity is stored as an
optional performed value, never a new prescription input. Client: readiness form, prescription
preview, active workout, optional form ratings, RPE or explicit not-recorded completion, abandon,
and the Progress screen; 43 unit tests at closure (55 after R1/R3/R5) and optional live UI smoke tests. Plan-item attribution is
sent only when the exercise occurs exactly once; repeated exercises remain nil/unmatched instead
of being guessed. Retry keys are body-aware, duplicate UI mutations are guarded, and an ambiguous
finish locks the exact completion body for replay. Verification: the live UI test passed on the
iPhone 18 Pro simulator against a temporary SQLite database (pair -> readiness -> issue -> start ->
add VBT set -> force-quit/relaunch recovery -> finish -> Progress). The owner confirmed the
physical-iPhone Phase 2 checklist on 2026-11-07 (iPhone 16 Pro Max, iPhone17,2, iOS 27.2). The live
data/coach.db is at schema 0053 with both Phase 2 tables present; PRAGMA quick_check returned ok.
A post-acceptance backup was written to
data/exports/phase2-post-acceptance-2026-11-07.tar.gz (SHA-256
b919ae0283edef91e31ac1d1d2062537288258818ab707b527caee3be29db9d7) and verified by a dry-run
import. The Release build passes. Rollback: set mutations_enabled: false to return mutation
routes to 503 while reads stay available; drop ios_issued_plan and ios_operation_receipt, remove
the Phase 2 routes/client screens, and forget the device. Existing prescriptions/workouts already
committed by a started session remain valid. At Phase 2 closure, residual limitations were no
offline queue, no HealthKit, no plan editing on the phone, and plain HTTP on the trusted LAN. R1's durable
pending-mutation journal was added immediately after closure (51 client tests), so a lost response
is replayable after termination within its 28-day window while the server receipt remains. R3
explicit plan-item selection and R5 recovery/reconciliation UX are implemented and closed; R2 is
closed as absorbed by R7; R4 is implemented and closed in roadmap §4.30. R7 (asynchronous
prescription request with session-type and minimum-session settings) is implemented as of
2026-11-08: migration `0056`, the bounded dispatcher, the `202` issue route, `GET plans/current`
and start-time prescription persistence; the client builds with an iOS 27.0 deployment target and
passes 102 unit tests on the available iOS 27.2 simulator. R8 (active-workout plan editing) was approved, implemented and closed on 2026-11-08
under `https://github.com/georgesdib/strength-app/blob/main/docs/contracts/IOS-R8-CONTRACT.md`. Execution telemetry (R9) adds migration `0057`,
append-only `workout_execution_event`, authenticated batch ingestion and read-only execution
analytics; the client records set/rest/exercise timing through the Phase 4 outbox and renders an
execution timeline in completed History. Server and simulator gates pass; physical-iPhone
acceptance was owner-confirmed 2026-11-14. R9 follow-up 2026-11-17: execution analytics keeps open
exercises per plan item, so a superset's overlapping exercise intervals are both retained rather
than one start being discarded; covered by a workflow test. Phase 2 is closed 2026-11-07.

**Phase 3A completion record (closed 2026-11-08; physical acceptance owner-confirmed).** Server: migrations 0054_healthkit_readiness.sql and
0055_healthkit_bodyweight.sql; the append-only healthkit_readiness table; one canonical
effective-readiness merge (manual/preset > HealthKit > imported) used by readiness day, series,
history, scoring and the HRV/RHR baseline; the authenticated
POST /api/ios/v1/healthkit/readiness route; device-scoped sample identity and operation receipts;
bootstrap healthkit_readiness capability. The default suite is 1685 tests and ruff passes.
Client: read-only HealthKit authorization for HRV SDNN, resting heart rate and bodyweight,
deterministic source classification and selection, offline-free single-flight import,
healthkitReadiness journal kind, Settings opt-in and Today provenance/freshness display; 102 unit
tests. Verification: focused server tests, full server suite, client unit tests, simulator build and
live UI workflow pass. Physical HealthKit acceptance with real samples was owner-confirmed on
the iPhone on 2026-11-08. Rollback:
remove the client importer and canonical-merge integration, drop healthkit_readiness and delete the
0054/0055 schema_migration rows together, leaving readiness_day/readiness_entry untouched.

**Phase 3A amendment 2026-11-18 — recovery HRV.** Readiness now reads a recovery series instead
of the newest raw sample: migration 0071_hrv_recovery.sql (append-only, one row per night),
`POST /api/ios/v1/healthkit/hrv-recovery` (dated, idempotent by sample id), the canonical merge
overriding `hrv_ms` from it and suppressing the raw sample, and the client's
`RecoveryHRV`/backfill (five-year horizon, resumable watermark). The raw sample import and its
48-hour rule are unchanged and remain the audit series. Rollback: drop `hrv_recovery` and delete
the 0071 row; the merge then reads the raw sample again.
Residual limits: HealthKit read denial is not observable and is reported as indeterminate; no
sleep, workouts, cardio, raw series, HealthKit write or scoring change. Phase 3B remains separate.

**Release gate:** the existing web/CLI API is unauthenticated HTTP on the home LAN
(LIM-57); the phone uses the separate per-device bearer facade. Keep existing web/CLI
routes compatible and keep the API on the trusted home LAN over plain HTTP: LAN traffic, including
the device credential, is unencrypted and the deployment assumes a trusted network with no public
exposure. No port-forwarding, remote access, TLS/Caddy/internal CA, certificate installation,
pinning or certificate management is required for this personal deployment; reconsider TLS only if
the network stops being trusted or remote access is added. No public endpoint, cloud database,
analytics or telemetry is required. The sole proposed app-network exception is the separately
enabled Apple PCC AI mode, with per-request context preview/consent; it is not part of the local
server API. Do not require an elaborate egress-audit project for the core release.

**Proposed phases:** (0) preconditions — complete 2026-11-07: signed empty app under free
provisioning with a HealthKit capability check, and the phone reaching the server on the home LAN
(plain HTTP);
(1) native foundation and read-only views; (2) online strength workflow with readiness, server
prescription, set logging, completion/session RPE, inline optional form ratings and basic history;
(3) opt-in HealthKit HRV/RHR/bodyweight readiness inputs, then reviewed Apple Workout/cardio imports and
source-aware effort mapping; (4) durable offline capture/reconciliation; (5) separately approved
optional enhancements such as Apple Intelligence on-device/PCC. The implementation order was 0 → 1 → 2
→ 3A → 4 → 3B → 5; phases 0–2, 3A and 4 are complete. The rubric review screen is optional and may follow the
first release. No sleep feature is proposed.

Full acceptance criteria and rollback gates are in the plan.

### 4.30 iOS reliability follow-ups (R1–R5, R7 and R8 closed)

R1, R3 and R5 were implemented and closed on 2026-11-07. R1 provides the durable pending-mutation
journal; R3 provides explicit plan-item selection for repeated exercises; R5 surfaces a
server-active workout, a workout ended elsewhere, or an unusable prescription with explicit
resume/abandon/refresh/clear actions. Unit and simulator verification pass; separate
physical-device R1/R3/R5 passes were not performed. R7 (asynchronous prescription request with
workout settings) was specified, approved and **implemented and closed on 2026-11-08**: the server
behaviour is
covered by the default suite, the client builds with an iOS 27.0 deployment target, passes its
102 unit tests on the iOS 27.2 simulator, launches, and passes the live UI flow twice against throwaway servers — once with the
resolver off and once with it **on** against a copy of the real database (202 in 0.1 s, plan ready
in 4 s, full flow 90.9 s). R8 (active-workout plan editing) was approved, implemented and closed on
2026-11-08.
R7's `plans/current` read closes R2 as absorbed; R4 is implemented and closed. This
reliability work did not add HealthKit, an unrestricted offline queue or Phase 3; Phase 3A is a
separate implementation under its own contract.

| id | priority | item | scope / constraints |
|---|---|---|---|
| R1 | High | Durable pending-mutation journal — **closed 2026-11-07** | Persists the operation UUID, device/server, mutation kind, target workout/plan id, route, exact encoded request body, creation timestamp and pending/conflict state in Application Support with iOS file protection and backup exclusion. Replays only the original UUID/body; 2xx removes, definitive 4xx removes, idempotency conflicts and terminal states are surfaced, and transport/5xx stay pending. Capped at 16 entries, 30-day retention, 28-day replay window. No unrestricted offline queue; new mutations are blocked while an unresolved operation exists. |
| R2 | Low | Unstarted issued-plan recovery — **closed 2026-11-08, absorbed by R7** | `GET /api/ios/v1/plans/current` returns the device's current unconsumed, non-superseded plan and also serves the R7 polling/foreground read. It never exposes another device's plan and never permits reuse. No separate R2 implementation exists. |
| R3 | Medium | Explicit plan-item selection — **closed 2026-11-07** | When an exercise appears multiple times, the active workout offers a prescription-item picker listing each occurrence; the default remains nil/unattributed. Unique exercises keep automatic attribution. The existing backend explicit-index validation is reused; no schema or API change. Covered by the plan-choice client test. |
| R4 | Low | Form-rating correction UX — **closed 2026-11-08** | The form section shows the current rating for the selected exercise, prefills it for a correction, labels a subsequent save **Save correction**, and states that the earlier rating is retained while the latest is shown. The server remains append-only and the workout payload still returns only the latest rating per exercise. No schema change. |
| R5 | Medium | Workout recovery/reconciliation UX — **closed 2026-11-07** | Today shows a Recovery section when refresh finds a server active workout not represented locally, a local in-progress workout no longer active on the server, or a consumed/expired/superseded prescription. Actions: resume/abandon/dismiss a server workout, refresh/clear stale local state, refresh/dismiss an unusable prescription. A one-read grace prevents false ended-elsewhere states immediately after a local mutation. Unreplayable pending mutations remain in the R1 recovery panel. |
| R7 | High | Asynchronous prescription request with workout settings — **implemented and closed 2026-11-08** | Replaces the blocking `POST /api/ios/v1/prescriptions` with a 202 and a database-backed request row: optional session type and minimum session, a shared CPU slot (no second concurrency budget), one bounded dispatcher with two eligibility checks so an ineligible request never reaches the resolver, a generation check so a superseded build is never published, an explicit legacy-row mapping in migration 0056, authoritative foreground recovery from `plans/current`, and prescription rows written at start instead of at issue. The client polls `GET /api/ios/v1/plans/current` (which also absorbs R2) at 1→2→5→10 s with no 60 s ceiling, survives app exit, and loads a ready plan on return. Contract: `https://github.com/georgesdib/strength-app/blob/main/docs/contracts/IOS-R7-CONTRACT.md`. |
| R8 | Medium | Active-workout plan editing — **closed 2026-11-08** | Swap, add, remove and set-count edits on an in-progress workout through the existing `workout.py` services. The phone never supplies a load or a replacement plan; add uses the service defaults (3×8–12 @ RIR 2, no load), and swap clears the load. An authenticated read-only `GET /api/ios/v1/exercises` supplies the picker while online; edits are online-only and R1 journaling makes an attempted edit retry-safe. Swap is blocked after sets are logged; set count cannot go below logged sets; the last item cannot be removed; ambiguous unattributed sets block edits. Plan-item `order_index` is the stable identity carried into `prescription_item_index`, so removing an earlier item never renumbers later logged sets; display position is separate. Edits rewrite `plan_modified_json` and append `workout_event` rows; the issued plan JSON is never modified. The web UI shares the same guards and 409 mapping. Contract: `https://github.com/georgesdib/strength-app/blob/main/docs/contracts/IOS-R8-CONTRACT.md`. |

**Recovery boundary after R1:** every attempted mutation is journaled before the HTTP request.
After termination, the app replays journaled operations with the original UUID and exact body,
then reconciles through the normal server responses. A response lost before acknowledgement is
therefore recoverable within the replay window, provided the server receipt has not expired.
Conflicts, stale entries, and terminal workout states stop automatic replay and require explicit
review/discard in Today. The journal is capped and blocks new mutations while an unfinished
operation exists; it is not a general offline queue.

### 4.31 Phase 4 — reliable capture and offline support (closed 2026-11-08)

Phase 4 caches the active workout and queues add set, form rating and finish while the server is
unreachable. It preserves performed/finish timestamps, gives offline sets temporary local identities,
replays strictly in order with the existing receipts, and keeps conflicts visible. Readiness,
prescription/start, plan editing and HealthKit remain online-only. No server queue table is added.
Contract: [`https://github.com/georgesdib/strength-app/blob/main/docs/contracts/IOS-PHASE-4-CONTRACT.md`](https://github.com/georgesdib/strength-app/blob/main/docs/contracts/IOS-PHASE-4-CONTRACT.md).
Physical offline acceptance was owner-confirmed at closure on 2026-11-08.

### 4.32 Phase 6 — watchOS companion (6.0–6.7 complete; 6.7 acceptance 2026-11-14)

The phone remains the planner; the watch becomes the execution client for a plan requested with an
explicit `execution_target` (`phone` or `watch`): fetch, start, log sets/rest/forms, finish with
sRPE, live heart rate and exactly one HealthKit strength workout. Targets are iOS 27.0 and
watchOS 27.0. The watch gets its own device token with a server-issued credential epoch and
acknowledgement, is pinned to the phone's **home** server via `homeBaseURL` + `configVersion`
(never the Away route), and is the only set writer during its session (the phone mirrors it with
plan edits and a take-over path). Start is the only online gate in v1; after it, logging is
offline-first with partial flushes and backoff, preserved timestamps, and an offline finish that
syncs by foreground retry or on next open. An HKWorkoutSession anchors the app's lifetime; a
replayed set whose plan item changed is preserved as off-plan rather than dropped, plan edits
propagate by revision, and forgotten sessions are idle-abandoned. Shared code has been extracted into
`StrengthCore` in four staged, behaviour-preserving moves (S1–S4 complete 2026-11-10; 184 iOS tests);
the watch target is 6.2a. Contract:
[`IOS-WATCH-CONTRACT.md`](https://github.com/georgesdib/strength-app/blob/main/docs/contracts/IOS-WATCH-CONTRACT.md).

**Completion record.** 6.0 (shared watch core), 6.1 (server watch contract), 6.2a–6.2c (watch
target, credential/config handoff, mint/list/revoke and the read-only watch Today), 6.3 (watch
execution lifecycle), 6.4 (offline conflicts), 6.5 (heart rate and one HealthKit workout), 6.6
(phone mirror, plan-revision pushes and take-over) and 6.7 are complete. Physical Apple Watch
acceptance was owner-confirmed **2026-11-14**, and the canonical status lives in the
[iOS client plan](https://github.com/georgesdib/strength-app/blob/main/docs/plans/IOS-CLIENT-PLAN.md)
and the watch contract, not here.

**Still deferred:** offline start (the pending-session shell) and the “Send to iPhone” relay.
Any further watch work needs a separate go-ahead.

### 4.35 Derived analytics layer  (Phase 0 complete; Milestones A, B and C implemented 2026-11-14)

**Status:** Phase 0 (architecture and design approval) is complete. **Milestone A (Analytics
Infrastructure)** is implemented (`bf2775f`; audit remediation `2654ce2`, `81ca614`).
**Milestone B (Core Materialisation and Consumer Migration)** is implemented: `derived_set`,
`derived_session_exercise` and the `core` family are live, and `progress` and `strength_trend`
read them when ready. **Milestone C (Rules, Outcomes, Monitoring and Production Validation)** is implemented.
Analytical snapshots remain optional and deferred. The full proposal is
[`docs/design/DERIVED-ANALYTICS-ARCHITECTURE.md`](docs/design/DERIVED-ANALYTICS-ARCHITECTURE.md).

The audit found no persistent analytical layer: dashboards and reports rescan and re-enrich the
whole `clean_set` history, several modules derive e1RM independently, and the deployment host
measures about 2.7 s p50 for `get_training_overview`, 1.7 s for a deload decision, 4.9 s for the
8-week outcomes report and 49 s for the monitoring analysis on a synthetic 377-session database.

The proposal is a selective, versioned, rebuildable materialisation owned by the existing
analytical modules: per-set derived values, session/exercise aggregates and ISO-week spinal and
volume aggregates. Owners keep their formulas and payloads; consumers keep calling the same
functions; a background worker backfills and resumes after interruption; reads fall back to
on-demand until the family is ready. Snapshots are optional, excluded from Milestones A and B,
and decided only after aggregate materialisation is measured.

**Milestone A delivered (`bf2775f`).** Migration
[`0061_analytics_phase1.sql`](strength_coach/store/migrations/0061_analytics_phase1.sql) adds the
append-only `analytics_revision` ledger and the `analytics_build` lifecycle table. The ledger is
written inside the source transaction by workout completion, imports (only when clean sets were
inserted), corrections/tombstones, void/unvoid, and dependency changes; dependency rows are
family-scoped so an unrelated configuration bump does not invalidate a family. The coordinator
[`strength_coach/analytics/coordinator.py`](strength_coach/analytics/coordinator.py) runs bounded
revision batches with checkpoints, resumes after interruption, records failed builds without
publishing, and promotes a family to `ready` only inside a `BEGIN IMMEDIATE` transaction that
re-reads the family revision and dependency fingerprint. `GET /api/analytics/status` reports the
revision and family rows. Tests:
[`tests/test_analytics_revision.py`](tests/test_analytics_revision.py) and
[`tests/test_analytics_build.py`](tests/test_analytics_build.py).

**Milestone A audit outcome (2026-11-14).** The independent audit traced every current
`clean_set`/`session` writer to three call sites (`workout.end`, `importer.import_export`,
`history.edit_session`/`void_session`) and confirmed transactional coupling, rollback, family-scoped
batch selection, checkpoint/failure behaviour and the `BEGIN IMMEDIATE` publication check with a
blocked concurrent writer. One diagnostic defect was fixed in `2654ce2`: `status_snapshot` now
reports the persisted lifecycle separately from validated readiness (`verified`/`unverified`/
`not_ready` plus a reason), so an unregistered family is never implied to be verified. Accepted
limitations: the registry is empty; no runtime configuration-reload hook exists, so fingerprints
protect readers and a caller must record a dependency revision to invalidate a published family
immediately; imports append one batch revision; no exercise-remap writer exists in the tree.

**Milestone B delivered (2026-11-14).** Migration
[`0062_derived_core.sql`](strength_coach/store/migrations/0062_derived_core.sql) adds
`derived_set` and `derived_session_exercise`; the `core` family materialises the progress e1RM
and the strength-observation payload per leaf set, plus per-session/exercise aggregates. Initial
backfill is the explicit `strength-coach analytics build` command (paged session backfill through
the Milestone A coordinator). Small source mutations refresh their session inside the same
transaction; imports above 50 sessions mark the family stale for an explicit build. The owners
call the read-only `core.ensure` and fall back to on-demand whenever the family is not verified
current. The fingerprint includes both taxonomy files (including UI-written overrides), so a
taxonomy edit invalidates stored strength payloads until a rebuild. Tests in [`tests/test_analytics_core.py`](tests/test_analytics_core.py) cover parity
before/after materialisation, corrections, void/unvoid, imports, fallback and failed-family
behaviour.

**Deployment:** pulling the code and restarting applies the migrations but does not materialise
history; run `strength-coach --db <coach.db> analytics build` once after the upgrade (back up
first, ideally while idle). Until then the consumed families stay on the on-demand path.

ODROID benchmark (377 synthetic sessions, same method as the audit): overview p50 2,746 → 2,474 ms;
dashboard 991 → 744 ms; one-lift strength trend 6,825 → 258 ms; full parity check passed. Backfill
took about 8.2 s. The overview gain is limited because deload, volume and attendance remain on
demand (Milestone C). Known limitations: initial backfill is an explicit operator command (no
scheduler yet); large imports mark the family stale until built; the strength payload is stored as
a versioned JSON value.

**Milestone C delivered (2026-11-14).** Migration
[`0063_derived_week.sql`](strength_coach/store/migrations/0063_derived_week.sql) adds
`derived_week` and the source set fields that outcomes/monitoring read. Spinal exposures are
materialised by the existing `rules.registry.spinal_exposures`; `deload` evaluates the authoritative
rule against a minimal context built from the weekly rows, so verdicts, evidence and the complete
cost map stay the rule's output. `outcomes` and `monitoring` read `core.set_frame` instead of
rescanning `clean_set`, and their e1RM associations use the migrated strength trend. The core
fingerprint now also covers the spinal-rule files.

Full-dataset parity (377 synthetic sessions): deload verdict/evidence/cost map, outcomes report and
monitoring payload all equal (monitoring compared without its database-identity fingerprint).
ODROID before/after: deload 1,682 → 40 ms; overview 2,744 → 799 ms; outcomes 4,884 → 3,585 ms;
monitoring 48,728 → 18,357 ms; build ~63 s. Remaining limitations: build is an explicit operator
command; a large import marks the family stale; snapshots are not used; the INT integration review
is still a follow-up.

**Follow-up C-1 — automatic maintenance worker (done 2026-11-15).** Delivered as a systemd oneshot
plus timer rather than an in-web background worker. `analytics build` compares the dependency
fingerprint with the persisted build row and does nothing when the family is current; when taxonomy
or spinal-rule files changed, the family is stale or incomplete, a large import arrived, or a build
failed, it rebuilds (resuming through the backfill cursor) and reports through
`/api/analytics/status`. A run that finds nothing to do exits 0 without touching the build
timestamps. The exercise writer that edits `overrides.v1.yaml` does not enqueue a build directly;
the next 15-minute tick reconciles it, which is the accepted trade for having no long-lived worker.
Consumers still fall back to on-demand, so a missed tick costs latency only.

**Benchmark tooling extended (2026-11-14).** `tools/intelligence_benchmark.py` now discovers every
registered capability, generates valid arguments from the benchmark database, and supports direct
execution, real MCP Streamable HTTP (official SDK client, bearer token from an environment
variable) and read-only existing-database modes. It reports per-capability distributions, errors,
envelope statuses, analytics readiness and a clearly labelled MCP-overhead difference; identifiers
are redacted. Tests are in `tests/test_intelligence_benchmark.py`. The HTTP mode was run on the ODROID against
a copied production database (377 sessions, 7,978 sets, core family verified ready): HTTP p95 was
6,201 ms for session details, 4,058 ms for overview, 3,800 ms for the programme summary and 1,663 ms
for readiness, so the one-second transport gate is **not met** for four capabilities. ADR-INT-010
then adopted the latency-aware budget (option B) and enabled the full catalogue; these p95 values
are guidance, not a guarantee, and T-3 remains the optimisation track.
The run also exposed a benchmark argument-schema bug (readiness/VBT use start/end), now fixed. See
`docs/INTELLIGENCE-DEPLOYMENT.md` §13.

**Correctness contract (2026-11-14 refinement).** A source revision is a durable, monotonic
`analytics_revision` row appended in the same transaction as each mutation (workout completion,
import, correction/supersede/tombstone, void/unvoid, any future remap that changes rows, config or
methodology change). `MAX(clean_set.set_id)` and `PRAGMA data_version` are only change probes:
they miss supersessions, flags and version changes and are not durable across processes. A family
may be published `ready` only when its rows are committed, `processed_revision` reaches the family
revision, the dependency fingerprint matches, and a final publication transaction sees no newer
revision. Committed batches are not a publishable family. During backfill the owner keeps the
on-demand path; concurrent writes advance the revision and the worker catches up before publishing.

**Grain.** The four identities are distinct: session fragment (`session_id`), training day
(`occurred_on`, possibly several fragments), exercise-within-day (best eligible fragment, never
averaged) and exercise-within-session. `derived_week` is stored at ISO week x session x exercise
because that is what reproduces `weekly_spinal_costs` exactly: summed weighted cost plus the
per-exercise exposure count behind the evidence text, including set-count and mean-intensity
factors. A week-only grain would lose that count and change the deload details.

**Dependencies.** e1RM, set classification, taxonomy, spinal and volume versions form a graph: an
upstream version bump invalidates every downstream family, which is why publication is keyed on a
fingerprint rather than a single version. `analytics_snapshot` remains optional and is excluded
from Milestones A and B; the monitoring/outcomes snapshot decision comes only after aggregate
materialisation is measured.

**Acceptance tests** (detail in the design doc): payload and numeric equivalence, exact deload
verdict/evidence/weekly cost map, interruption and resume, concurrent source changes during
backfill, invalidation after correction/void/import, methodology and config bumps, no partial
family reads, and fallback when a family is incomplete or failed.

| Phase / milestone | Scope | Status |
|---|---|---|
| 0 | Architecture and design approval | **completed 2026-11-14** |
| **A** | Analytics infrastructure: revision ledger, mutation coverage, build state, coordinator/recovery, fingerprints, safe publication, status | **implemented and audited 2026-11-14 (`bf2775f`, `2654ce2`)** |
| **B** | Core materialisation and consumer migration (former phases 2–3): `derived_set`, `derived_session_exercise`, family registration, progress and strength-trend migration | **implemented 2026-11-14; parity and ODROID measurements recorded** |
| **C** | Rules, outcomes, monitoring and production validation (former phases 4–6): `derived_week`, deload/rules, outcomes, monitoring, ODROID verification, INT gate | **implemented 2026-11-14; parity and ODROID measurements recorded** |
| **C-1** | Automatic maintenance worker (startup/periodic reconciliation, exercise-writer hook) | not started |
| Snapshots | Optional, deferred, not a milestone requirement | not decided |

**Non-goals:** metric changes, deload policy changes, lookback truncation, a generic cache, MCP
transport changes or client changes.

### 4.36 Longevity assessment — aerobic adequacy, fitness and strength context  (implemented 2026-11-18; released in 1.7.0; corrected in 1.7.1)

Three questions, one deterministic answer each: is the aerobic reference being met, can the stored
VO₂max be read at all, and what volume headroom remains per pattern. Canonical plan:
[longevity assessment](https://github.com/georgesdib/strength-app/blob/development/docs/plans/LONGEVITY-ASSESSMENT.md).

Python computes the facts and exposes them as one `assessment` block on `GET /api/cardio/summary`
and as the `get_longevity_assessment` intelligence capability (MCP tool 11, the iOS intelligence
route and the chat dossier). It returns facts only; the iPhone Today card and the web Longevity
panel render the same block, and the host model writes the advisory prose from it (on-device or
configured). The WHO 150–300 band is context, not a target (`DEC-LONGEVITY-01`); there
is no VO₂max category and no age/sex field (`DEC-LONGEVITY-04`); cardio minutes, time-in-zone and
VO₂max are `health` and need their own off-device consent (`DEC-LONGEVITY-02`); the advice is never
wired to a prescription. Time-in-zone reuses the existing sample classification and the corrected
elapsed-time integration, which is not an impulse model. No migration, no notification, no strength
verdict.

**1.7.1 corrective release (2026-11-18).** Eight audit findings were verified against the 1.7.0
code and corrected without changing the product decisions: (1) the DeepSeek chat dispatcher now
builds a per-request allowlist from the tools it actually advertised and rejects unadvertised
health or plan tools before their provider is called; (2) recovery-tail samples
(`association = 'tail'`) and samples outside the workout interval are excluded from workout
classification and time-in-zone while remaining in the corpus; (3) time-in-zone now integrates
elapsed time between adjacent samples, clips to the workout, does not allocate gaps over 120 s or
the final sample, and reports covered/workout/unobserved duration separately from continuity
eligibility; (4) an above-300-minute week is its own `above` relation and is described as context
above the band, never as excessive or harmful; (5) inserting new heartbeat samples for an
already-imported workout invalidates the classification cache via a cheap state marker, and a
re-import is a no-op; (6) the web Longevity panel reads only the canonical `assessment` block and
requests optional time-in-zone/headroom deliberately; (7) VO₂max presentation includes units,
date, source/method and currency on both clients; (8) remote narration of a health-class capability
requires an explicit `health_consent` flag in addition to the browser disclosure.
Cross-platform fixtures are byte-identical in both repositories and are asserted by the parent
contract test. Limitations: time-in-zone is still sample-based and only for continuity-eligible
workouts, so it is not a clinical zone-duration measurement; whole-workout classification remains
an estimate; VO₂max remains a consumer estimate with no age/sex category.
