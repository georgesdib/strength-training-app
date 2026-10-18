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

Manual entry (daily, occasional, or partial) is planned for v0.2 §4.1. When it lands it will
feed the same merge, with manual values winning per field and the import filling gaps
(`DEC-READINESS-03`).

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

One row per date in `readiness_day`, with the 1–5 fields, the device fields, and a nullable
`composite`.

**The composite is deliberately null.** A 0–1 score would need every metric's scale and
direction declared first (`metric_definition`), and inventing one would make a guess
indistinguishable from a measurement. `config/readiness.v1.yaml` has the switch, off.

## 5. What actually moves a load

`MOD-FAT-001` reads **only the configured fields** and compares them to a threshold:

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

**Missing is not "fine".** If no readiness exists for the date, the modifier does not apply and
the prescription says so: *"readiness unknown"*. A partially filled day applies only the fields
it has.

## 6. Changing it

Everything a user might reasonably want different is in `config/readiness.v1.yaml`:

| key | effect |
|---|---|
| `modifier.fields` | which readiness fields can downgrade a session |
| `modifier.at_or_below` | the threshold on those fields |
| `merge.strategy` / `merge.tie_break` | which duplicate row wins; only the implemented values are accepted |
| `composite.enabled` | reserved; stays off until metrics are declared |

An unimplemented value raises rather than being ignored — a config that silently did nothing
would leave the athlete believing they had changed the behaviour.

Changing a modifier field or threshold **changes a prescribed load**, so it is a decision, not
a preference of convenience: record it in `docs/DECISIONS.md` when you do.

## 7. What is deliberately not done

- No composite readiness score yet (`composite` stays null).
- No normalisation of HRV, RHR, Bevel or grip strength until their directions are declared in
  `metric_definition`.
- No inference of readiness from training data, sleep reports or anything else: absent means
  absent.
