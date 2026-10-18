# USER GUIDE

How to actually use this tool. For the design record see [docs/](docs/), and for where the
project is going see [ROADMAP.md](ROADMAP.md).

---

## 1. What it is, in one paragraph

It reads your training export, cleans it under a documented set of rules, reconstructs
sessions, judges the most recent one against a fixed constitution, and prescribes the next
session — Day A, B or C. **Python computes every number; the LLM only explains them.** If no model is
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

.venv/bin/python -m pytest          # 316 tests, including integration on real data
```

After install you can call `strength-coach ...` instead of
`.venv/bin/python -m strength_coach.cli ...`; both are identical.

---

## 3. First run

```bash
strength-coach import
```

This reads the two CSVs into `data/coach.db` (git-ignored). It prints how many rows were
inserted, how many sessions were reconstructed, and how many rows were quarantined. Importing
the same file twice writes nothing the second time — identity is the source line, not the
content.

A quarantined row is **not** deleted: it is a row with no date or an exercise the taxonomy
cannot resolve. It stays visible and counted, because silently dropping rows is how real
violations disappear.

---

## 4. The three routines

### 4.1 `run` — critique the last session, prescribe a date

```bash
strength-coach run --date 2026-10-20
```

It critiques the most recent stored session on or before that date, prescribes Day B for it,
stores both inside a run trace, and prints the prescription with the rule or stored set that
justifies every number.

Sample output (numbers are illustrative):

```
prescription 2026-10-20  (day B, full)
  exercise                 sets    reps     load  rir  refs
  ---------------------------------------------------------
  trap_bar_deadlift           4     3-5      158.5    2  PRG-RIR-001, set:2026-10-05/7821
  bench_press_narrow          4     3-5      106.5    2  PRG-RIR-001, set:2026-10-05/7835
  lateral_raise               3   10-12       25.0    2  PRG-DP-001, set:2025-11-10/6565
  split_squat                 3    8-10       67.5    2  PRG-DP-001, set:2026-06-05/7359
  note: bench_main: chose bench_press_narrow from [...]
  note: PRG-EREC-001 not assessable: missing symptom.flare, block.week_index

critique 2026-10-15: composite 0.88
  RIR_ADHERENCE             0.75   3/4 rated sets inside the effort window
  WEEKLY_SPINAL_COST        1.00   weighted spinal cost 0 against cap 3
  ESSENTIAL_WORK             n/a   no prescription template for day 'unknown'
  ...
```

Useful flags:

| flag | effect |
|---|---|
| `--day A\|B\|C` | which day to prescribe (default B) |
| `--llm on` | ask the configured model for a narrative (see §7) |
| `--force` | regenerate even though that date was already prescribed |
| `--db PATH` | use a different database |

Re-running the same date writes nothing unless you pass `--force`. Two runs produce two
append-only critique rows, by design: history is not rewritten.

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

Marks are append-only: marking a session again adds a correction; the latest mark per
item wins, older ones stay in the table.

You can also supply marks from a file instead of typing:

```bash
strength-coach review --session 2026-10-15 --scores private/eval/labelled.yaml
```

### 4.3 `calibrate` — the running picture

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

This is the §11 athlete state: goals, constraints and per-exercise suitability. It exists so
a hard constraint can veto a prescription deterministically, rather than living in a prompt.

- **constraint** — `hard_exclude` vetoes the exercise; `caution` and `monitor` are recorded
  but do not block. A resolved injury is `monitor`, not `hard_exclude`.
- **suitability** — `can_do: false` is a hard block; `will_do: false` is a preference the
  engine reports as a warning ("a substitution is needed"), never treats as a safety veto.
- The tables are append-only: re-running the import with `--force` adds a new version, and
  `state` always shows the latest.

If no state is recorded, a prescription is still produced but says so: *"athlete state not
recorded: constraints were not evaluated"*. Silence is not permission.

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
strength-coach e1rm set --exercise ssb_squat --kg 160 --from 2026-11-01 \
    --reason "tested single"
strength-coach e1rm set --exercise ssb_squat --kg 150 --until 2026-12-01   # temporary
strength-coach e1rm list
```

Use an override when you know a value the formula cannot see: a tested single, a
post-layoff starting point, or an estimate that disagrees with reality. From `--from` (or
today) until `--until` (or forever), the override outranks the computed e1RM.

In the prescription it shows up as a normal load, with:

- a citation `e1rm_override:<id>` in its `refs` column, and
- a note: *"using a manual e1RM override (160 kg)"*.

Worth knowing:

- **Append-only.** A correction is another `e1rm set`; the latest applicable row wins and
  the older one stays in history.
- **Temporary is first-class.** `--until` expires it; after that the computed estimate
  returns on its own.
- **It only changes the derived load.** History, scores and verdicts are untouched.
- **Bulk entry** works through the state file: add an `e1rm_overrides:` list and run
  `strength-coach state --import private/athlete-state.yaml`.

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
  `lighter` (RIR and load are re-solved together).

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
strength-coach test --exercise ssb_squat --kg 160 --reps 1 --max
strength-coach test --exercise ssb_squat --kg 140 --reps 3 --e1rm 165 --yes
```

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

---

## 5. Reading the output

### The prescription

| column | meaning |
|---|---|
| exercise | canonical id from the taxonomy, not the raw log name |
| sets | prescribed working sets |
| reps | the rep range; add load only at the top of it |
| load | solved from your recent e1RM, **rounded down** to your increment |
| rir | target reps in reserve |
| refs | the rule id **and** the stored set that justify the load |

Loads come from the best usable e1RM in the last 84 days, inverted through the same
Epley+RIR formula that produced it, then rounded down to 0.5 kg (your microplates). Rounding
up would push the set above the target RIR, so it never happens.

If a load is `-` and the output says `NO_LOAD`, there was no usable e1RM in the window. The
prescription is then **not executable**, and it says so instead of inventing a number.

`CONSTRAINT_VETO:<exercise>` means a stored hard constraint blocks that exercise; the
prescription is not executable until the constraint or the template changes. A warning that
an exercise "you will not do" appears is a **preference**, not a veto — it asks for a
substitution rather than blocking the session.

### The critique

Six items are measured, two are not:

| item | measures |
|---|---|
| `RIR_ADHERENCE` | share of rated primary-compound sets inside the allowed window (RIR 1–4) |
| `PROGRESSION_ADHERENCE` | accessories added load only after topping the rep range |
| `WEEKLY_SPINAL_COST` | the week's weighted spinal load against a cap of 3 |
| `ESSENTIAL_WORK` | the day's essential lifts were present |
| `REDUNDANCY` | no hinge + erector stacking, no two hinge lifts |
| `ROTATION` | selection stable for self-directed sessions; expected rotation for app-assigned |
| `SESSION_DURATION` | **not measurable** — the export has no timestamps |
| `VELOCITY_LOSS` | **not measurable** — one mean velocity per set |

`composite` is the weighted mean over the items that were measurable, re-normalised — a
missing metric never drags the score to zero.

### 5.1 Readiness — how it is derived

Readiness can only *reduce* a prescribed load, so its derivation is written down in full in
[READINESS.md](docs/READINESS.md). In short:

- the export is read as text and then as numbers; `0` becomes missing in the fields where a
  physical zero is impossible (bodyweight, HRV, RHR, fat %, the three readiness scores);
- duplicate rows on one date are merged: **most complete wins, ties go to the latest**, and
  the merge note records which candidate won and why;
- `MOD-FAT-001` reads only the fields listed in `config/readiness.v1.yaml` (sleep and energy
  by default) and cuts loads by 5% when one of them is at or below 2;
- missing readiness is **not** "fine": the modifier does not apply, and the prescription says
  so.

To change which fields matter, the threshold, or the merge tie-break, edit
`config/readiness.v1.yaml`. Only implemented values are accepted — anything else raises
rather than silently doing nothing. Manual and partial readiness entry is planned for v0.2
(§4.1 of [ROADMAP.md](ROADMAP.md)).

---

## 6. Configuration

Everything that changes a number lives in config, not code.

| file | what it controls |
|---|---|
| `config/thresholds.v1.yaml` | load increment (0.5 kg), rounding, e1RM window (84 days), fatigue multiplier (0.95) |
| `config/templates/days.v1.yaml` | which lifts a day contains, sets, rep ranges, rest |
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

Today the model **only explains**. Letting it *propose* changes to the session — a substitute
accessory, a different bench variant, more or fewer sets — is planned for v0.1
([ROADMAP.md](ROADMAP.md) §3.4). Even then the numbers will still come from Python: the model
would propose a structured intent, the policy engine would accept or veto it, and the
prescription would record `approved_by = llm+policy`.

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

| symptom | cause and fix |
|---|---|
| `no stored session on or before <date>` | the date predates the log, or nothing is imported. Run `strength-coach import`. |
| `already prescribed for <date>` | `run` is idempotent per date. Add `--force` to regenerate. |
| `NO_LOAD: ... no usable e1RM` | no rated set for that lift in the last 84 days. Train it, or widen `e1rm_window_days`. |
| `SPINAL_CAP ... exceeds cap` | the week already contains a hinge exposure; two hinge sessions cost 2+2 against a cap of 3. Move the day or accept the warning. |
| `PRG-EREC-001 ... missing symptom.flare` | expected: there is no symptom input yet. It becomes assessable in v0.1. |
| `PRG-DP-001 ... missing rep_range.back_extension` | expected on Day B: the rule also covers Day A/C accessory work. Harmless but noisy; disappears with A/C templates. |
| `no marks yet` | run `strength-coach review --session DATE` first. |
| `llm: off (NullLLM)` | no model configured; see §7. |
| `call failed: HTTP 401` | wrong key, or the key is in the environment but not the file. Check `tools/llm_check.py`. |

---

## 10. Limits you should know

- **Days A, B and C** are all prescribable. The erector ramp still needs a declared block
  start (`block --date`); until then `PRG-EREC-001` is `unknown` on every day.
- **No symptom input.** Back-symptom rules return `unknown` rather than assuming no flare.
- **No timestamps.** Session duration is unmeasurable and is stored as such.
- **VBT targets are not prescribed** (`DEC-VBT-01`): the calibration exists, the step from a
  velocity band to "do this set at X" is not specified, so prescriptions carry no velocity
  target and no calibration id.
- **The spinal cost is load-blind.** A light good-morning at RIR 3 counts the same as a heavy
  one. Known gap, recorded in the roadmap.
- **Loads are estimates.** e1RM uses Epley with the RIR folded in (`ASSUMPTION-03`); treat the
  number as a target, not a measurement.
- **Calibration is thin.** One remembered session so far; the rubric is not tuned to it.
- **One day at a time, and one input path.** There is no whole-programme view yet, and no
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
