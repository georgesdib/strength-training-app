# User Guide

This guide is for someone using Evidence-Based Strength Coach for the first time. It prioritises the local web interface; the command-line interface (CLI) is available for automation and for actions not exposed in the UI.

The app is a local-first strength-coaching tool. It imports training and readiness logs, records athlete state and constraints, critiques completed sessions against explicit rules, and generates a prescription for a selected day. Python computes scores, loads, RIR targets, validation and other numbers. An optional language model can explain results or choose among bounded, precomputed options; it does not calculate training numbers or override safety rules.

> **Important:** this is a training decision-support tool, not medical advice, injury clearance, or a validated predictor of injury or performance. Check every prescription before using it.

## 1. Before you start

You need:

- Python 3.11 or later.
- A copy of the repository.
- Your training export at `data/raw/training_log.csv`.
- Your readiness export at `data/raw/readiness.csv`.
- A terminal for the initial installation. The browser UI can handle routine work after the app is running.

See [`data/README.md`](data/README.md) for the exact CSV schemas. Keep personal exports and derived personal data out of Git: the repository's `data/` and `private/` locations are intended to be git-ignored.

## 2. Install and launch

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Start the web interface:

```bash
./run-web.sh
```

The launcher normally opens a browser at `http://127.0.0.1:8000`. If you are running on a headless machine, or want to open the page from another device on your trusted home network, use:

```bash
./run-web.sh --no-open
```

Then open `http://<server-address>:8000` from a device that can reach the server.

**Network warning:** the web UI has no authentication and, by default, binds to `0.0.0.0`. Keep it behind a trusted home network. Do not port-forward it or expose it directly to the public internet. Do not put sensitive training exports in a public repository.

To stop a foreground server, use `Ctrl+C` in its terminal. The CLI can also start the UI:

```bash
.venv/bin/strength-coach web
```

If the command is not found, use the `.venv/bin/` path or activate the environment first:

```bash
source .venv/bin/activate
```

## 3. First-time setup

Follow these steps in order. Page names below refer to the web UI; equivalent CLI commands are shown where useful.

### Step 1 — Import your history

Open **Import** and upload the training and readiness CSV exports. Alternatively, run:

```bash
.venv/bin/strength-coach import
```

Read the import report rather than assuming every row was accepted. Check:

- How many new rows and sessions were added.
- How many rows overlapped with history already stored.
- How many rows were quarantined.
- The date range actually covered.
- Any issues or unknown exercise names.

Quarantined rows are retained and reported rather than silently discarded. A repeated cumulative export is overlap-matched against stored data, but a changed row may be treated as new. Importing does not, by itself, require a calibration run.

### Step 2 — Set up athlete state

Open **Athlete** and review the athlete's goal, constraints, exercise suitability, and estimated one-repetition maximums (e1RMs) or overrides. Set a block start date if the current block's week should drive the programme's undulating scheme.

Use the CLI when needed:

```bash
.venv/bin/strength-coach state
.venv/bin/strength-coach block --date YYYY-MM-DD
```

Do not remove a hard constraint just because a readiness score is high. Constraints and exercise-suitability ratings are separate from day-to-day readiness.

### Step 3 — Review a few recent sessions

Open **Review**. Review only sessions you can reasonably remember and enter marks for the rubric items. Leave an item blank if you cannot judge it. Set memory confidence honestly (`high`, `low`, or `unknown`).

The calibration report compares the engine's rubric scores with your marks. It is not an automatic tuning system: the report is evidence for a human decision, and it does not automatically change rubric weights or prescription rules.

You can catch up in the CLI:

```bash
.venv/bin/strength-coach review --pending
```

### Step 4 — Log today's readiness

Open **Workflow → Readiness** and enter the subjective measures available to you, such as sleep, energy, mood, soreness and stress. Device-derived HRV/RHR values and a wearable score are optional. Enter only data you have; do not invent values to complete the form.

The CLI equivalent is:

```bash
.venv/bin/strength-coach readiness set \
  --date YYYY-MM-DD \
  --sleep 4 --energy 4 --mood 4 --soreness 4 --stress 4
```

The example numbers are illustrative, not targets. Follow the scale labels in the UI. A score requires a sufficient subset of the core inputs. If readiness is incomplete, the app requires an explicit acknowledgement that no score will be applied before it proceeds.

## 4. Your normal workout workflow

Use **Workflow** for the day-to-day loop.

### Before training — preview

1. Record readiness for the date you are training.
2. Open **Workflow → Preview**.
3. Choose the session type or use the automatic rolling sequence.
4. Read the prescription and its warnings before accepting it.
5. Check exercise choices, loads, rep ranges, RIR targets, rest guidance, and rule/provenance notes.
6. Resolve any unsuitable exercise or hard constraint before training. Do not treat a warning as permission to ignore pain or other symptoms.

The four canonical session types are:

- **Squat**
- **Hinge**
- **Bench + squat**
- **Bench + hinge**

The programme rolls through these types; the Programme page is a forecast, not a promise that a future session will remain unchanged. The day's prescription is rebuilt from the current state and inputs.

### During training — live workout

Start the workout from the Workflow page and record completed work in the live workout interface. Use the prescribed rep range and effort target as guidance, while applying normal judgement and stopping if the session becomes unsafe or symptoms materially worsen. Each planned exercise has a **History** toggle showing the last five completed sessions for that lift (with **Show more**); it is read-only and does not include the set you are currently logging.

Power work is quality-limited: stop when movement quality or output declines rather than chasing fatigue. A prescribed RIR target is an estimate of repetitions in reserve, not a requirement to grind through a bad rep.

If you use an external workout tracker instead, import its updated export afterwards.

### After training — finish and review

1. End the live workout, or import the updated external log.
2. Open **Review workout** or the **Review** page.
3. Compare the recorded session with the rubric and enter marks you can justify.
4. Optionally record session RPE (1–10) and duration.
5. Leave uncertain rubric items blank and use `high` memory confidence only when appropriate.

CLI example:

```bash
.venv/bin/strength-coach review --session YYYY-MM-DD
```

Marks and run history are append-only. A later correction adds a new record; it does not erase the earlier record.

## 5. Weekly maintenance

Once a week, or after a meaningful change:

- Review recent sessions you remember.
- Run the rubric calibration report after entering marks.
- Inspect the **Weekly volume** panel and any MRV/volume warnings.
- Check athlete state, exercise suitability, constraints and block dates if they have changed.
- Review symptoms and injury-signal information where relevant.
- Treat readiness calibration and HRV/RHR baseline-shadow reports as diagnostic reports, not as automatic changes to the programme.

Useful CLI commands:

```bash
.venv/bin/strength-coach calibrate
.venv/bin/strength-coach readiness calibrate
.venv/bin/strength-coach readiness shadow
.venv/bin/strength-coach programme --weeks 4 --remaining
```

The reports do not automatically retune readiness weights, calibration thresholds, or training rules.

## 6. Understanding what you see

### Readiness

Readiness is a date-specific adjustment input. Depending on the score and configured rules, it can reduce load, increase the RIR allowance, and remove an accessory set. Main-lift set reduction is a separate opt-in setting. Readiness does not override a hard constraint or injury ceiling. The score's weights and cut-points are transparent design choices, not validated individual thresholds.

### Loads and e1RM

An e1RM is an estimate, not a measured current maximum. Loads are calculated by Python from the selected e1RM or a permitted override, the prescription formula and real loading increments. Loads are rounded down to valid increments. Variant comparability and data availability affect which estimate can be used.

### Volume and deloads

The volume ledger compares recent working sets with configurable pattern-level MEV/MAV/MRV landmarks. These are broad guardrails, not measured personal biological limits. The MRV cap trims non-essential work first; it does not silently remove essential work to force a number under the cap. Deload policy is separate from the volume ledger.

### Injury signal and constraints

The symptom/injury signal summarises recorded symptoms and loading history. It is not a diagnosis and does not certify recovery. A `review` status does not automatically make an exercise suitable or remove a constraint. Missing symptom data means unknown, not symptom-free.

### LLM explanations

The model is optional. Without it, deterministic prescriptions and reports still work. The model can narrate results or select among permitted alternatives; it cannot calculate or change loads, RIR or velocity targets, and cannot veto a rule. A narrative should never be treated as more authoritative than the underlying prescription and its cited rules.

## 7. Troubleshooting and common questions

**The app says readiness is incomplete.** Enter the subjective fields you actually know, or use the UI's explicit acknowledgement for partial/unknown readiness if offered. Do not make up values.

**Why did import quarantine a row?** Common causes include a missing date or an exercise name the taxonomy cannot resolve. Inspect the import report and the schema in [`data/README.md`](data/README.md).

**Should I calibrate immediately after importing?** Not unless you have reviewed sessions and supplied marks. Rubric calibration compares the engine with human marks; importing alone does not create those labels.

**Why didn't a calibration change the programme?** Calibration reports are diagnostic. They do not automatically change weights or prescription policy.

**Why is a future Programme entry different from today's workout?** Programme is a forecast. The actual prescription is rebuilt for the day using the current athlete state, readiness, constraints and other modifiers.

**Can the app diagnose an injury or predict injury?** No. It records context and applies conservative training constraints; it is not a medical system or validated injury predictor.

**Can I expose the UI outside my home?** No—not in its current unauthenticated form. Keep it on a trusted network.

### First diagnostic steps

1. Note the exact symptom, the page or command, and the full error text.
2. Check the **Logs** page in the UI, or the terminal that started `./run-web.sh`; the in-memory log resets when the server restarts.
3. Confirm which database is in use. The default is `data/coach.db`; `./run-web.sh --db PATH` selects another one.
4. Reproduce once after a reload. Do not delete or rewrite the database to "fix" a display error.

### Symptom guide

**The page will not load.** Confirm the server is running with `./run-web.sh --no-open`, then open
`http://127.0.0.1:8000/`. If the port is already in use, stop the other process or start with
`./run-web.sh --port 8001`. A terminal traceback and the Logs page are the useful diagnostics.

**A panel says "internal server error".** The server logs the underlying exception. Open
**Logs**, copy the timestamp and message, and check the terminal for the traceback. Reload once;
if it persists, report the page, action, timestamp and log line. Do not assume the database is
corrupt.

**A form rejects a value.** Read the message next to the field. The API returns the same
message and, where supported, a field-specific error. Check the input against the documented
range or canonical option list; do not bypass validation by editing the database.

**A prescription is empty or has unknown loads.** First complete readiness or use the
Workflow's explicit partial/unknown acknowledgement. Then inspect the prescription warnings:
unknown loads usually mean there is no usable e1RM/history, while a blocked or reduced plan can
come from a hard constraint, injury ceiling or other safety rule. The deterministic warnings
are authoritative; do not invent a load to fill the gap.

**An optional LLM feature does nothing.** Check **Settings → Language model** and run
`.venv/bin/python tools/llm_check.py`; add `--call` to test the configured endpoint. With no
provider configured, `NullLLM` is active: deterministic training works, but narrative and
LLM-assisted selection/proposal are unavailable. A configured-but-failing provider should show
an error in the UI and the server log; the deterministic path remains usable.

**Displayed data looks stale.** Reload the page, confirm the date selector, and check that a
save reported success. Programme entries are forecasts rebuilt for their dates, not committed
workouts. If a saved record is missing, use **Logs** and the database path before considering
any data repair.

When escalating, include the app version (`strength-coach --version`), the page or command,
the exact error, the relevant Logs lines, and whether a non-default database was used. Remove
personal training values from screenshots or pasted logs before sharing.

## 8. Further reading

- [How workout generation works](docs/WORKOUT-GENERATION.md) — plain-English explanation of the prescription pipeline.
- [Methodology](docs/METHODOLOGY.md) — canonical decision flow and non-negotiable boundaries.
- [Web UI](docs/WEB-UI.md) — UI behaviour, pages and deployment details.
- [Session templates](docs/SESSION-TEMPLATES.md) — template configuration and validation.
- [Readiness score](docs/READINESS-SCORE.md) — score inputs, assumptions and limitations.
- [Injury signal](docs/INJURY-SIGNAL.md) — symptom signal design and caveats.
- [Volume management](docs/VOLUME-MANAGEMENT.md) — volume landmarks, MRV cap and limitations.
- [Volume budget guide](docs/VOLUME-BUDGET.md) — how to use the consolidated Volume budget settings panel.
- [Data schema](data/README.md) — import file format.
- [Privacy](docs/PRIVACY.md) — handling private data.

## CLI reference

The web UI is the recommended route for routine use. The CLI remains useful for automation and for operations not exposed in the UI. Run:

```bash
.venv/bin/strength-coach --help
.venv/bin/strength-coach <command> --help
```

Use the command's own help as the authority for exact options, because options can change as the app evolves.


## Related

- **Decisions:** [DECISIONS.md](docs/DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](docs/OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](ROADMAP.md)
