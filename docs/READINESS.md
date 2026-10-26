# READINESS — how the daily signal is derived

Readiness is the one input that can reduce a prescribed load, so its derivation is written down
here in full. Two parts are **rules** (fixed in code, because getting them wrong corrupts
history) and two are **preferences** (config, because a user may reasonably want them different).

```
readiness.csv
   │  every cell kept as text (io_utils)          ← no type inference, no silent NaN
   ▼
coerce to numbers, map null tokens to missing
   │
   ▼
zero → missing for fields where 0 is impossible   ← per-field sentinel policy
   │
   ▼
merge duplicate rows per date                     ← most complete; ties to the latest
   │
   ▼
readiness_day  (one row per date, append-aware)
   │
   ▼
MOD-FAT-001 reads the configured fields           ← sleep, energy by default
   │
   ▼
if any configured field ≤ threshold → load × 0.95, cited with readiness:<date>
```

---

## 1. Input

Today readiness arrives only from the exported `readiness.csv`: one row per recording, and
several rows can share a date. Every cell is read as text and stored verbatim in `raw_row`
before anything is interpreted.

Manual entry (daily, occasional, or partial) feeds the same merge. Quick presets write the same ordinary fields with `source=preset`; they do not bypass the gate or the minimum-data rule. Context flags (`travel`, `timezone_change`, `illness`, `alcohol`, `poor_sleep_environment`, `high_work_stress`) are stored separately and are displayed, not scored by default. A manual value wins **per
field**; the imported row fills the fields it does not provide (`DEC-READINESS-03`). The old
`squat_readiness`/`bench_readiness`/`deadlift_readiness` columns are retained only as
calibration labels; they are not accepted as manual input (`DEC-READINESS-06`). Manual
readings are appended to `readiness_entry`, never written into `readiness_day`, so a
correction preserves the earlier value.

The guided workflow unlocks the preview when the score is **ready** (three core fields plus
sleep or energy). With a partial or unknown score, the athlete must explicitly acknowledge
that no readiness score will be applied; missing fields stay absent, and no score-based load
modifier is used. The same acknowledgement is required to start a workout without a score.

## 2. Missing values: the sentinel policy

The export uses `0` for "not measured" in several columns, and a physical zero is impossible
there. Those fields become missing, never zero:

| field | why 0 is missing |
|---|---|
| `Weight` | 0 kg bodyweight is impossible |
| `HRV`, `RHR` | 0 ms / 0 bpm are incompatible with life |
| `Fat_Percent` | 0% body fat is impossible |
| `Squat_Readiness`, `Bench_Readiness`, `Deadlift_Readiness` | the 1-5 scale has no zero bucket |

The 1–5 fields (`Sleep`, `Energy`, `Mood`, `Soreness`, `Stress`, `Nutrition`, `Hydration`)
have **no** sentinel: a zero would be an invalid entry, not a missing one, and is treated as
unparseable rather than silently converted.

This is `numeric.ZERO_IS_MISSING` and `numeric.ZERO_IS_VALID`; the split exists because the same
`0` means different things in different columns (AGENTS.md §5).

## 3. Duplicate rows on one date

Several rows for a date usually **conflict** rather than repeat. The documented rule
(`DEC-READINESS-01`, OPEN-QUESTIONS Q6):

1. count how many fields each row actually measured (after sentinel handling);
2. keep the **most complete** row;
3. on a tie, keep the **later** row in the file — the only ordering the export provides.

`readiness_day.merge_note` records how many candidates there were, which one won, and why. The
assumption that completeness equals authority is `ASSUMPTION-04`; it is a choice, not a
measurement.

## 4. Storage

One row per date in `readiness_day`, with the 1–5 fields, the device fields (HRV, RHR,
bodyweight, body fat, wearable score), and a nullable `composite`. The legacy
`grip_strength_kg` column remains for historical rows but is no longer accepted or scored;
grip is tracked with `measure --metric grip_strength_kg` (`DEC-GRIP-01`).

**`readiness_day.composite` is deliberately null.** The computed score is a separate
`readiness_score` assessment (`docs/READINESS-SCORE.md`), so the imported row stays a
measurement record. Its HRV/RHR baseline and optional wearable blend are explicit and shown
with the result; they are not written back into `readiness_day.composite`.

Manual readings live in `readiness_entry`: one row per field, append-only, with source
`manual`, a timestamp and an optional note. Re-logging a date appends; the latest entry per
(date, field) wins. `queries.readiness_day` overlays those entries on the imported row and
returns a `sources` map and a `manual_merge_note` with both values, so a partial manual day
keeps the imported fields around it and the override is auditable.

## 5. What actually moves a load

The implemented score reads the five core subjective fields (sleep, energy, mood, stress,
soreness) and needs at least three of them plus sleep or energy. HRV and RHR enter only with
a 28-day baseline (at least 7 readings) at half weight; an optional wearable score is a 10%
blend. It produces a global score and per-category scores; overrides are 0.00–1.00. An explicit
override still applies when no numeric score can be formed (the status stays `insufficient`),
and a `category:` scope that names no category is rejected rather than silently ignored. The old
`MOD-FAT-001` configured-field rule remains as a **floor**:

```yaml
modifier:
  fields: [sleep, energy]
  at_or_below: 2
```

Higher is better on every readiness scale, so "at or below" is the risk side. `Stress = 5`
means *no stress*; a naive `stress >= 4` reading would be inverted.

When a field crosses the threshold the prescribed loads are multiplied by the configured
fatigue factor (0.95), rounded down, and every touched item cites `MOD-FAT-001` and
`readiness:<date>`.

There is also a conservative **set-reduction valve**: when the global score is below
`set_reduction.score_below`, or the sleep/energy floor fires, each item loses
`set_reduction.sets` (minimum one set). `include_essential` is **false** by default after the 2026-10-23 audit; accessory
sets lose one set, while main-lift set reduction is an explicit opt-in in the volume-valve settings. The
warning names the affected sets, and the prescription notes record the setting. This is fatigue
management, not a proven strength optimisation.

A separate **readiness feedback** report compares a readiness-reduced session with the prior one. It reads completed workout snapshots whose frozen plan cites `MOD-FAT-001`, so the UI start-workout path is included, and compares planned versus actual sets. CLI-stored prescription modifiers fill in when no workout snapshot exists. It is association-only and never tunes the weights or valve.

**Missing is not "fine".** A current/future workout is refused until readiness is "ready";
missing or insufficient data is reported as such. Historic dates remain reproducible. The old
sleep/energy floor still applies when a score cannot be formed.

## 6. Changing it

Everything a user might reasonably want different is in `config/readiness.v1.yaml`:

| key | effect |
|---|---|
| `modifier.fields` | which readiness fields can downgrade a session |
| `set_reduction` | whether poor readiness removes sets, at what score, how many, and whether essentials are included |
| `modifier.at_or_below` | the threshold on those fields |
| `merge.strategy` / `merge.tie_break` | which duplicate row wins; only the implemented values are accepted |
| `score.baseline_days` / `score.baseline_min_readings` | HRV/RHR baseline window and minimum |
| `score.hrv_weight` / `score.rhr_weight` | device-field weights (default 0.5) |
| `score.wearable_weight` | optional wearable blend (default 0.10) |
| `composite.enabled` | reserved; stays off. No implementation consumes it; a dynamic composite needs weight/role/baseline metadata, not just metric rows |

An unimplemented value raises rather than being ignored — a config that silently did nothing
would leave the athlete believing they had changed the behaviour.

Changing a modifier field or threshold **changes a prescribed load**, so it is a decision, not
a preference of convenience: record it in `docs/DECISIONS.md` when you do.

## 7. What is deliberately not done

- The global/category score is implemented in [`READINESS-SCORE.md`](READINESS-SCORE.md);
  `readiness_day.composite` itself stays null. The old sleep/energy trigger remains a floor.
- Grip strength stays a capacity trend, not a daily score input.
- The wearable score is not used to override constraints or the injury ceiling.
- No inference of readiness from training data, sleep reports or anything else: absent means
  absent.

## Related

- **UI surface:** [UI-MAP.md](UI-MAP.md)
- **Evidence:** [LIFT-READINESS.md](LIFT-READINESS.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
