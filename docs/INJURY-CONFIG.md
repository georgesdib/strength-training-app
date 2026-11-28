# INJURY CONFIG — changing which lifts load a region

`config/injuries.v1.yaml` is the **only** place that says which exercises load a region. No
module knows that a squat loads the knee: the signal, the readiness ceiling, exercise selection
and the local deload all read this file. If a mapping is wrong, the fix is here — not in code.

This page is the how-to. The behaviour those mappings feed is in
[INJURY-SIGNAL.md](INJURY-SIGNAL.md); the readings they consume are in
[SYMPTOM-LOGGING.md](SYMPTOM-LOGGING.md).

## 1. What the file controls

| key | read by | effect |
|---|---|---|
| `regions.<id>.label` | CLI, API, UI | display name only; the id never changes |
| `links.direct` | signal + deload | weight **2** per working set |
| `links.indirect` | signal + deload | weight **1** per working set |
| `min_session_load` | signal + deload | weighted sets a session needs to count as an exposure (default 2) |
| `base_symptom_free_days` etc. | signal | recovery window and tolerated-session requirement |
| `max_entry_age_days` | signal + deload | a reading older than this cannot speak for today |
| `policy.signal` | signal | `false` removes the region from the signal (no ceiling, no selection penalty, no review certificate) |
| `policy.deload` | deload | `false` keeps the region out of the local reactive deload |

Nothing else reads the file. A region with both consumers off is recorded and displayed but
changes no prescription.

## 2. How a lift is matched

`ExerciseLink.matches` ORs four kinds of clause:

```yaml
direct:
  patterns: [squat, knee_extension]      # taxonomy pattern of the exercise
  muscles: [erectors]                    # primary muscles
  flags: [high_fatigue_spinal]           # boolean key on the taxonomy entity
  exercises: [ssb_squat, front_squat]    # canonical exercise ids
```

- `patterns`, `muscles` and `flags` are **validated at load time**. A typo aborts the config
  with the unknown name, because a pattern that matches nothing would read as "no exposure".
- `exercises` ids are validated too: an id that is not in
  `config/exercises/taxonomy.v1.yaml` aborts the load.
- All four are ORed. `direct` wins over `indirect`; a lift that matches both is counted once,
  as direct.

A session is an **exposure** for the region when `sum(working sets × weight) >= min_session_load`
over that date. On the default of 2, one direct set or two indirect sets is enough.

## 3. Worked changes

### 3.1 A lift should count as direct, not indirect

Move the pattern (or add the id) from `indirect` to `direct`:

```yaml
  core:
    indirect:
      patterns: [squat, squat_unilateral, hinge, hinge_unilateral, carry]   # before
```

→ remove `squat` from `indirect` and put it under `direct`. Effect: a squat becomes a core
exposure by itself (weight 2), and — if the signal is on — a core flare now caps squats at 50%
rather than 60%.

### 3.2 Stop a region reacting to a whole family

Delete the pattern from both blocks. Example: a core reading should not touch squats at all:

```yaml
  core:
    direct:
      patterns: [core, core_flexion, core_anti_extension, core_stability, core_isometric]
    indirect:
      patterns: [carry, horizontal_push_bw]     # squat and hinge removed
```

Effect: 65 mapped lifts drop to 14, and the local deload can no longer cut a squat because of
a core symptom. This is the shipped mapping (`DEC-INJURY-08`); the count is pinned in
`tests/test_injury_signal.py`, so change both or neither.

### 3.3 Name specific lifts instead of a family

Grip is a property of the exercise, not of the movement shape, so the forearm region names its
lifts:

```yaml
  forearm:
    direct:
      patterns: [horizontal_pull, vertical_pull, carry]
      exercises: [trap_bar_deadlift, conventional_deadlift, rdl, shoulder_shrugs]
```

Add or remove ids to change the set. Prefer this over a new flag when only a handful of lifts
need the link.

The named ids here are deadlift and shrug variants, which the `horizontal_pull` and
`vertical_pull` patterns do **not** match: the list adds heavy-grip hinge work, it does not
duplicate the pulls. Removing the patterns to "de-duplicate" would drop every row and pull-up
from the region.

### 3.4 Prefer a flag when the property is not the pattern

If a property cuts across patterns and the taxonomy does not express it yet, add a boolean to
the taxonomy entities and reference it:

```yaml
# config/exercises/taxonomy.v1.yaml, on the lift
  conventional_deadlift:
    grip_intensive: true
```

```yaml
# config/injuries.v1.yaml
  forearm:
    direct:
      flags: [grip_intensive]
```

That is the right shape when the property is "how it is held", not "what the movement is".
It also means future lifts need only the flag, not a config edit in two files.

### 3.5 Add a region

```yaml
  ankle:
    label: "Ankle"
    policy: {signal: true, deload: true}
    links:
      direct: {patterns: [plantar_flexion]}
```

Checklist: the id is new and lowercase; every pattern/flag/muscle/id exists; the label is what
you want the CLI and UI to print. There is no migration — regions are config, not schema.

### 3.6 Take one consumer off a region

```yaml
  core:
    policy: {signal: false, deload: true}
```

`signal: false` keeps logging and the local deload but removes the load ceiling, the selection
penalty and the review certificate. `deload: false` keeps everything except the local deload.
Both off means the region is record-only.

### 3.7 Change the local deload's trigger

`config/deload.v1.yaml`:

```yaml
reactive:
  consecutive_flares: 2      # exposures needed, shared with the whole-session trigger
  local:
    enabled: true
    lookback_days: 21        # how far back an exposure still counts
```

Set `local.enabled: false` to stop every regional deload without touching the per-region
policy. The whole-session triggers (spinal cap, two flaring sessions) are unaffected.

## 4. Verifying a change

```bash
strength-coach injury                     # every region: policy, status, mapped-lift count
strength-coach injury --region core --show  # the exact ids the region now loads
strength-coach deload status --date 2026-11-28  # what a regional deload would do today
strength-coach symptom --show             # the readings those mappings consume
```

Then the focused tests:

```bash
./check.sh --files config/injuries.v1.yaml config/deload.v1.yaml
```

`tests/test_injury_signal.py` pins the shipped policy matrix and rejects unknown
patterns/flags/muscles/ids; `tests/test_deload_local.py` covers the regional trigger and the
reducer's scope.

## 5. What a mapping change can move

- **Lifted count.** `injury --region <id>` before and after. A region that suddenly matches 60
  lifts will cap or deload most of a session.
- **The ceiling.** If `policy.signal` is on, a flaring region caps its direct links at 50% and
  its indirect links at 60% (`DEC-INJURY-04`, `DEC-INJURY-07`).
- **The deload scope.** A local deload reduces only the mapped exercises; the rest of the
  prescription stays byte-identical.
- **The review prompt.** A flaring region gets its own review task; the linked count appears in
  it.
- **Whether pressing counts as an elbow exposure.** `biceps` maps pressing as *indirect*
  (`DEC-INJURY-08`). Indirect carries weight 1 rather than 2, but it still puts pressing days
  in the region's deload scope: a biceps/elbow flare will ease bench and overhead work. That is
  intended — pressing loads the elbow — and it is the reason the pattern list lives in config
  rather than in code.

Two rules of thumb: keep `indirect` for "loaded but not the limiting tissue", and prefer the
narrowest clause that names the lifts you mean. Broad indirect links are how one reading ends
up touching half the catalogue.

## 6. Before you commit a mapping change

1. `strength-coach injury --region <id> --show` — does the lift list look right?
2. Does the change belong in `direct` or `indirect`? Direct changes the ceiling and the deload
   weight; indirect is a gentler claim.
3. Did you keep the region's id and label stable? History and the API key off the id.
4. If you added a pattern or flag, is it in the taxonomy and documented in
   [DATA-MODEL.md](DATA-MODEL.md)?
5. Run the focused tests, then `./check.sh`.

## Related

- **Decisions:** [DECISIONS.md](DECISIONS.md) — `DEC-INJURY-01` to `DEC-INJURY-07` (exposure
  model, ceiling, verification), `DEC-SYMPTOM-03` (regions stay separate), `DEC-SYMPTOM-06`
  (per-region policy), `DEC-PROGRAMME-14` (local deload).
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md) — per-region recovery windows and
  the two-exposure trigger remain assumptions, not findings.
- **Roadmap:** [ROADMAP.md](../ROADMAP.md) §4.7 (injury signal).
- **Signal behaviour:** [INJURY-SIGNAL.md](INJURY-SIGNAL.md) — statuses, tolerated loading, the
  recovery certificate.
- **Readings:** [SYMPTOM-LOGGING.md](SYMPTOM-LOGGING.md) — the scale, characters and sides.
- **Schema:** [DATA-MODEL.md](DATA-MODEL.md) §11.5–11.7.
