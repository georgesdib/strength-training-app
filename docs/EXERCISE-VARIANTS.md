# Exercise variants — configuration

Variants are **configuration**, not code. A variant slot is a template slot with more than
one allowed canonical exercise; the engine picks one, and the shadow selector can rank them.

## 0. Web Exercises tab

The web UI's **Exercises** tab shows every entity and writes edits/additions to
[`config/exercises/overrides.v1.yaml`](../config/exercises/overrides.v1.yaml). The checked-in
taxonomy stays intact, so comments and the base audit trail survive. IDs are immutable.

## 1. Add the canonical exercise

[`config/exercises/taxonomy.v1.yaml`](../config/exercises/taxonomy.v1.yaml):

```yaml
  front_squat:
    display: "Front Squat"
    log_names: ["Front Squat"]
    pattern: squat
    main_lift: false
    primary_compound: true          # the RIR window applies
    programme_slot_of: ssb_squat    # informational: used where SSB was programmed
    vbt_family: squat
    loadable: true
    time_based: false
```

| property | why it matters |
|---|---|
| `log_names` | exact names resolved at import; add every spelling |
| `pattern` | readiness category, selection family, injury links |
| `primary_compound` | applies `PRG-RIR-001` |
| `bodyweight_type` | `load 0` is a real bodyweight load |
| `loadable` | external load is meaningful |
| `vbt_family` | VBT calibration family |
| `history_equivalent_of` | **only** for the same movement (e.g. back extension/hyperextension); it merges history and load |

Do not use `history_equivalent_of` for a different variant with different loads
(pull-up vs lat pulldown).

## 2. Add it to a slot

[`config/templates/session-types.v1.yaml`](../config/templates/session-types.v1.yaml):

```yaml
        - id: squat_main
          exercise_variants: [ssb_squat, front_squat]
          sets: 4
          reps: {low: 3, high: 5}
          rir: {low: 2, high: 3}
          rest_s: 180
          essential: true
          load_source: e1rm
```

- `exercise` **or** `exercise_variants`, not both.
- every id must exist in the taxonomy;
- all variants share the slot’s sets/reps/RIR/rest;
- `essential: true` treats whichever is selected as essential work.

The engine still chooses the most recently trained variant. The shadow selection panel ranks
all configured variants but does not change the prescription.

## 3. History caveat

Taxonomy changes apply to **future imports**. Existing `clean_set` rows keep the canonical id
they had at import. If a raw name was previously stored as `pattern:squat`, adding
`front_squat` will not relabel that history.

Options:

- use the existing canonical id instead of introducing a duplicate;
- `history_equivalent_of` only if it is genuinely the same movement;
- a deliberate re-resolution migration (not built);
- rebuild the database from exports in a fresh setup (loses marks/state).

## 4. Canonicalisation and history rewrite (2026-10-20)

All synthetic raw names in the current log were canonicalised: **114 new entities** were
generated from the log's `Main_Muscle`, `Mechanics`, `Force` and name semantics, and
`clean_set` identities were rewritten by migration `0014` (audit table `exercise_remap_log`,
**3,607** rows). The raw rows are untouched.

**Correction:** `Close Grip Pulldown` was initially reused as `lat_pulldown`; it is a grip
variant with different leverage/load, so migration `0015` split it into
`close_grip_pulldown` (**15** rows) and added it to the pull-slot candidates. The same principle
applies to `Bench Press (medium grip)`, which remains its own entity.

**Exceptions preserved:**

- `Competition Deadlift` keeps date-scoped sumo/trap-bar resolution; no blanket rewrite.
- `Hyperextensions` keeps its own id and remains `history_equivalent_of: back_extension`.

The generated mapping is kept for audit at [`config/variants.mapping.yaml`](../config/variants.mapping.yaml).
A pre-migration database backup was made at `data/coach.db.pre-variant-20261020` (git-ignored).

[`config/variants.v1.yaml`](../config/variants.v1.yaml) lists the squat/bench/pull variants as
selection candidates. The template still decides the default prescription; ticking **Apply
selection** in Prescribe (or `run --apply-selection`) applies at most one substitution per slot
and re-solves the load from the selected lift (`MOD-SELECT-001`).

## 5. Selection tuning

[`config/selection.v1.yaml`](../config/selection.v1.yaml) holds the weights and rotation
window. The selector uses readiness, recent stress, rotation, suitability preference and the
fitness-fatigue state. The model is **cached per database version** (file mtime/size), so the
selector does not pay the fit cost on every request. Selection comparability is implemented as A/B/C classes
(`DEC-SELECT-03`); see [SELECTION-COMPARABILITY.md](SELECTION-COMPARABILITY.md). Symptom and
stress/readiness suggestions add tax metadata and a trigger, but remain explicit; see
[READINESS-EXERCISE-SELECTION-PLAN.md](READINESS-EXERCISE-SELECTION-PLAN.md). Per-exercise preference comes from Athlete
suitability, not config.

## 6. Validation checklist

- [ ] canonical entity resolves: `strength-coach state` or a fresh import;
- [ ] new variant has history (or accept that it starts at no history);
- [ ] template parses: `strength-coach select --date YYYY-MM-DD --session-type T`;
- [ ] golden/rep-range tests updated if the template changed;
- [ ] server restarted.
