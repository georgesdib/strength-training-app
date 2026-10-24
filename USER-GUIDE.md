# USER GUIDE

How to actually use this tool. For the design record see [docs/](docs/), and for where the
project is going see [ROADMAP.md](ROADMAP.md).

---

## 1. What it is, in one paragraph

It reads your training export, cleans it under a documented set of rules, reconstructs
sessions, judges the most recent one against a fixed constitution, and prescribes the next
session — squat, hinge, bench_squat or bench_hinge. **Python computes every number; the LLM only explains them.** If no model is
configured, everything still works — you just lose the prose.

It is a coaching tool with a fixed methodology, not a chatbot that invents programmes. Where
the data cannot support a judgement it says `unknown` or `n/a`, never a guess.

---

## 2. Requirements and install

- Python 3.11+
- Your exports as `data/raw/training_log.csv` and `data/raw/readiness.csv`
  (schema in [data/README.md](data/README.md))

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

.venv/bin/python -m pytest          # counts live in ROADMAP.md
```

**Activate the environment before using the command:**

```bash
source .venv/bin/activate          # bash / zsh
# or: . .venv/bin/activate.fish   # fish
strength-coach --version
```

`strength-coach` lives in `.venv/bin`, so it is only on `PATH` while the venv is active. If
you would rather not activate it, call `.venv/bin/strength-coach ...` or
`.venv/bin/python -m strength_coach.cli ...` directly — all three are identical.


### 2.1 Web UI

The same core is available in a local browser UI; the CLI remains the automation interface.

```bash
./run-web.sh                       # http://127.0.0.1:8000, opens a browser
./run-web.sh --no-open             # ...without opening one
./run-web.sh --port 8001           # another port
./run-web.sh --db other.db         # another athlete database
```

`run-web.sh` is a convenience launcher: it finds `.venv/bin/python` (falling back to
`python3`), checks the dependencies, refuses a non-loopback `--host`, and then runs the same
`strength-coach web` command. Everything else works unchanged:

```bash
./run-web.sh                       # http://127.0.0.1:8000, opens a browser
./run-web.sh --no-open             # no browser
./run-web.sh --port 8001           # another port

# or directly:
strength-coach web                 # http://127.0.0.1:8000
strength-coach web --open
strength-coach web --port 8001
```

It binds to **127.0.0.1 only** and has **no authentication**; do not expose it on a network.
The pages are Today, Outcomes, Prescribe, Workout, Programme, Review, Readiness, Cardio, Measures, Import, Exercises, Athlete, Settings, Terminal and Docs. Every load, RIR, warning
and calibration number still comes from Python — the browser only displays and submits forms.
Docs are rendered locally, so the UI works offline. **Import** accepts the training and
readiness CSVs in the browser; the files are parsed in memory and stored in SQLite, not written
to the repository.

```bash
.venv/bin/python -m strength_coach.cli web   # if the venv is not active
```

---

## 3. First run

```bash
strength-coach import
```

This reads the two CSVs into `data/coach.db` (git-ignored). It prints how many rows were
inserted, how many were already present as overlap, how many sessions were reconstructed,
and how many rows were quarantined. A new cumulative export is overlap-matched against the
stored rows, so old history is not duplicated; identical rows inside one file are still kept
as separate sets. Importing
the same file twice writes nothing the second time — identity is the source line, not the
content.

A quarantined row is **not** deleted: it is a row with no date or an exercise the taxonomy
cannot resolve. It stays visible and counted, because silently dropping rows is how real
violations disappear.

---

### 3.1 The workflow — how to actually use it

Think in four layers, not one big loop:

| layer | how often | where |
|---|---|---|
| **state** — goals, constraints, suitability, e1RM, block | once, then when life changes | Athlete page / `state` |
| **readiness** — sleep, energy, soreness, HRV/RHR, optional wearable | before each session | Readiness page / `readiness set` |
| **training** — prescribe, perform, import | each session | Prescribe / Import |
| **review + calibration** — marks, reports, adjustments | after sessions, weekly | Review / Calibrate |

The important rule: **readiness comes first, then the prescription.** A current or future
workout is refused until readiness is ready enough; that is deliberate, because the readiness
score changes the load and may trigger a deload.

#### First-time setup

1. **Import** the training and readiness exports (Import page or `strength-coach import`).
   Check the quarantine count; a row with no date or an unknown exercise is reported, not
   silently dropped. The full procedure, including when calibration happens, is §4.0.
2. **Record athlete state** (Athlete page or `strength-coach state`): primary goal, constraints,
   exercise suitability, and any e1RM overrides. Set the block start when the erector ramp
   should begin (`block --date YYYY-MM-DD`).
3. **Review a few recent sessions** so the rubric has marks. Do this while the sessions are
   fresh; reconstructed marks are kept but excluded from agreement. Calibration is **not** an
   import step — run it after this review (or weekly), not immediately after uploading.
4. **Optional device setup**: HRV/RHR are scored only after seven readings in the previous
   28 days. Set a per-athlete baseline window, minimum and slopes on the Readiness page if the
   defaults do not fit. A wearable readiness score (0-100) is optional and only a 10% blend.

#### Before each workout

1. **Log readiness** for today:
   ```bash
   strength-coach readiness set --date 2026-10-20 \
     --sleep 4 --energy 4 --mood 4 --soreness 4 --stress 4
   ```
   Device fields and the optional wearable score can be added in the same command or on the
   Readiness page. Any subset is valid, but a score needs at least three core fields plus sleep
   or energy.
2. **Check the readiness result.** The page/CLI shows the score, components, overrides, injury
   ceiling and whether a baseline was available. Do not use the old squat/bench/deadlift
   readiness fields; they are labels, not inputs.
3. **Prescribe the session**:
   ```bash
   strength-coach run --date 2026-10-20 --session-type auto
   ```
   Or use the Prescribe page. Check the warnings, rule citations, load sources and any
   constraints; a hard constraint or injury ceiling wins over the score. Poor readiness also
   removes one accessory set (main-lift volume is unchanged) in addition to the load/RIR cut.
4. **Optional:** print the rolling horizon with `strength-coach programme --weeks 4 --remaining`
   or the Programme page. Treat it as a forecast; the day's prescription is rebuilt when the
   day arrives.

#### After the workout

1. **Update the export and import it** (or use the Import page). A new cumulative export is
   overlap-matched against stored rows, so old history is not duplicated. A genuinely changed
   row is new, not silently merged.
2. **Review the session while it is fresh**:
   ```bash
   strength-coach review --session 2026-10-20
   ```
   Or use the Review page. Marks are append-only; leave an item blank if you do not remember.
3. **Catch up on missed reviews** with `strength-coach review --pending`; this is the routine
   that keeps calibration current.

#### Weekly or when something changes

- **Review** the new sessions and run the rubric calibration report (Review page or
  `strength-coach calibrate`). It is a report, not an automatic weight change.
- **Readiness calibration** (`strength-coach readiness calibrate`) compares the score with the
  historical labels. It is mimicry of those labels, not validation, and it does not auto-apply
  weights.
- **Baseline shadow** (`strength-coach readiness shadow`) compares the rolling-median HRV/RHR
  baseline with a trend projection. It is diagnostic only.
- **Symptoms/injury**: log a pre-session symptom when relevant; the injury signal can cap the
  readiness score and veto risky work. It never clears a constraint.
- **State changes** (new injury, goal change, exercise no longer suitable, new e1RM/test,
  block reset) go through the Athlete page or `state`. Never edit the database by hand.
- **Programme view** is a forecast, not a commitment; use it for planning, then prescribe the
  actual day.

#### The short loop

```text
import  →  state (once)  →  readiness  →  prescribe  →  perform
                                      ↓
                           import updated export
                                      ↓
                                review marks
                                      ↓
                         weekly calibration reports
```

#### CLI and UI are the same workflow

| step | CLI | UI |
|---|---|---|
| import | `import` | Import |
| athlete state | `state`, `block`, `e1rm`, `test` | Athlete |
| readiness | `readiness set` | Readiness |
| prescription | `run --date ... --session-type auto` | Prescribe |
| programme | `programme --weeks N [--start-session-type T]` | Programme |
| review | `review --session ...` | Review |
| rubric report | `calibrate` | Review → Run rubric calibration |
| readiness report | `readiness calibrate` | Readiness → Run calibration |
| baseline shadow | `readiness shadow` | Readiness → Run baseline shadow |
| baseline settings | `readiness settings` | Readiness → Baseline settings |

The Terminal page can run any of the CLI commands against the same database, but the dedicated
pages are safer because they validate and show the result in context.

## 4. The routines

### 4.0 `import` — load a history file, and when to calibrate

```bash
strength-coach import
```

Reads `data/raw/training_log.csv` and `data/raw/readiness.csv`; the **Import** page uploads the
same two files. A cumulative export is overlap-matched against stored rows, so old history is
not duplicated. Quarantined rows (no date, or an exercise the taxonomy cannot resolve) are kept
and counted, never silently dropped.

**"Should I run a calibration after importing?" — not because of the import.** Import adds
sessions. Calibration compares the engine's rubric scores with **your marks**, so with no marks
there is nothing to compare and `calibrate` prints `no marks yet`. The procedure is:

1. **Import and read the report.**

   | field | what to look at |
   |---|---|
   | new raw rows / overlapping | overlap means the export was already loaded; no duplicate sets |
   | clean sets inserted / existing | how much training history is new |
   | sessions written | reconstructed workouts |
   | quarantined | rows that could not be used; investigate a high count |
   | readiness days | days merged from the readiness export |
   | window | the date range actually covered |
   | issues | flags such as unknown exercise names or sentinel values |

2. **Review recent sessions** — `strength-coach review --pending` (up to 10 after the last
   reviewed session) or the **Review** page. The marks you enter are the calibration labels.
   Only `high`-confidence marks count toward the headline agreement. Do not reconstruct the
   distant past; `--pending` deliberately stops at the last reviewed session.

3. **Calibrate later, after the review.** `review` prints the report automatically;
   `strength-coach calibrate` reprints it, and the Review page has **Run rubric calibration**.
   Cadence: after a batch of reviews, weekly, or at the end of a block. Importing history does
   **not** require it, and re-importing does not invalidate existing marks.

So for a history file now: **import → check the report → review the recent sessions you actually
remember → calibrate after that**, then keep reviewing new sessions and re-run the report on the
same cadence.

**Two different calibrations, both report-only:**

| report | compares | where |
|---|---|---|
| rubric calibration | your marks vs the engine's rubric scores | `strength-coach calibrate` / Review page |
| readiness calibration | the readiness score vs the old readiness labels | `strength-coach readiness calibrate` / Readiness page |

Neither retunes anything automatically. A rubric change is a separate decision (`DEC-EVAL-03`);
the report flags an item for review after five marks and is used to decide, not to auto-adjust.

First import also needs the one-time setup in §3.1: athlete state, block start, and a readiness
entry before a current or future prescription.

### 4.1 `run` — critique the last session, prescribe a date

```bash
strength-coach run --date 2026-10-20
```

It critiques the most recent stored session on or before that date, prescribes the rolling session type for it,
stores both inside a run trace, and prints the prescription with the rule or stored set that
justifies every number.

Sample output (numbers are illustrative):

```
prescription 2026-10-20  (hinge, full)
  exercise                 sets    reps     load  rir  refs
  ---------------------------------------------------------
  trap_bar_deadlift           4     3-5      158.5    2  PRG-RIR-001, set:2026-10-05/7821
  bench_press_narrow          4     3-5      106.5    2  PRG-RIR-001, set:2026-10-05/7835
  pull_up                     3     6-10         0    2  PRG-DP-001, set:2026-09-20/7012
  lateral_raise               3   10-12       25.0    2  PRG-DP-001, set:2025-11-10/6565
  split_squat                 3    8-10       50.0    2  PRG-DP-001, set:example
  note: bench_main: chose bench_press_narrow from [...]
  note: PRG-EREC-001 not assessable: missing symptom.flare, block.week_index

critique 2026-10-15: composite 0.88
  RIR_ADHERENCE             0.75   3/4 rated sets inside the effort window
  WEEKLY_SPINAL_COST        1.00   weighted spinal cost 0 against cap 3
  ESSENTIAL_WORK             n/a   no prescription template for day 'unknown'
  ...
```

Two programme details worth knowing: **The squat session opens with a power slot** (`box_jump` 3×3-5,
maximal intent, full recovery, stop when height or quality drops — the "RIR 4" means far from
failure), and **The hinge session's pull slot is interchangeable** between `pull_up` and `lat_pulldown`;
the engine picks whichever you trained most recently and never compares their loads. Both are
explained, with the evidence, in [LONGEVITY-REVIEW.md](docs/LONGEVITY-REVIEW.md).

Useful flags:

| flag | effect |
|---|---|
| `--session-type T` | squat, hinge, bench_squat or bench_hinge (default: auto rolling) |
| `--llm on` | ask the configured model for a narrative (see §7) |
| `--force` | regenerate even though that date was already prescribed |
| `--db PATH` | use a different database |

Re-running the same date writes nothing unless you pass `--force`. Two runs produce two
append-only critique rows, by design: history is not rewritten.

If you have declared a block start (`block --date`), the week index drives a 4-week undulation
cycle: week 3 puts main lifts on the `maximal` scheme (1-3 reps; hinges stay at 3-5), and weeks
2 and 4 put accessories on `volume` (6-8). The prescription notes which DUP week it used. This
is a variety and fatigue-management tool — the evidence says undulating and linear
periodization are comparable — and it can be switched off in
`config/templates/undulation.v1.yaml`.

### 4.2 `review` — mark a session, sharpen the calibration

```bash
strength-coach review --session 2026-10-15
```

It prints the session (working sets, reps, loads, RIR), then the engine's scores, then asks you
for a score per item:

```
  RIR_ADHERENCE            engine 0.75  score 0-1:
```

- a number `0`–`1` (0, 0.25, 0.5, 0.75, 1) — higher is always better
- **Enter** — skip this item (writes nothing; an earlier mark is not overwritten)
- `q` — stop and save what you have

Then it asks how well you remember the session: `high`, `low` or `unknown`. **Only
`high` counts toward the headline agreement.** A mark from a session you cannot really
remember is kept for the record but excluded — it is evidence of a guess, not of the rubric.

Finally it asks for two **optional** numbers: overall session RPE (1–10) and session length
(minutes). Press Enter to skip either; they are stored append-only and can be corrected later.
Why ask: sets, reps and load give volume, but not how hard the session felt or how long it took
(no timestamps). Session RPE is a validated internal-load measure for resistance training; no
model reads it yet, so it is capture for later review and a possible future fatigue model.
Non-interactive form:

```bash
strength-coach review --session 2026-10-15 --session-rpe 7 --session-minutes 75
```

The Review page has the same two optional fields.

Catch up on a backlog in one go:

```bash
strength-coach review --pending            # unreviewed AFTER the last reviewed session, up to 10
strength-coach review --pending --limit 3
```

`run` prints how many sessions are unreviewed and points at this command, so a new workout
does not silently leave the backlog behind. It deliberately stops at the last reviewed workout:
the distant past does not need reconstructing. When manual workout logging lands (v0.2 §4.2), the
same catch-up runs as part of concluding and logging the session.

**You do not need ten sessions before using the app.** Ten remembered sessions per item is the
threshold for *retuning* a definition or weight (`DEC-EVAL-03`), not for using the tool. Calibration
runs from the first review and updates after every session; the rubric simply is not re-fitted
until there is enough evidence.

Marks are append-only: marking a session again adds a correction; the latest mark per
item wins, older ones stay in the table.

You can also supply marks from a file instead of typing:

```bash
strength-coach review --session 2026-10-15 --scores private/eval/labelled.yaml
```

### 4.2a Settings

The **Settings** page configures the optional model and browser-only defaults.

- **Language model** — enable/disable narration and selection, set model, endpoint, temperature,
  max tokens and timeout; the API key is write-only and masked after saving. Settings live in
  the git-ignored `config/llm.local.toml`; environment variables override the file.
- **Prescribe defaults** — default minimum-session target and whether to show different lifts
  (C) by default. These only pre-fill the Prescribe page.
- **App** — version, database path and LLM config path, all local-only.

With the model disabled, every deterministic feature still works; only the prose/selection
choice is unavailable.

### 4.3 `calibrate` — the running picture

Run this **after you have reviewed sessions**, not as part of importing: with no marks it exits
with `no marks yet`. It is a report; it never retunes the rubric.

```bash
strength-coach calibrate
```

```
session       confidence    compared  agreement     mae  disagreements
2026-10-05    high                 5        60%    0.23  ESSENTIAL_WORK, ROTATION
2023-12-13    low                  4        25%    0.41  ...

headline (high confidence only): 5 comparable items, agreement 60%, mae 0.23

per item (high confidence only)
  RIR_ADHERENCE              1       100%    0.06
  ROTATION                   1         0%    0.40   revisit this item's definition or weight
```

How to read it:

- **agreement** — share of items where your mark and the engine's score are within ±0.25
  (one marking step).
- **mae** — mean absolute difference.
- **compared** — how many items were comparable. An item the engine could not measure
  (`n/a`) is never counted, so it can neither flatter nor punish the result.
- **"revisit this item"** appears only once an item has **five** marks and still disagrees by
  more than 0.25.

Nothing is retuned automatically. A rubric change is a decision, made after reading the
report, and it bumps `RUBRIC_VERSION` so older marks stay interpretable.

### 4.4 `state` — record your goals, limits and suitability

```bash
strength-coach state --import private/athlete-state.yaml
strength-coach state
```

The web **Athlete** page edits all of this append-only: profile, constraints, suitability,
e1RM overrides, strength tests, block start and symptoms. The CLI below remains the scripted
route. This is the §11 athlete state: goals, constraints and per-exercise suitability. It exists so
a hard constraint can veto a prescription deterministically, rather than living in a prompt.

- **constraint** — `hard_exclude` vetoes the exercise; `caution` and `monitor` are recorded
  but do not block. A resolved injury is `monitor`, not `hard_exclude`.
- **suitability** — `can_do: false` is a hard block; `will_do: false` is a preference the
  engine reports as a warning ("a substitution is needed"), never treats as a safety veto.
- The tables are append-only: re-running the import with `--force` adds a new version, and
  `state` always shows the latest.

If no state is recorded, a prescription is still produced but says so: *"athlete state not
recorded: constraints were not evaluated"*. Silence is not permission.

To rate one exercise without editing the YAML:

```bash
strength-coach state --rate EXERCISE_ID --can-do yes --will-do yes --feels-bad no
```

An unrated exercise is "unknown", which is why a main-lift substitution (see §4.8) is refused
until its replacement has a rating.

### 4.9b Readiness feedback

```bash
strength-coach readiness feedback --weeks 12
```

Read-only follow-up of stored readiness reductions (associations only; no tuning). Available
as the **Readiness feedback** panel on the Outcomes page.

### 4.9a Quick readiness presets and context

```bash
strength-coach readiness preset --name good_to_train
strength-coach readiness context --flags travel,alcohol
strength-coach readiness context
```

Presets write ordinary sleep/energy/soreness/stress readings with `source=preset`; they do
not bypass the readiness gate or the minimum-data rule. Context flags are displayed beside
readiness and do not change the score by default. The Readiness page exposes the same
buttons and checkboxes.

### 4.4f `regime` — read-only regime check

```bash
strength-coach regime --weeks 8
strength-coach regime --weeks 12 --json
```

Flags a main lift whose working volume fell sharply while a same-category substitute
rose. It is a review question, not a verdict and never a prescription change. See
[REGIME-CHANGE.md](docs/REGIME-CHANGE.md).

### 4.4e `prospective` — W5 review

```bash
strength-coach prospective --weeks 8
strength-coach prospective --weeks 12 --json
```

Read-only 8/12-week check defined in `docs/W5-PROSPECTIVE-EVALUATION.md`: stable-lift
e1RM status, attendance, planned-vs-completed work, RIR adherence, measured duration,
symptoms, sRPE, coverage and review flags. No model or prescription effect.

### 4.4d `run --minimum-session`

```bash
strength-coach run --date 2026-10-23 --minimum-session --target-minutes 45
strength-coach run --date 2026-10-23 --minimum-session --target-minutes 30 --minimum-include-main
```

A user-selected, volume-only fallback. The default tier reduces non-essential accessory work
and preserves main lifts; the deeper tier reduces main-lift sets to a floor of two. Load,
RIR, reps and exercise identity are unchanged. It is never automatic. The UI has the same
controls on the Prescribe page.

### 4.4c `outcomes` — a descriptive multi-week review

```bash
strength-coach outcomes --weeks 8
strength-coach outcomes --weeks 12 --json
```

Read-only 4/8/12-week review of main-lift e1RM change, weekly volume, target-based
attendance, sRPE/duration, readiness, symptoms, spinal-cap weeks, deload provenance, cardio
and measurements. Missing data is shown as unknown; the report makes no causal claim and
never changes a prescription.

### 4.4b `programme` — a rolling forecast

```bash
strength-coach programme --weeks 4
strength-coach programme --weeks 4 --remaining
```

It prints a dated rolling session-type forecast for the next N weeks, three sessions per week
on Monday/Wednesday/Friday. Use
`--start-session-type squat|hinge|bench_squat|bench_hinge|auto` to force the first session; the
default is the rolling rule. This is a **forecast**: the day's prescription is rebuilt when the
day arrives, using current e1RM, readiness and symptoms. It is not a fixed block and persists
nothing. The first session is marked `fatigue_reduced` if the last two weeks exceeded the
spinal cap or the last two sessions both flared.

### 4.5 `block` — declare or reset week 1

```bash
strength-coach block --date 2026-11-02          # declare week 1
strength-coach block --date 2026-11-02 --force  # reset: the ramp restarts at week 1
```

The block anchor drives the erector ramp. It is **declared, never inferred** (`DEC-RAMP-01`):
a gap in the log cannot start a block, because gaps are non-adherence. Resetting is a genuine
restart — the ramp goes back to week 1 rather than continuing at week 8 (`DEC-RAMP-02`).

### 4.6 `e1rm` — override the estimated max

```bash
strength-coach e1rm set --exercise ssb_squat --kg 120 --from 2026-11-01 \
    --reason "tested single"
strength-coach e1rm set --exercise ssb_squat --kg 150 --until 2026-12-01   # temporary
strength-coach e1rm list
```

Use an override when you know a value the formula cannot see: a tested single, a
post-layoff starting point, or an estimate that disagrees with reality. From `--from` (or
today) until `--until` (or forever), the override outranks the computed e1RM.

In the prescription it shows up as a normal load, with:

- a citation `e1rm_override:<id>` in its `refs` column, and
- a note: *"using a manual e1RM override"*.

Worth knowing:

- **Append-only.** A correction is another `e1rm set`; the latest applicable row wins and
  the older one stays in history.
- **Temporary is first-class.** `--until` expires it; after that the computed estimate
  returns on its own.
- **It only changes the derived load.** History, scores and verdicts are untouched.
- **Bulk entry** works through the state file: add an `e1rm_overrides:` list and run
  `strength-coach state --import private/athlete-state.yaml`.

**Calibration report.** `strength-coach e1rm calibrate` compares each measured `test` with the
formula estimate the app would have used before it: per-lift median ratio, mean bias and MAE.
The table includes every lift with a recent e1RM, even before any measured test: it shows
both the **formula** and the **active measured override** as raw → effective (decayed), which
source is used, the last set, and "no measured test; formula only". It also applies
a **bounded correction** when at least 3 tests exist and the 95% bootstrap CI
of the median ratio excludes 1.0: the formula e1RM is multiplied by the median ratio, clamped
to ±10%, and cited as `MOD-E1RM-001`. Ambiguous evidence or a larger bias applies nothing.
Measured overrides are never adjusted. The same table is on the Athlete page.

### 4.7 `symptom` — the pre-session back reading

```bash
strength-coach symptom --level 0                          # today, no symptoms
strength-coach symptom --date 2026-11-03 --level 2 --settled no --note "tight after sitting"
strength-coach symptom --show
```

One number for the whole back, recorded **pre-session**: `0` none, `1` awareness, `2`
annoying, `3` limiting. `--settled` records whether it settled within 48 hours.

A reading counts as a **flare** when the level is 2 or more, or when a level of 1 did not
settle within 48 hours. A flare makes `MOD-BACK-001` apply to the next prescription: erector
work returns to the weeks 1-3 dose and main lifts are held at RIR 3.

With a reading **and** a declared block start (`block --date`), `PRG-EREC-001` stops
returning `unknown` and grades the ramp, citing `symptom:<date>`. Without either input it
still says `unknown` — no reading is never read as "no flare".

Correct a mistake by logging again; the latest entry for the day wins and the earlier one
stays in history.

### 4.8 `run --propose` — the model may suggest, the rules decide

```bash
strength-coach run --date 2026-11-03 --llm on --propose
strength-coach run --date 2026-11-03 --llm on --propose --yes   # no prompt
```

The model sees the deterministic session and may propose a **structural** change:

- swap a non-essential item for a same-pattern alternative;
- change an item's set count within configured bounds;
- drop a non-essential item;
- reorder the session;
- pick a menu option Python computed: `keep`, `easier`, `harder`, `heavier` or
  `lighter` (RIR and load are re-solved together);
- **substitute an essential lift**, but only for a primary compound you have rated
  can-do/will-do with no "feels bad", at most once per proposal and no more often than every
  42 days; a main-lift swap always asks for confirmation, even with `--yes`;
- change the **rep scheme**: `maximal` (1-3, main lifts only and never the hinge),
  `strength` (3-5), `volume` (6-8), `accessory` (8-12). The load is solved for the scheme.

It may **not** supply a load, RIR, percentage or velocity. Any such field is rejected
before the proposal is even applied, because the model never does arithmetic here.

Set counts are the one number it may change, within configured bounds. Menu options are bounded
by the RIR rule itself: with a 1-4 window, `harder` at RIR 2 is RIR 1, and at RIR 1 it is not
offered at all. If the window changes on evidence, the menu changes with it.

You see the proposal and its one-line reason, then accept or decline (`--yes` skips the
prompt). If you accept, the prescription is stored with `approved_by = llm+policy`; if you
decline or the proposal is invalid, the deterministic session is kept, the run is marked
`llm_downgraded` when the model was at fault, and the proposal plus reasons stay in the run
trace.

A proposal is **not attempted** when a safety modifier already changed the session (a
fatigue cut or a back flare). The safety decision outranks the suggestion.

### 4.9 `test` — a strength test that updates the e1RM

```bash
strength-coach test --exercise ssb_squat --kg 140 --reps 3 --yes
strength-coach test --exercise ssb_squat --kg 120 --reps 1 --max
strength-coach test --exercise ssb_squat --kg 140 --reps 3 --e1rm 165 --yes
strength-coach test --status
```

`test --status` shows the 3RM/5RM cadence: the next scheme and due date. The reminder interval
is 10 weeks by default (`config/test-cadence.v1.yaml`); it never records a test automatically.

A **3RM or 5RM** is the default and the recommended test: it gives the e1RM the solver
needs without loading the spine like a single. The command reports the estimate first, then
records it as a `measured` e1RM override, so the next prescription uses it and cites
`e1rm_override:<id>`.

- `--e1rm` lets you **override the computed value** with your own, after the test.
- `--date` sets when the result takes effect (default: today).
- A test is an **assessment, not a training set**: it is not counted as volume and does not
  enter the RIR rule, because a maximal test is RIR 0 by definition.

**True 1RM** is allowed, sparingly:

- requires `--max` (a single rep without it is rejected);
- asks for confirmation unless you pass `--yes`;
- is limited to one every **56 days** by default (`--force` overrides, and the config can
  change the interval);
- 3RM/5RM tests more often than every 28 days print a warning — testing becomes a stimulus.

The evidence behind this is in [TRAINING-DYNAMICS.md](docs/TRAINING-DYNAMICS.md).

### 4.10 Gaps, returns, and the injury signal

**Gaps are detected, not declared.** Every prescription compares its date with the last stored
session. If the gap is long enough, the session is amended and says so:

| gap | what changes |
|---|---|
| under 14 days | nothing |
| 14-27 days | keep load, one extra RIR |
| 28-55 days | load −5%, one extra RIR |
| 56+ days | load −10%, one extra RIR, erector ramp steps back one stage |

The amended items cite `MOD-GAP-001` and the note reads e.g. *"MOD-GAP-001: 31-day gap;
prescription amended"*. Bodyweight work loses a set instead of load. The DUP cycle counts
only weeks with a session or a measured test, so a missed week does not advance it. The
thresholds are config (`config/thresholds.v1.yaml`, `continuity`) and remain assumptions
(§4.10 is documented in [CONTINUITY.md](docs/CONTINUITY.md)).

**Injury signal.** Log a symptom number per region — low back by default:

```bash
strength-coach symptom --level 1                    # low back, today
strength-coach symptom --region knee --level 2      # a knee flare
strength-coach symptom --show                       # recent readings, all regions
```

`state` and every prescription then show a general signal plus one per region (`low_back`,
`biceps`, `knee`). A region is `unknown` with no readings, `insufficient` when the last reading
is more than 14 days old, `active` while it is flaring, `monitoring` in between, or `review`
when there is enough evidence to look at a suitability rating.

`review` needs a symptom-free streak **and** enough **tolerated** sessions since the last
flare. Tolerated means the session loaded the region and a reading in the following 7 days
showed no flare; a session with no reading is `unverified` and does not count. The streak and
the number of sessions both scale with how often you have flared before (28 days + 14 per prior
flare, 4 sessions + 2 per prior flare, capped).

A `review` may recommend looking at a suitability rating; it never sets one. Every display
says: *"Not medical clearance. A symptom-free streak is weak evidence; the athlete decides."*
Readiness is not part of it. The regions and the lifts that load them are config
(`config/injuries.v1.yaml`); the full definitions and evidence are in
[INJURY-SIGNAL.md](docs/INJURY-SIGNAL.md).

### 4.10i Workout mode — start, log, end

The local UI has a **Workout** tab. Build a prescription on **Prescribe**, then choose
**Start workout**.

- The seven self-report readiness fields are required; HRV, resting HR, bodyweight, body-fat
  and wearable score are optional.
- If readiness changed after the prescription was built, the UI asks before starting with the
  old plan; cancel and rebuild if you want a new prescription.
- The prescription snapshot is frozen. Manual sets are added against it; remove a set with the
  **Remove** button (a removal event, not a delete).
- **End workout** uses the measured timer unless you enter a duration override. Session RPE is
  required unless you tick **sRPE not recorded**.
- **Abandon** keeps the record but does not mark it completed.

During the workout, the plan is editable: adjust planned sets, swap an exercise, add or remove
an exercise. The original prescription is frozen; every override is an event and the modified
plan is shown separately. Actual sets can be edited inline after import; imported values show
field-level conflicts and the last import can be undone.

**CSV import:** in Workout mode, paste or choose a file with columns
`Exercise,Set,RPE,Value,Weight,Reps`. Preview first. RPE is converted with `RIR = 10 − RPE`,
fractions round down, and RIR above 6 is capped at 6 and treated as a warm-up. `???` is
missing. A recognised exercise that is not in the prescription is added to the workout plan as a
new item; an unrecognised exercise is reported and the import is not applied. Import replaces the
same exercise/set and leaves other manual sets alone. The file has no date, so it only imports
into the active workout. On **End workout**, sets are materialised, actual vs modified plan and
actual vs original prescription are shown, the deterministic rubric is persisted, and
**Review workout** opens the rubric sheet. Saving marks runs calibration and closes the workout.
**Optional per-rep velocity:** a second CSV can be pasted or chosen in the same import panel:
`Exercise Name,Set Number,Metric Name,Rep Number,Velocity`. A blank `Rep Number` is the set mean;
numbered rows are reps. It must match an existing exercise/set in the main CSV and only
`Mean Concentric Velocity` is accepted. The main CSV `Value` wins if both means exist; a mismatch
is shown as a warning. The table is optional and never creates a set. After ending the workout,
the end screen shows first/last velocity and loss per set; this is descriptive only.

The standard dated training export remains the Import-page backfill path. Workout CSV import is
in-workout only. This plan is **closed**; CLI workout commands cover
status/add/update/remove/end/import, while starting a workout remains UI-only.

### Can I delete a past workout?

**No.** There is no hard delete, and that is deliberate: clean sets, prescriptions, critiques and
marks are append-only, and deleting one would change e1RM, volume and review history.

- An **in-progress** workout can be abandoned.
- A wrong set during an active workout can be removed or edited.
- A **completed** workout cannot currently be deleted, edited or voided.

The recommended future operation is **void**, not delete: keep the rows, add an append-only void
reason, exclude the session from reports and prescriptions, and allow unvoid. It is documented in
[DATA-MODEL.md](docs/DATA-MODEL.md#17-deleting-or-voiding-a-session) but not implemented.

### 4.10b `cardio` — capture the other half

Cardio is a separate exposure, not a strength session. It is captured first; it does **not**
change a load yet and no fatigue model reads it.

```bash
strength-coach cardio --modality run --minutes 40 --avg-hr 150 --max-hr 170 --srpe 6
strength-coach cardio --modality walk --minutes 30
strength-coach cardio --show --weeks 12
```

`--date` defaults to today, `--distance-km` is optional, and sRPE is 1-10. `--show` prints the
last N weeks: sessions, total and average minutes, weekly breakdown, modalities, and the WHO
reference range (150-300 min/week) as **context**, not a target. The Cardio page in the web UI
does the same. The evidence and the proposed prescription are in
[LONGEVITY-REVIEW.md](docs/LONGEVITY-REVIEW.md).

### 4.10f `exercise` — catalogue listing/editing

```bash
strength-coach exercise list
strength-coach exercise set --id front_squat --json '{"pattern":"squat"}'
```

Edits and additions are written to `config/exercises/overrides.v1.yaml`; the checked-in
taxonomy is not rewritten. The web **Exercises** tab is the form-based version.

### 4.10d Session types and rolling selection

`run` and the Prescribe page default to a rolling session type rather than the legacy fixed
A/B/C calendar (removed by migration 0023). The types are `squat`, `hinge`, `bench_squat` and `bench_hinge`; the rule balances
squat/hinge/bench emphasis over recent sessions. The four types are the only override labels:

```bash
strength-coach run --date 2026-10-20 --session-type auto
strength-coach run --date 2026-10-20 --session-type hinge
```

### 4.10e `select` — exercise selection

Apply it to a prescription with:

```bash
strength-coach run --date 2026-10-20 --session-type squat --apply-selection
strength-coach run --date 2026-10-20 --session-type squat --apply-selection --selection-confirm
strength-coach run --date 2026-10-20 --session-type squat --apply-selection --selection-llm
```

```bash
strength-coach select --date 2026-10-20 --session-type hinge
strength-coach select --date 2026-10-20 --session-type hinge --include-different
strength-coach select --date 2026-10-20 --session-type hinge --llm
```

Ranks the configured variants for the chosen session type from readiness, recent stress,
rotation and preference. Constraints and `can_do: false` exclude a candidate; an active injury region
penalises one. `--llm` lets the configured model choose **only from that filtered list**;
Python validates and falls back deterministically on any error. Candidates now carry a
comparability class:

- **A** — load-comparable; can apply automatically.
- **B** — near-comparable (same pattern, different grip/bar/ROM/stability); requires explicit
  confirmation with `--selection-confirm` or the Prescribe checkbox.
- **C** — different lift/load basis; hidden by default and **never applied automatically**.

The selector still re-solves the load from the selected lift's own history. Class C is shown
only with `--include-different` (or "show different lifts" in the UI) for information.
A display-only "own-history" ratio (latest e1RM versus that lift's own recent median) appears
beside each candidate; it does not affect the score, ranking, class or prescription.
The Prescribe **Apply selection** toggle applies A, and B only when confirmed.

### 4.10h `volume` — weekly hard-set ledger

The Today page also has a small **Descriptive progress** panel: sRPE coverage, performance
ratio, weekly volume status and latest back symptom. It is monitoring only and never changes a
prescription.

```bash
strength-coach volume --weeks 4 --date 2026-10-20
```

Working sets by movement pattern, average per week, total and target status. It reports drift.
When a pattern is below MEV for three weeks, the engine adds **one accessory set** to that
pattern (`MOD-VOL-002`); main lifts are never increased by this rule. The MRV cap still applies.
The weekly volume panel also shows **heavy spinal sets** — high-fatigue spinal exercises at
RIR ≤ 1 — as context only. This is deliberately not load-weighted and does not change the cap
or prescription.

The Readiness page's **Volume valve** sets whether poor readiness removes sets and how many.

### 4.10g `continuity` — return-to-training calibration

```bash
strength-coach continuity --date 2026-10-20
```

Shows per-band return count, e1RM retention median, bootstrap interval, fixed factor and
applied factor. Fixed continuity remains the fallback when a band is under-powered.
`--allow-relax-fixed on|off` changes whether a well-observed band may remove part of the fixed
reduction; the same checkbox is in the Prescribe continuity panel.

### 4.10d `fatigue` — the strength model in shadow mode

```bash
strength-coach fatigue --date 2026-10-20
```

Per-lift fitness/fatigue state fitted from hard sets and your own e1RM observations, plus an
**overall** relative-e1RM row. It shows R², span, fitness/fatigue/state with approximate 95%
intervals, and a status (`ok`, `weak fit`, `insufficient`, `unstable`);
it refuses parameters when the data are sparse or ill-conditioned. **No prescription reads
it.** The Prescribe page shows the same table under **Strength fatigue model**. See
[FATIGUE-FITNESS.md](docs/FATIGUE-FITNESS.md) §4a.

### 4.10f `validate` — retrospective walk-forward

```bash
strength-coach validate --max-dates 12
```

Replays past cutoffs using only earlier data. It checks:

- **continuity** against the fixed rule;
- the **strength fatigue** model against persistence;
- volume only descriptively, because no predictive volume model exists;
- selection is excluded, because there is no counterfactual.

The 12-date result was: fatigue relative MAE 0.158 vs 0.074 persistence; continuity 0.150 vs
0.128 fixed. Both lost to their baselines, so neither is adopted. The Prescribe page has the same
report under **Retrospective validation**. This is not prospective validation; see
[RETROSPECTIVE-VALIDATION.md](docs/RETROSPECTIVE-VALIDATION.md).

### 4.10e Deload policy

A deload is a **low-volume week**, not a new training block:

- a **scheduled suggestion** every 6 weeks from your declared `block_start_date`;
- you are asked at each workout in that week; default is **no**;
- declining skips only that workout; the next workout in the week asks again;
- after the week ends, the suggestion waits for the next cycle;
- also triggered reactively by two consecutive weeks over the spinal cap or two consecutive
  back flares — these reactive triggers are **automatic**;
- one set removed per item (never below two), load reduced 10%, RIR increased by one;
- cited as `MOD-DELOAD-001` in the prescription and shown on Prescribe/Programme.

Without a declared block anchor there is no scheduled calendar position, so only reactive
deloads run. For scripts, `run --deload no|yes` controls the scheduled suggestion; the default
non-interactive behaviour is **no deload**. The six-week interval is a configurable policy
(`config/deload.v1.yaml`, `ASSUMPTION-32`), not a claim of a proven optimal schedule.

### 4.10c `measure` — periodic measurements

Readiness is daily; these are **outcomes** you test every few weeks. They never change a load.

```bash
strength-coach measure --metric vo2max --value 45.2 --method "step test"
strength-coach measure --metric grip_strength_kg --value 52 --method "dynamometer"
strength-coach measure --metric sit_to_stand_5_s --value 9.4
strength-coach measure --show
strength-coach measure --show --metric vo2max
```

The catalogue is `config/measurements.v1.yaml`: `vo2max`, `grip_strength_kg`,
`sit_to_stand_5_s` (lower is better), `steps_per_day`, `sitting_hours_per_day` (lower is
better). Each metric is declared once with its direction and aggregation; a later direction
change is refused rather than silently reinterpreting old values. `--method` keeps the protocol
next to the number, which matters for VO2max estimates.

Grip strength is **only** a measurement now; readiness no longer accepts it
(`DEC-GRIP-01`). Log it here or on the Measures page.

The **Measures** page in the web UI does the same and shows the latest value and change per
metric.

---

## 5. Reading the output

### The prescription

Main lifts carry three **warm-up ramp sets** at roughly 50/70/85% of the working load; they are
not counted as working volume. The Prescribe page shows them under the exercise.

| column | meaning |
|---|---|
| exercise | canonical id from the taxonomy, not the raw log name |
| sets | prescribed working sets |
| reps | the rep range; add load only at the top of it |
| load | solved from your recent e1RM, **rounded down** to your increment |
| rir | target reps in reserve |
| recent stress | advisory decayed hard sets: `high`, `normal` or `low`; **never changes the load** |
| readiness | per-lift 0–1 score from global readiness + e1RM trend, RIR and VBT; can only **lower** a load |
| e1RM n | usable sets behind a formula e1RM; `—` for a manual override, last-load fallback or non-e1RM item |
| refs | the rule id **and** the stored set that justify the load |

Loads come from the best usable e1RM in the last 84 days, inverted through the same
Epley+RIR formula that produced it, then rounded down to 0.5 kg (your microplates). Rounding
up would push the set above the target RIR, so it never happens. An e1RM older than 21 days is
decayed by 1% per week (capped at 10%); this applies to measured overrides too, and cites
`MOD-E1RM-DECAY-001`. If the continuity rule is already handling a 28+ day gap, the age decay
is skipped to avoid counting the same absence twice.

`readiness` is the per-lift score: it starts from the global/category readiness and nudges it
by recent e1RM, mean RIR and velocity-vs-calibration. A lower score can reduce this lift's load
(and add RIR); a higher one never increases it. No per-lift readiness instrument is validated,
so this is deliberately asymmetric (`docs/LIFT-READINESS.md`).

`recent stress` is a fixed exponential decay of your working sets (48 h half-life, high
at 6 decayed sets). A lift prescribed within 48 h of high stress gets a warning saying so, but
the load and RIR are unchanged — it is context for your judgement, not a fatigue model. The
constants are in `config/stress.v1.yaml` and are assumptions (`ASSUMPTION-24`).

That e1RM is an **estimate, not a calibrated measurement**: Epley with RIR folded in is an
approximation, and no bias correction is applied. A measured `test` writes an override and the
next prescription cites it. A calibration report (measured vs predicted, bias/MAE per lift) is
proposed but not implemented; see [FATIGUE-FITNESS.md](docs/FATIGUE-FITNESS.md) §6.

If a load is `-` and the output says `NO_LOAD`, there was no usable e1RM in the window. The
prescription is then **not executable**, and it says so instead of inventing a number.

`CONSTRAINT_VETO:<exercise>` means a stored hard constraint blocks that exercise; the
prescription is not executable until the constraint or the template changes. A warning that
an exercise "you will not do" appears is a **preference**, not a veto — it asks for a
substitution rather than blocking the session.

### The critique

Seven items are measured, one is not:

| item | measures |
|---|---|
| `RIR_ADHERENCE` | share of rated primary-compound sets inside the allowed window (RIR 1–4) |
| `PROGRESSION_ADHERENCE` | accessories added load only after topping the rep range |
| `WEEKLY_SPINAL_COST` | the week's weighted spinal load against a cap of 3 |
| `ESSENTIAL_WORK` | the day's essential lifts were present |
| `REDUNDANCY` | no hinge + erector stacking, no two hinge lifts |
| `ROTATION` | selection stable for self-directed sessions; expected rotation for app-assigned |
| `SESSION_DURATION` | measured live-workout duration against 80 planned / 90 hard; imported sessions remain unmeasurable |
| `VELOCITY_LOSS` | **not measurable** — one mean velocity per set |

The rubric version is `1.1.0`; the six original weights were scaled by 0.95 to make room for a
0.05 duration weight. The composite still re-normalises over measurable items.

`composite` is the weighted mean over the items that were measurable, re-normalised — a
missing metric never drags the score to zero.

### 5.1 Readiness — how it is derived

Readiness can only *reduce* a prescribed load, so its derivation is written down in full in
[READINESS.md](docs/READINESS.md). In short:

- the export is read as text and then as numbers; `0` becomes missing in the fields where a
  physical zero is impossible (bodyweight, HRV, RHR, fat %, the three readiness scores);
- duplicate rows on one date are merged: **most complete wins, ties go to the latest**, and
  the merge note records which candidate won and why;
- a global 0.00–1.00 score is computed from sleep, energy, mood, stress and soreness; it needs
  at least three of those and either sleep or energy;
- HRV and RHR enter at half weight only with a 28-day baseline (7 readings); an optional
  **wearable readiness score (0–100)** is a 10% blend, never a replacement;
- the old sleep/energy rule remains a floor (at or below 2 still cuts loads by 5%);
- missing or insufficient readiness blocks a current/future workout rather than silently
  omitting the modifier;
- the three old per-lift readiness values are calibration labels, not inputs;
- readiness is **not per lift**: there is one global score plus manual **category** overrides
  (squat, hinge, horizontal push, …). An exercise inherits its category's factor. A validated
  per-lift readiness score does not exist.

**Manual entry (any subset):**

```bash
strength-coach readiness set --date 2026-10-20 --sleep 2 --energy 3 --soreness 1
strength-coach readiness set --date 2026-10-20 --energy 4 --note "slept badly"
```

The 1-5 fields and the device fields (HRV, resting HR, bodyweight, body fat, grip strength in kg,
wearable readiness 0–100) are accepted in any combination. The old squat/bench/deadlift readiness fields are not. A manual value wins
**per field**; an imported row fills the fields you did not provide. Re-logging a date appends
a new version and the latest value wins — nothing is edited or overwritten. The command prints
each field with its source (`manual` or `import`).

Bulk entry uses the same store through `state --import`:

```yaml
readiness:
  - date: 2026-10-20
    sleep: 2
    energy: 3
```

Override the computed score at global or category scope (0.00–1.00, reason required):

```bash
strength-coach readiness override --date 2026-10-20 --scope global \
  --value 0.55 --reason "felt worse than the form"
strength-coach readiness calibrate     # report only; never auto-applies weights
```

A **current or future workout requires a ready assessment**; otherwise `run`/the web page
refuses and tells you what is missing. Historic prescriptions remain reproducible. The web
Readiness page also shows the computed score and has a **Run calibration** button.

To change which fields matter, the threshold, or the merge tie-break, edit
`config/readiness.v1.yaml`. Only implemented values are accepted — anything else raises
rather than silently doing nothing.

**Per-athlete baseline settings** override the config from a date:

```bash
strength-coach readiness settings --date 2026-10-20 \
  --baseline-days 14 --baseline-min-readings 5 \
  --hrv-slope 0.4 --rhr-slope 0.4 \
  --hrv-weight 0.5 --rhr-weight 0.5 --wearable-weight 0.1
strength-coach readiness shadow --date 2026-10-20   # diagnostic only
```

The same controls are on the Readiness page. Settings are append-only; the latest effective
row wins. `readiness shadow` compares the rolling-median baseline with a trend projection
and never changes a prescription.

### 5.2 Velocity targets — what they mean

When the export contains enough velocity data, a prescription item gains a `vel` column:

```
exercise                 sets    reps     load  rir    vel  refs
bench_press                 4     3-5     84.5    2   0.31  PRG-RIR-001, set:...
```

That number is the **calibrated median mean velocity** for that lift, rep count and effort
band, taken from your own clean sets. It is not a population table. A target appears only when
the calibration has **12 clean sets across 3 sessions** for the lift (or 24 in its movement
family), and the basis next to it records the scope and sample size.

How to use it: the first working set should move at roughly the target. Noticeably faster means
the load is light for the day; noticeably slower means accumulated fatigue or a heavy day. It is
a reference, not a stop rule — the app does not yet measure within-set velocity loss.

What is deliberately not shown:

- a target when the data is thin — the item simply has no velocity, and the prescription says
  **unavailable** rather than guessing;
- a target for the **trap-bar deadlift**, because the velocity-to-RIR relationship for the hex
  bar failed accuracy criteria in the literature and in practice;
- a target for a session already modified by a fatigue or back-flare rule, because the load no
  longer matches the calibration.

The evidence and best practices are in [VBT-EVIDENCE.md](docs/VBT-EVIDENCE.md); the upgrade
path (per-rep velocity, velocity loss, individual load-velocity profiles) is in
[VBT-CALIBRATION.md](docs/VBT-CALIBRATION.md) §9.

---

## 6. Configuration

Everything that changes a number lives in config, not code.

| file | what it controls |
|---|---|
| `config/thresholds.v1.yaml` | load increment (0.5 kg), rounding, e1RM window (84 days), fatigue multiplier (0.95) |
| `config/templates/session-types.v1.yaml` | session slots, sets, rep ranges, rest |
| `config/rules/programme.v1.yaml` | the constitution: rule ids, severities, thresholds |
| `config/exercises/taxonomy.v1.yaml` | exercise identity and properties |

Change an increment or a rep range and the golden test will fail on purpose — update the
fixture only if the change is intended.

---

## 7. The LLM (optional)

With nothing configured, the system uses `NullLLM`: no network call, no narrative, everything
else identical. To enable narration:

```bash
cp config/llm.example.toml config/llm.local.toml   # git-ignored
$EDITOR config/llm.local.toml                      # base_url, model, api_key
strength-coach run --date 2026-10-20 --llm on
```

The default endpoint is DeepSeek (`https://api.deepseek.com/v1`, `deepseek-chat`), so setting
a provider and a key is enough. Any OpenAI-compatible endpoint works.

Check it before relying on it:

```bash
python tools/llm_check.py           # effective settings, key masked
python tools/llm_check.py --call    # one test prompt
```

Environment variables override the file: `STRENGTH_COACH_LLM_PROVIDER`, `_MODEL`,
`_BASE_URL`, `_API_KEY`, `_TEMPERATURE`, `_MAX_TOKENS`, `_TIMEOUT_S`, and
`_CONFIG` for a different file.

What the model may and may not do:

- it receives the facts as JSON and is told to use only those numbers;
- its output is stored as a `run_event`, **never** written into a prescription, a score or a
  verdict;
- a failed call is recorded and the deterministic run continues.

The model may **narrate or propose** within the rules (`run --propose`). It proposes a
structured intent — a substitute, a set change, a scheme — and the policy engine accepts,
adjusts or vetoes it; the numbers still come from Python, and the trace records
`approved_by = llm+policy` when a proposal survives. The CLI remains the proposal surface;
the web UI does not yet expose it.

---

## 8. The other tools

| command | what it does |
|---|---|
| `python tools/profile_data.py` | regenerates the data profile (reproducibility check) |
| `python tools/baseline.py` | regenerates the strength baseline |
| `python tools/import_export.py` | same as `strength-coach import`, usable without install |
| `python tools/eval_prepare.py --session DATE` | prints a labelling sheet and writes a skeleton |
| `python tools/backtest.py` | agreement report from the database (`--labels` for a YAML file) |

Tests: `.venv/bin/python -m pytest`, and the markers `-m golden` (locked numbers) and
`-m integration` (touches the real CSVs).

---

## 9. Troubleshooting

- **`strength-coach: command not found`** — the venv is not active. Run
  `source .venv/bin/activate` first, or use `.venv/bin/strength-coach` directly.
| symptom | cause and fix |
|---|---|
| `no stored session on or before <date>` | the date predates the log, or nothing is imported. Run `strength-coach import`. |
| `already prescribed for <date>` | `run` is idempotent per date. Add `--force` to regenerate. |
| `NO_LOAD: ... no usable e1RM` | no rated set for that lift in the last 84 days. Train it, or widen `e1rm_window_days`. |
| `SPINAL_CAP ... exceeds cap` | the week already contains a hinge exposure; two hinge sessions cost 2+2 against a cap of 3. Move the day or accept the warning. |
| `PRG-EREC-001 ... missing symptom.flare` | expected: there is no symptom input yet. It becomes assessable in v0.1. |
| `PRG-DP-001 ... missing set.reps.<exercise>` | the scoped accessory has no comparable working set yet. Train it once; the range itself now comes from all day templates. |
| `no marks yet` | run `strength-coach review --session DATE` first. |
| `llm: off (NullLLM)` | no model configured; see §7. |
| `call failed: HTTP 401` | wrong key, or the key is in the environment but not the file. Check `tools/llm_check.py`. |

---

## 10. Limits you should know

- **Days A, B and C** are all prescribable. The erector ramp still needs a declared block
  start (`block --date`); until then `PRG-EREC-001` is `unknown` on every day.
- **No symptom input.** Back-symptom rules return `unknown` rather than assuming no flare.
- **No imported timestamps.** Live workouts store measured duration and the rubric scores it;
  imported sessions remain unmeasurable. Manual review duration is still optional.
- **VBT targets are not prescribed** (`DEC-VBT-01`): the calibration exists, the step from a
  velocity band to "do this set at X" is not specified, so prescriptions carry no velocity
  target and no calibration id.
- **The spinal cost is load-blind.** A light good-morning at RIR 3 counts the same as a heavy
  one. Known gap, recorded in the roadmap.
- **Loads are estimates.** e1RM uses Epley with the RIR folded in (`ASSUMPTION-03`); treat the
  number as a target, not a measurement.
- **Calibration is thin.** One remembered session so far; the rubric is not tuned to it.
- **One day at a time, and one input path.** The CLI has a rolling forecast (`programme`); the
  web programme view is still planned. There is no
  manual logging or alternative file formats. Those are scoped in
  [ROADMAP.md](ROADMAP.md) §4 (v0.2), including how missing readiness will be reported rather
  than assumed.

---

## 11. Privacy

This repository is public and contains no personal data.

- `data/` (exports, `coach.db`) is git-ignored.
- `private/` (evidence profile, baseline, your marks) is git-ignored.
- `config/llm.local.toml` and `.env` are git-ignored; keys are masked in every diagnostic.
- The code, schemas, rules and tests contain no athlete-specific values.

## 12. Using this for someone else

The app is local-first and one database per person. Nothing personal is committed, so a
second athlete runs exactly the same code against their own database:

1. **Choose their database path.** Every command takes `--db /path/to/their.db`; the default
   `data/coach.db` belongs to the first athlete. Never point two people at one file.
2. **Create their state file.** Copy [`config/athlete-state.example.yaml`](config/athlete-state.example.yaml)
   to `private/athlete-state.yaml` (git-ignored) and fill it in. Leave
   `block_start_date: null` until they declare week 1.
3. **Import their state:**
   ```bash
   strength-coach --db /path/to/their.db state --import private/athlete-state.yaml
   ```
4. **Import their training export** into `data/raw/`, or point the importer at it, then:
   ```bash
   strength-coach --db /path/to/their.db import
   strength-coach --db /path/to/their.db block --date YYYY-MM-DD
   strength-coach --db /path/to/their.db run --date YYYY-MM-DD --session-type squat
   strength-coach --db /path/to/their.db review --session YYYY-MM-DD
   strength-coach --db /path/to/their.db calibrate
   ```
5. **Add their exercise vocabulary in YAML**, not Python: `config/exercises/taxonomy.v1.yaml`.
   Unknown names are reported, never silently dropped.

Privacy rules that make this safe:

- `data/` and `private/` are git-ignored; a tracked-file test fails if anything personal is
  committed.
- LLM keys live in `config/llm.local.toml` (git-ignored) or the environment.
- Their export, state, marks and database never touch the first athlete's files.

The portability test suite runs the full loop on two independent databases with different
lifts, dates and days, and asserts neither database sees the other's artifacts.
