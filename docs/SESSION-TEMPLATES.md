# Session templates — field guide

The session templates are the scheduling source of truth:
`config/templates/session-types.v1.yaml`. The deterministic engine builds each session from
one template. **Exercise `day_roles` are derived from this file**, not stored separately.

The local UI exposes the YAML in **Exercises → Session templates → Edit templates**. Saving
validates all four session types and every exercise id before writing. A rejected edit leaves
the current file untouched.

## Top level

```yaml
schema_version: "1.0.0"

session_types:
  squat: { ... }
  hinge: { ... }
  bench_squat: { ... }
  bench_hinge: { ... }
```

- **`schema_version`** — must be `1.0.0`; a mismatch fails loudly.
- **`session_types`** — exactly the four canonical types. No A/B/C day labels.
- Each type has a **`label`** and a **`prescription`** block.

## Prescription block

```yaml
squat:
  label: "Squat emphasis"
  prescription:
    time_cap_s: 4800
    slots:
      - id: main_squat
        exercise: ssb_squat
        sets: 5
        reps: {low: 3, high: 5}
        rir: {low: 2, high: 3}
        rest_s: 180
        essential: true
        load_source: e1rm
```

- **`time_cap_s`** — target session budget in seconds; used by the time estimate.
- **`slots`** — ordered list of work items. Order is the session order.

## Slot fields

| field | meaning |
|---|---|
| `id` | stable slot identity within the session type; unique |
| `exercise` | one canonical exercise id |
| `exercise_variants` | alternative exercise ids; exactly one is selected by the selector/readiness rules. Use this **or** `exercise` |
| `sets` | working sets |
| `reps.low`, `reps.high` | prescribed rep range |
| `rir.low`, `rir.high` | effort window; required for non-power work |
| `rest_s` | optional rest in seconds |
| `essential` | essential work is not removed by budget trimming or the minimum-session fallback |
| `load_source` | `e1rm`, `double_progression` or `bodyweight`; how the load is solved |
| `power` | optional; power work is quality-limited |
| `quality_stop` | required when `power: true`; replaces an RIR target |
| `flare` | optional `auto`, `hold_effort` or `erector_dose`; flare policy |

Power slots must **not** carry `rir`; use `power: true` and `quality_stop`. Non-power slots
must not carry `quality_stop`.

## Variants and day roles

`exercise_variants` lists alternatives for one logical slot. The first variant is the
default for display/grouping. The selector may substitute within comparability rules.

The catalogue derives `day_roles` by scanning every template slot and variant:

- an exercise appears in a session type if it is a slot `exercise` or in
  `exercise_variants`;
- the result is read-only in exercise details;
- it is **not** stored in taxonomy or overrides;
- changing a template changes the derived roles immediately after the cache is cleared.

## What changing a template changes

- session contents, order, sets/reps/RIR/rest;
- which exercises are scheduled and therefore their derived day roles;
- the time estimate and, through slot choices, the prescribed load;
- the programme summary digest.

It does **not** change exercise identity, history, volume targets or the constitution.

## Save, validation and recovery

- Saving validates the whole document first: schema, all four session types, slot
  parsing, RIR/power rules, load source, unique ids, at least one essential slot per session,
  positive time cap, and exactly one of `exercise` / `exercise_variants` per slot.
- Unknown exercise ids are rejected by the server.
- A rejected save leaves the current file untouched; the UI shows the validation message.
- A successful save writes atomically and keeps the last **20** timestamped backups in the
  git-ignored `data/template-backups/` directory.
- **Restore last backup** backs up the current file first, validates the backup, then restores it.
- After a save, the template cache is cleared; new prescriptions use the new template. Existing
  prescriptions are not rewritten.

## Tests, goldens and the programme summary

The UI edits runtime config; it never edits test code.

- `tests/test_golden_prescription.py` pins the shipped programme. A template change that alters
  a prescription will fail that test until the golden fixture is deliberately updated.
- Synthetic-template tests exercise the engine independently of the shipped programme.
- Programme-invariant tests assert decisions such as push/row coverage and main-lift uniqueness.
- An intentional template change therefore needs a reviewed fixture update; an unintended one
  should be restored from backup.

`docs/STRENGTH-PROGRAM-REVIEW.md` is generated from the templates. After a template change it is
stale until **Refresh programme summary** rewrites its generated block. That is documentation,
not test code.

## Safety rules

- Keep the four session types and their core slots; removing essential work or a main lift is a
  programme decision, not a cosmetic edit.
- Do not invent exercise ids; validation rejects unknown ids.
- Do not use legacy A/B/C day names.
- Preserve the power/quality-stop and flare rules.
- A template edit is a config change. It should be reviewed like a programme change, not applied
  casually mid-block.

## Related

- **UI surface:** [UI-MAP.md](UI-MAP.md)
- **Exercise variants:** [EXERCISE-VARIANTS.md](EXERCISE-VARIANTS.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
- [Volume modulation](VOLUME-MODULATION-PLAN.md) — how prescribed sets feed the volume budget.
- [Methodology](METHODOLOGY.md) — change-control rules.
