# VOLUME MODULATION — weekly target, session cap, and a settings layer

**Status: design accepted; constitution 1.17.0; step 1 (read-only weekly budget), step 2
(per-group budget behind the off-by-default profile flag), step 2b (opt-in main-lift reduce),
step 9a (read-only compensation preview) and step 9b (opt-in compensation application) are
implemented (2026-10-26).** This document specifies a volume budget (a weekly target plus a
per-session cap) and the settings/modality layer it must sit behind. It records the evidence,
the rules, the decisions and a phased path. Step 1 is read-only; 9a is a preview; 9b is opt-in;
9c (`drop`) has an agreed two-branch design (§4.6) but is not implemented; steps 3–8 are not
implemented.

At a glance: weekly target **57 sets** (51 targeted + 6 untargeted), session cap **30** total
plus per-pattern and time caps, allocation against the **projected week** with a ±10% deadband,
safety cuts lower the **effective target**, no cross-week debt, phased automatic accessory
trim/top-up, and a settings/modality registry with append-only profiles. `MOD-VOL-003` is
declared in constitution 1.16.0; it only runs when the athlete profile enables it (default off).
document yet (`DEC-VOLUME-06`, `DEC-VOLUME-07`).

Related: [FREQUENCY-AND-VOLUME.md](FREQUENCY-AND-VOLUME.md), [VOLUME-MANAGEMENT.md](VOLUME-MANAGEMENT.md),
Q26 in [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md), LIM-51 in [LIMITATIONS-REGISTER.md](LIMITATIONS-REGISTER.md).

---

## 1. The problem this solves

The athlete will:

- miss sessions;
- sometimes shorten a session;
- sometimes extend one.

Today the programme is a fixed three-session template. `--sessions-per-week` only selects
weekdays, so a one-session week delivers about one third of the weekly sets (19 vs 61 in the
reproduced example) and nothing redistributes a short or long session. The request is a
**weekly target and a per-session cap** used to modulate the session in both directions.

Two design questions must be answered together:

1. **What is the weekly dose, and how is it spent?** (the budget)
2. **Who is allowed to change a prescription, and how is that recorded?** (the settings layer)

The second is not optional: DUP, the spinal cap, deload, the MRV cap and the new budget are all
"modalities" that the athlete may want on or off, with their factors visible. A budget hard-wired
into the engine would be a fifth scattered `enabled` flag.

## 2. What the programme delivers today

The four session types form a six-session (two-week) cycle. Building one full cycle gives
**114 working sets**, i.e. **57/week**:

| pattern (ledger group) | sets/week | MEV | MAV | MRV |
|---|---:|---:|---:|---:|
| squat (incl. split squat) | 10 | 6 | 8–12 | 14 |
| hinge | 6.5 | 6 | 6–9 | 10 |
| horizontal push | 12 | 8 | 10–16 | 18 |
| horizontal pull | 9 | 4 | 6–10 | 12 |
| vertical push | 3 | 3 | 4–8 | 10 |
| vertical pull | 4.5 | 3 | 4–8 | 10 |
| core | 6 | 3 | 4–9 | 12 |
| hinge unilateral | 0 | 0 | 0–6 | 8 |
| **targeted total** | **51** | | | |
| untargeted (erector 3, power 3) | 6 | — | — | — |
| **week total** | **57** | | | |

Week-to-week phases are not identical: starting at bench+squat gives 56, then 58 (squat 12 then
8; hinge 5 then 8). A budget that treated 58 as "over 57" would trim every other week, so the
model needs a tolerance band.

Note on the 19-vs-61 example: the reproduced live week totalled 61 because the stored history
triggered under-MEV additions; the pure template cycle is 114/2 = 57. The budget targets the
programme, so an active under-MEV increment must be included in the target rather than trimmed
back (see §6).

## 3. The model

### 3.1 Terms

| term | meaning |
|---|---|
| `weekly_total` | explicit total for one week; must equal the sum of `weekly_target`; default 57 |
| `weekly_target[pattern]` | hard working sets for one week, by ledger group (default: the cycle average above) |
| `weekly_floor[pattern]` | MEV; the level below which the week is "under" (report only) |
| `weekly_ceiling[pattern]` | MRV; the hard ceiling already enforced by `MOD-VOL-001` |
| `completed[pattern]` | stored working sets in the current week |
| `exempt[pattern]` | sets removed by safety/recovery rules; lowers the week's target, not the cap |
| `effective_target[pattern]` | `max(0, weekly_target - exempt)`; the dose the budget actually plans against |
| `remaining[pattern]` | `max(0, effective_target - completed)` |
| `projected_week` | `completed + today's plan + the template sets of the remaining planned sessions` |
| `session_cap` | maximum working sets in one session: total, per pattern, and by time |
| `tolerance` | band inside which nothing changes (±10% of the total, ±1 set per pattern) |
| `week` | ISO week, Monday–Sunday |

Warm-ups never count. Working sets count regardless of load source (barbell, bodyweight,
machine), matching the existing ledger. The pattern grouping is the ledger's
`volume_target_key` mapping, so the budget and the report cannot disagree.

### 3.2 Target source

**Recommended: the cycle average (51 targeted sets, 57 total).** At three sessions a week the
budget is neutral; at one or two sessions the same weekly target is compressed. This is the only
option that changes no prescription on a normal week.

Alternatives, exposed as config `target_mode`:

- `landmark` — use MAV's low value (squat 8, hinge 6, push 10, pull 6, vertical push 4,
  vertical pull 4, core 4). This is a programme change: it lowers push and pull from current
  levels and raises nothing.
- `explicit` — per-pattern values the athlete sets, checked against MEV/MRV for feasibility.

Every target is config, not code. Untargeted patterns (direct erector work, power) stay outside
the budget because they are dosed by other rules (`PRG-EREC-001`, the power slot).

### 3.3 Session cap

Three caps, whichever binds first:

1. **Total working sets: 30.** Current sessions are 19–22, so this allows roughly one extra
   session's worth of top-up without turning a session into a meet.
2. **Per pattern: squat 8, hinge 6, horizontal push 8, horizontal pull 8, vertical push 5,
   vertical pull 5, core 6, hinge unilateral 5.** These are roughly `ceil(weekly_target / 2)`
   rounded up, and never above the pattern's weekly MRV.
3. **Time.** The existing estimator (`sets × (30 s + rest_s)`, plus warm-ups) must stay within
   the athlete's `max_session_minutes` (80 planned, 90 hard). If the set cap would exceed the
   time cap, the time cap wins and the plan reports the set count achieved.

At 57 weekly sets and a 30-set cap, **two sessions can meet the target and one cannot**. That is
the honest answer to the original complaint, and it should be stated, not hidden.

### 3.4 Feasibility check

For the chosen target, cap and frequency:

`min_sessions = max( ceil(total_target / session_cap), max over patterns ceil(target[p] / pattern_cap[p]) )`

Also check time: `ceil(total_estimated_minutes / time_cap)`. With the recommended numbers this
is 2 sessions/week. Feasibility uses the nominal target at the start of the week; an exemption can
only lower it, so a week that starts infeasible can still become feasible. If the athlete picks
`--sessions-per-week 1`, the forecast must say "target 57, cap 30, minimum 2 sessions: 27 sets
unreachable" rather than silently delivering 19.

### 3.5 Week window and tolerance

- ISO week (Mon–Sun), matching the ledger and the Mon/Wed/Fri schedule. A session on Sunday
  belongs to that week.
- **No cross-week debt.** A missed Sunday is not made up on Monday. The evidence for weekly
  dosing gives no basis for a fortnightly catch-up, and a rolling debt invites volume spikes.
- Tolerance: no change when `|completed - effective_target| <= 10%` of the total and
  per-pattern deviation is ≤ 1 set. This absorbs the 56/58 phase variation.

### 3.6 Exemptions — safety cuts lower the target, not the cap

A budget that made up every removed set would undo the safety layer. The mechanism is an
**effective weekly target**:

`effective_target[pattern] = max(0, weekly_target[pattern] - exempt[pattern])`

An exemption lowers the week's **dose** for that pattern, so the removed sets are not reallocated.
It does **not** lower the session cap: the cap is a per-session fatigue guard, and cutting it
would also block a legitimate top-up later in the week. The MRV ceiling is unchanged too — a
safety cut lowers the dose, not the safety limit. The tolerance band uses the effective target;
feasibility is computed on the nominal target at the start of the week.

| removed by | lowers effective target? | why |
|---|---|---|
| readiness set valve (`MOD-FAT-001`) | **yes** | a recovery decision must not be re-added next session |
| deload (`MOD-DELOAD-001`) | **yes**, to the deload plan | a deload is a planned low week, not a shortfall |
| spinal trim (`MOD-SPINE-001`) | **yes** | a safety veto is not volume debt |
| constraint/injury veto | **yes** | same |
| session missed entirely | **no** | the athlete wants the remaining volume reallocated |
| session ended early | **no** (unless a symptom was recorded) | the common case the request targets |
| `MOD-MIN-001` minimum session | **no** by default (config can exempt) | it is a time choice, not a recovery rule |

Each exemption is stored per pattern with its source id, so the report can say why the week's
target is lower.

If the last session on a pattern recorded a symptom flare, automatic top-up for that pattern is
suppressed and the warning says so. The budget must never push volume into a region that just
flared.

## 4. Allocation algorithm

The budget is evaluated against the **projected week**, using the **effective weekly target**
after exemptions, not one session's remainder. That is what makes a long Monday trim Wednesday,
and a missed Wednesday top up Friday, without overfilling the early part of the week.

1. Compute `effective_target[pattern] = max(0, weekly_target - exempt)` from the week's recorded
   safety/recovery removals; each keeps its source id.
2. Determine the week's planned sessions: the completed sessions, today, and the sessions the
   athlete still intends to train (the programme schedule, or `sessions_per_week_target` minus
   completed). If the future is unknown, use the rolling session-type templates.
3. `projected = completed + today's template + the template sets of the remaining planned sessions`,
   measured against the effective target. The band is 10% of the effective target (at least one
   set per pattern).
4. If `effective_target - band <= projected <= effective_target + band`, change nothing.
5. If `projected > effective_target + band`: trim today's non-essential accessories from the end,
   down to one set each, until the projection is inside the band. Essential items are never
   trimmed; if they alone keep the projection over, warn.
6. If `projected < effective_target - band`: top up today's non-essential accessories in the
   patterns furthest below target, round-robin, up to the per-item maximum (8), the per-pattern
   cap, the total cap and the time cap, until the projection is inside the band. Main lifts are
   not topped up by default.
7. If the cap is reached and the projection is still below the band, warn with the arithmetic and
   the minimum frequency. Top-up capacity is limited by the accessories present: if a pattern has
   no non-essential item (for example squat on a bench+squat day, where the competition squat is
   essential), it stays unmet and the warning names it.
8. Record the arithmetic (target, exempt, effective target, completed, projection, cap,
   allocated, feasibility) in the `MOD-VOL-003` `prescription_modifier` detail; `prescription`
   has no notes column. Cite `MOD-VOL-003` on every changed item.

A deload week is the week-scale case: the effective target is the deload plan and no debt follows.
Future sessions are projected at **template** sets; their own readiness or deload adjustments are
not known yet. The projection is recomputed on every build, so a changed plan or a new stored
session updates it.

### 4.1 Per-group triggers (step 2)

Step 1 exposes, per group, the week status, the persistent four-week status and the top-up
capacity. Step 2 acts on it:

- top up a group only when it is below its own band **and** has non-essential capacity; the
  total band remains an aggregate guard, not the only trigger;
- trim a group that is over its own band, accessory-first; never pay for a bench surplus by
  cutting squat or pull accessories;
- never inflate an essential main lift; if a group is under with capacity 0, warn and leave the
  decision to the athlete;
- use the four-week ledger for a **programme** change; the weekly trigger handles scheduling
  shortfalls and phase noise.

### 4.2 Cross-group quota compensation (design agreed; later)

The athlete's model, at the `drop` end of the policy: once a group's weekly quota is met, the
next session gives that group no work and moves the freed sets to other groups — more bench, less
hinge (squat and hinge are similar) but not zero (they are not the same movement).

**Strength-preserving is the default for this athlete.** The policy lives in
`athlete_profile.main_lift_policy` (append-only; `preserve` default, `reduce`/`drop`
opt-in), so it is athlete state, not prompt text or a hidden config. Under `preserve` the main
lift still runs at its template sets even when the group quota is full; only **accessory** volume
is withheld and reallocated. "No squats at all" is `drop`, not `preserve`.

`drop` is the volume-first mode, not the default strength programme, because it can remove a main
lift from a session. The default (`preserve`) keeps the main lift and moves only accessory volume.

**Quota accounting**
- Every working set counts, main lifts included. In `preserve` a main lift is never trimmed, so
  a session can exceed the group target; the target is a **floor for accessories**, not a hard
  cap. The report warns when a preserved main lift pushes the group over.
- A group is **filled** when the week reaches its effective target (tolerance applies). Its
  non-essential accessories are then withheld; the main lift stays in `preserve`.
- A **persistent four-week deficit** is a programme change (add or swap an accessory), not a
  weekly top-up. The weekly trigger only handles scheduling shortfalls and phase noise.

**Compensation pool**
- Each session type gets one optional, non-essential **compensation slot**. Candidates need an
  executable load; the starting pool is `dumbbell_bench_press` for horizontal push and `rdl`
  for hinge (taxonomy/config, no code).
- When a group is filled, its accessory slot is withheld. The compensation slot may be filled
  from a group below quota, chosen by the weights below. If the session has no free non-essential
  slot or no executable candidate, warn; do not inflate a main lift.
- Adding sets to an essential main lift is a separate, opt-in `main_lift_topup` (default false),
  never automatic compensation. It adds to the receiver's main lift, never trims the filled
  group's main lift.

**Weights**
- `similarity[a][b]` is config: squat↔hinge 0.7, squat↔bench 0.2, hinge↔bench 0.2, push↔pull
  0.3; the remaining pairs default to 0.1. `floor` is 0.1.
- `compensation_weight(a -> b) = max(floor, 1 - similarity[a][b])`, normalised over receiving
  groups with headroom. A filled squat sends most freed sets to bench, less to hinge, and still
  some to hinge.
- The athlete profile selects the mode (`preserve`/`reduce`/`drop`); the matrix is config,
  not per-athlete profile.

**Caps**
- Per-group MRV, session cap, time cap, spinal cap (sumo/hinge), constraints, injury ceilings,
  readiness and deload still apply. Compensation cannot exceed them.
- Only exercises with an executable load (e1RM, double progression or bodyweight) can receive
  compensation; an unknown-load addition is refused, not guessed.

**Identity and provenance**
- `preserve` changes no session identity: only a non-essential accessory slot is replaced.
- `drop` removes a main lift; rebuild the rolling schedule/template or make it a distinct
  volume-first session type. Never silently relabel a squat session as a squat session.
- `MOD-VOL-003` covers set changes; `MOD-VOL-004` covers accessory slot replacement and
  compensation. Both need constitution approval at implementation.

Evidence limits:

- No trial shows that bench sets substitute for squat sets, or at what ratio. The similarity
  weights are a coaching heuristic (`ASSUMPTION-47`), not measured equivalence.
- Strength is specific: removing the squat main lift can reduce squat strength even when weekly
  set volume is maintained elsewhere. That is why `preserve` is the default and `drop` is
  opt-in.
- Hypertrophy may tolerate more redistribution, but the evidence is per muscle group, not
  cross-group.

Phasing: per-group diagnostics (step 1, done) → within-template per-group triggers (step 2) →
compensation preview (step 9a) → opt-in compensation application (9b) → volume-first drop
(9c, decision + simulation).

### 4.3 Frequency above three sessions

The budget math is frequency-agnostic: `sessions_per_week_target` can be 4, the report projects
four sessions, and the per-session cap applies to each. The target is still the three-session
average (57 sets), so four sessions **spread** the same dose; they do not automatically add
volume. To use the fourth session for more volume, set an explicit `weekly_total` and matching
`weekly_target` in `config/volume.v1.yaml` (the report and engine read it), or set a higher value
per group.

Strength-preserving still applies by default: the main lifts stay at template sets, so four
full-body sessions add main-lift frequency and may exceed the 57-set target; the budget trims
accessories only and warns. In the opt-in `reduce` mode a filled group's main lift is trimmed to
the floor instead. A fourth heavy full-body day can also collide with the MRV, spinal and readiness
caps. The sensible first design is a fourth **accessory/weak-point** session, not another heavy
squat/hinge day; that is a programme decision.

The scheduler is **out of scope for now**: `programme --sessions-per-week` stays 1–3. A
four-session week is manual single-session training; the budget report still projects four when
the profile target is 4. No four-day forecast is planned.

### 4.4 What steps 2 and 2b actually do (implemented)

This is the current, implemented behaviour; it is the reference for the reduce/drop work.

**Activation and precedence**
- `athlete_profile.volume_budget_enabled` is authoritative and defaults to off (0). If no
  profile flag is recorded, `budget.enabled` in `config/volume.v1.yaml` is the fallback.
  `MOD-VOL-003` only runs when the budget is enabled.
- `athlete_profile.main_lift_policy` defaults to `preserve`. `reduce` is implemented (step
  2b). `drop` is recorded but not implemented: the prescription warns and keeps the main lift.

**Targets and inputs**
- `budget.weekly_total` is explicit and must equal the sum of `budget.weekly_target`; config
  load fails if only one side is edited. The default is 57.
- `effective_target = max(0, weekly_target - exempt)`. Fixed template doses (erector,
  power jump) count in the total but are never changed.
- Completed = stored working sets in the ISO week. Projected = completed + today's items + the
  template sets of the remaining planned sessions; the number of future sessions comes from
  `sessions_per_week_target`. There is no cross-week debt.
- `tolerance` is ±10% of the total; a per-group band is at least ±1 set.

**Every knob is config-backed** (`config/volume.v1.yaml`, `budget:`; the engine has no
hidden allocation threshold):

| config key | default | role |
|---|---|---|
| `enabled` | false | fallback only when no profile flag is recorded |
| `weekly_total` | 57 | explicit total; must equal the sum of `weekly_target` |
| `weekly_target[pattern]` | 10/6.5/... | per-group target; fixed doses included |
| `main_lift_floor` | 3 | reduce mode: minimum main-lift sets of a filled group |
| `trim_enabled` | true | allow accessory trim |
| `top_up_enabled` | true | allow accessory top-up (disabled in reduce mode) |
| `session_cap.total` | 30 | **daily/session total cap** |
| `session_cap.per_pattern` | 8/6/... | per-group session cap |
| `tolerance` | 0.10 | total band (±10%) |
| `band_min` | 1 | per-group band minimum in sets |
| `min_accessory_sets` | 1 | trim floor for an accessory |
| `top_up_max_sets_per_item` | 8 | per-item top-up ceiling |
| `set_seconds` | 30 | execution seconds per set in the time estimate |
| `warmup_estimate_minutes` | 5 | planning warm-up allowance |
| `session_time_cap_minutes` | 80 | upper bound for the budget time cap |

The profile adds only `volume_budget_enabled` (authoritative on/off),
`main_lift_policy` (`preserve`/`reduce`/`drop`), and `max_session_minutes`, which can
only **lower** the config time ceiling. The engine's own planned-minutes ceiling may be lower
still. Nothing in the allocation is hardcoded except the rule IDs and the safety-reference set.

**Allocation**
1. A group acts when its own projected week is outside its band, and either the total is outside
   its band or the four-week ledger agrees (persistent under/over). This avoids reacting to the
   normal 56/58 phase noise.
2. If over: trim **non-essential** sets in that group, down to one set each, until the group is
   back at the top of its band. Never trim another group's accessories to pay for it.
3. If under: top up **non-essential** sets in that group, to at most eight per item, bounded by
   the per-pattern cap, total cap, time cap and MRV. No capacity means a blocked warning, not an
   essential add.
4. In `preserve`, essential items never move. In `reduce`, only the **main-lift** items of a
   group that was already filled before today move, and only down to the floor. A group with a
   safety ref in the current build is not topped up or reduced.
5. Every changed item cites `MOD-VOL-003`; the warning names the changes and the prescription
   note carries the before/after arithmetic.

**Reduce mode (step 2b)**
- Only with `main_lift_policy: reduce` and the budget enabled. "Filled" means the group had
  already reached its effective target **before today** (`completed >= effective`). If so, its
  **main-lift** items are trimmed to `budget.main_lift_floor` (default 3), never below the floor
  and never by adding sets. The lift stays in the session; the session type is unchanged.
- `preserve` never trims a main lift. `drop` is not this mode.
- Top-up is disabled while `reduce` is selected: the freed sets are not sent to another group
  (that is step 9). Only over-group accessory trims still run.
- A main lift with a safety ref in the current build is left alone. Tests: filled group, floor,
  safety skip, preserve unchanged, no cross-group top-up, citation.

**Order and caps**
- The budget runs after continuity and before VBT/under-MEV; MRV, spinal, deload and the minimum
  session still run afterwards and may trim further. No later rule re-adds a safety cut. The
  total, time, spinal, MRV, constraint, injury, readiness and deload caps all still bind.

**Exemptions**
- `record_exemptions` runs after a prescription is stored. For a present item with
  `MOD-FAT-001`, `MOD-DELOAD-001` or `MOD-SPINE-001` and fewer sets than its template
  slot, the difference is written to `volume_exemption`. The report subtracts it from the
  target, so a later session does not make up a safety cut.
- The current build skips top-up for a group with a safety ref. Removed items are not recorded:
  the budget only tops up items that are present, so it cannot resurrect one.

**Not implemented**
- `drop` (step 9c); cross-group compensation and the compensation slot pool; a separate top-up
  switch (top-up is part of step 2, disabled in `reduce`); a four-day programme forecast (manual
  single-session only); settings UI for the targets (the config file is the source).

### 4.5 Cross-group compensation — 9a preview and 9b application

9a is a read-only preview; 9b applies the selected slot **opt-in** when the budget is on. The
settings are under `budget.compensation` in `config/volume.v1.yaml`:

- `enabled` — show the preview and compute the selection; default true.
- `apply` — **true** in 9b; the engine adds the selected slot only when the profile budget flag
  is also on. Set false to return to a preview-only budget.
- `floor` — the inverse-similarity floor (0.1).
- `similarity` — squat↔hinge 0.7, squat↔push 0.2, hinge↔push 0.2, push↔pull 0.3; unknown
  pairs default to 0.1.
- `slots` — one optional non-essential slot per session type, with candidate exercises, sets,
  reps, RIR, rest and load source. A candidate needs an executable load; no history retries the
  e1RM basis, asks for an e1RM if needed, and refuses only if still unusable.

The preview works like this:

1. A group is **filled** when `completed >= effective_target` before today, the same rule as
   `reduce`. Its **non-essential** sets in today's template are the freed sets; main lifts stay.
2. The largest freed group is the source. Each slot candidate must be a different group that is
   under its target and has session headroom. **9b is additive**: it does not remove the source
   accessory, so it also stops at the **weekly high tolerance band**; if the projected week is
   already there, status is `weekly_full` and nothing is added.
3. The weight is `max(floor, 1 - similarity(source, receiver))`, normalised over the candidates.
   The **one** slot takes the highest weight; its sets are capped by the freed sets, the slot's
   configured sets, the receiver's shortfall, the per-group session cap, the session total cap and
   the remaining weekly headroom to the high band.
4. The report returns `freed`, `source`, `candidates` (weight, share, sets) and `selected`.
   Status is `disabled`, `no_filled_accessory`, `no_receiver`, `weekly_full` or `simulated`; the
   engine note adds `applied` or `refused`. `weekly_full` means the projected week is already at or
   above the high tolerance band; 9b adds nothing.

With `apply: true` and the budget on, 9b builds one new non-essential item from the selected
candidate using the normal `build_item` load solver. It is an **addition**, not a swap: the
source accessory stays, and the weekly high-band guard prevents it from pushing the total past
the high tolerance band. The item cites `MOD-VOL-004`; MRV, spinal, under-MEV, deload, total and
time checks still run afterwards. If the candidate has no working
history, the engine retries with the **e1RM basis**. If that also has no usable e1RM, the
Prescribe panel asks the athlete to enter one (and the CLI prints the `e1rm set` command), then
rebuilds. It refuses only if no usable load exists after that.

Worked example: squat is filled before today, so the hinge session's split-squat accessory frees
3–4 sets. Bench is short; the bench weight 0.8 beats hinge 0.3, so the one slot selects the
dumbbell bench. With a recorded dumbbell-bench load, 9b adds that item; without one, it refuses
and names the missing history.

`MOD-VOL-004` is declared in constitution **1.17.0**. When the slot has no load, the athlete
is asked for an e1RM rather than silently refused (`DEC-VOLUME-15`). Step 9c (`drop`) is
separate: its two-branch design is agreed in §4.6, but it is not implemented and `MOD-VOL-004`
does not remove a main lift.

### 4.6 9c drop — agreed design (not implemented)

The drop decision is made at the start of a session, from the remaining week, not from one slot.

**Branch 1 — total at or above the high tolerance band**
- There is no volume to reallocate. The session is a **technique-focused session**: no main lift,
  no working sets counted toward the weekly target and no compensation volume. It counts as
  attendance; record "week complete" and the original session. This is not a `volume_fill`.
- Rebuilding as the next normal type would just add volume and hit the same high band again, so
  it is not used.

**Branch 2 — below the high band, one group already filled**
- Remove that group's main lift and its non-essential work from the session.
- Build a distinct **`volume_fill`** session from the remaining session budget, using **multiple**
  non-essential slots rather than the single 9b slot:
  - fill the under-target groups by their shortfalls and the inverse-similarity weights (for a
    filled squat, bench gets more than hinge, but both can receive);
  - fill **into** the high tolerance band, not only to the nominal total; stop at the high band;
  - respect the daily/session cap, time, MRV, spinal and executable-load rules;
  - stop when the shortfalls are met, the session is full or the high band is reached; report
    any unreachable shortfall.
- The original session type and the reason are recorded; `volume_fill` is a distinct type,
  counts as a session, and is never silently relabelled as a normal squat/hinge session.
- If there is no under-target group or no capacity, use the technique-focused session instead.

**Default candidate pool (all configurable)**
- push: `dumbbell_bench_press`, then `incline_db_bench_press`;
- hinge: `rdl`; `single_leg_db_rdl` only when `hinge_unilateral` is targeted;
- horizontal pull: `dumbbell_chest_supported_row`, then `dumbbell_row`;
- vertical pull: `pull_up`, then `lat_pulldown`;
- vertical push: `landmine_press`;
- core: `ab_wheel`, then `hanging_leg_raise`.
- Avoid main-lift and high-spinal substitutes. Each candidate carries its own sets, reps, RIR,
  rest, load source and priority; all of it is overrideable in settings.

**Session identity**
- `volume_fill` and `technique` are first-class session types, not relabelled normal sessions.
- `volume_fill` counts as attendance and as the scheduled slot for the current week (so the
  filled type is not immediately re-requested), but not as a main-lift exposure for the omitted
  group. Accessory volume counts for the receiver groups. The original type, omitted group and
  filled groups are recorded and shown.
- `technique` counts as attendance, not as volume or main-lift exposure; it does not advance the
  main-lift rotation. The next week starts the normal cycle.
- The programme forecast and review/rubric must know both types; a `volume_fill` without a main
  lift must not be graded as a failed main session.

**Activation and safety**
- Only when the budget is enabled and `main_lift_policy: drop` is selected; `preserve`/`reduce`
  are unchanged.
- Automatic after that opt-in, with a per-session confirmation at competition/peak; the window
  is config with a default of **7 days** before `competition_date`; never remove a main lift
  silently.
- `MOD-VOL-005` will cover 9c; `MOD-VOL-004` remains the 9b single-slot application. No code,
  template or constitution change is made yet.

## 5. Worked examples

- **Normal week:** projected 56–58 vs target 57; inside the band; no change.
- **Readiness cuts two squat sets on Monday:** the squat effective target becomes 8, and those
  two sets are not re-added later. A long Monday still trims; a missed Wednesday still leaves the
  week short.
- **Missed Wednesday:** on Friday, completed 19 and today's template 20 → projected 39, against
  a low band of 51.3. Top up by the cap (+10 to 30); the week lands at 49/57. Warning: 8 sets
  short with no session left; add a session or accept 49.
- **Short Wednesday:** on Friday, completed 31 (19 + 12) and today's template 20 → projected 51,
  just below the 51.3 band floor. Friday tops up by one set to 21; week 52/57, inside the band.
- **Long Monday (26 instead of 19):** on Wednesday, completed 26, Wednesday 22 and Friday 20 give
  a projected 68 against a high band of 62.7. Trim Wednesday's accessories by about six sets;
  the week lands at 62/57, inside the band, and the warning names what was trimmed.
- **One session a week:** projected 19 against a low band of 51.3; cap 30 → 30 sets planned and
  27 unreachable. Feasibility says the minimum is two sessions; the plan is 30 sets, not 19.

## 6. Interaction and precedence

Proposed order inside `build_prescription` (no reordering of existing safety layers):

1. template, selection, DUP;
2. readiness / continuity / back flare (load and optional set cuts);
3. **volume budget** (this proposal);
4. under-MEV — folded into the target (recommended) or skipped for targeted patterns; it never
   runs as an independent add on top of a budget that would trim it;
5. MRV cap (hard ceiling; runs after the budget);
6. spinal trim (hard veto);
7. deload — suspends the budget on its week;
8. technique throttle, warm-up attach, minimum session (user-selected), validation.

Under-MEV and the target: when a pattern has been below MEV and `MOD-VOL-002` is active, its
increment is part of the intended weekly dose, so the target is recomputed as template + active
under-MEV increments and the budget will not trim it back. If that coupling is too much for v1,
the fallback is to suspend `MOD-VOL-002` while the budget is on and let the athlete raise the
target in config. Either way, the two rules must not add and trim the same set.

## 7. Settings and modality toggles (future, designed in)

The athlete's request: put the modalities behind a setting flag, including DUP, the spinal cap
and the factors, and expose them to settings. The budget must be built as one of those modules,
not as a fifth hard-wired flag.

### 7.1 Current state

Toggles are scattered: `deload.enabled`, `undulation.enabled`, `volume.apply_mrv_cap`,
`volume.under_mev.enabled`, `readiness.set_reduction.enabled`, `readiness.composite.enabled`,
`e1rm-decay.apply`, `e1rm-calibration.apply`, `continuity-calibration.enabled`,
`fatigue-fitness.enabled`, `test-cadence.enabled`, `warmup.enabled`. The constitution
(`config/rules/programme.v1.yaml`) is versioned separately and owns the hard rules. The Settings
page exposes only the LLM and some Prescribe defaults; readiness weights have their own
append-only table.

### 7.2 Proposed registry

A single `config/modalities.v1.yaml` (or a section in an existing settings file) listing every
module:

```yaml
- id: volume_budget
  class: prescription_policy        # hard_safety | prescription_policy | display | experiment
  enabled: false                    # ships off until approved
  config: volume.v1.yaml#budget     # where its factors live
  depends_on: [volume_ledger]
  citations: [MOD-VOL-003]
  factors: [target_mode, session_cap, tolerance, exemption_minimum_session]
```

Classes:

- **hard_safety** — constraints, injury ceilings, RIR-0 floor, load validation. These cannot
  be switched off by a checkbox: turning one off is a **constitution change**, recorded as a
  `DEC` and a new rule version.
- **guarded_safety** — the weekly spinal cap and the per-exercise spinal costs. Modifiable in
  Settings, but only with a warning, a double confirmation, a required reason and an append-only
  profile. The rule (`PRG-SPINE-001`) stays in force at the new value and is cited with the
  profile; it is parameterised, not disabled. Disabling the rule or removing the citation is
  still a constitution change. See §7.6.
- **prescription_policy** — DUP, deload, MRV cap, under-MEV, readiness set valve, e1RM
  decay/calibration, selection, budget. Toggleable, but every change creates a profile and is
  cited in the prescription.
- **display** — reports and advisories (volume ledger, recent stress, injury attention).
- **experiment** — shadow-only models.

### 7.3 Profile, not a raw config edit

A config file edit silently changes future prescriptions and cannot explain an old one. Instead:

- a named **prescription profile** (append-only): `profile_id`, `name`, `effective_from`,
  `settings_json`, `reason`, `created_at`;
- each prescription stores the profile id and a snapshot, so `run` on an old date still shows
  the settings that were in force;
- precedence: profile > config > code default, mirroring `readiness_setting`;
- a diff preview before saving ("this turns off the MRV cap; today's session would gain 2 sets").

### 7.4 Factors exposed to settings

Each module declares its factors with a type, range, unit, default and what they affect. The
settings UI renders those, not raw YAML. The first candidates: volume budget (target mode, cap,
tolerance, exemptions), DUP cycle, deload interval and prescription, readiness weights,
MRV/MEV/MAV landmarks, e1RM source and decay, the readiness set valve, and the **guarded spinal
cap/costs** (§7.6).

### 7.5 Migration and tests

- Move the existing `enabled` flags into the registry without changing behaviour; a test pins
  registry defaults to the current config values.
- A test per module: disabling it changes only its cited outputs; the default profile
  reproduces today's golden prescriptions.
- A hard-safety module cannot be disabled without a waiver; the loader rejects a profile that
  omits the waiver or the constitution version.
- A guarded-safety change (spinal cap or cost) requires the warning acknowledgement, the double
  confirmation and a reason; the default profile reproduces today's prescriptions; the rule
  still evaluates at the new value and the prescription cites `PRG-SPINE-001` and
  `profile:<id>`.
- The spinal override is read by both the rule parameters and the taxonomy `spinal_cost`; a
  second copy is a test failure.
- Profiles round-trip, are append-only, and are cited on every changed item.

### 7.6 Spinal load: a guarded setting

The athlete asked for spinal load to be editable in Settings. It is a safety parameter, so it
gets the strongest guard short of "not editable":

**Parameters**
- `weekly_cap` — `PRG-SPINE-001.params.cap`, default 6.
- `costs` — the ordinal `spinal_cost` for each high-fatigue exercise, default from the rule.
- `heavy_exposure` — the display-only heavy-set advisory (4-week window, RIR ≤ 1); separate
  and non-prescriptive.

**Guard**
1. A warning says that the cap and costs are ordinal heuristics, not measured lumbar load; the
   normal week sits exactly at the cap, so raising it removes a guard and lowering it can make
   the normal programme non-executable.
2. A double confirmation: tick a confirmation **and** type the new cap (or `CONFIRM`), plus a
   required reason. CLI `settings spinal --cap 8 --confirm --reason ...`; the API requires
   `confirm: true` and the typed value.
3. An append-only profile records old/new values, the reason and the date; the prescription
   cites `PRG-SPINE-001` and `profile:<id>`.
4. The rule still runs at the new value and still vetoes. The profile is the single override
   layer: the rule params and the taxonomy `spinal_cost` must read the same override, never a
   second copy.

**Not allowed:** disabling `PRG-SPINE-001`, removing its citation, or negative costs — those
remain a constitution change. Settings range: cap 0–12, costs 0–5; outside that is a config edit
(`ASSUMPTION-46`). The erector ramp (`PRG-EREC-001`) is a separate rule and is not part of
this setting.

### 7.7 Recommended scope split

The settings layer is a larger piece of work than the budget. To avoid blocking the request:

- **v1 budget:** read-only report plus a config-backed settings object, then trim/top-up behind
  a flag; no scattered constants, so it can move into the profile store unchanged;
- **v2 profile store:** append-only profiles, the budget reading them, the guarded spinal
  cap/costs and the Settings UI for the budget and spinal parameters;
- **v3 registry migration:** move the remaining flags (DUP, deload, MRV, under-MEV, readiness
  valve, e1RM) into the registry; hard-safety stays on the constitution path.

## 8. Provenance and data

`MOD-VOL-003` is the proposed **modifier id** for the weekly volume budget. It sits in the
same namespace as `MOD-VOL-001` (MRV cap) and `MOD-VOL-002` (under-MEV): `MOD` for modifier,
`VOL` for volume, `003` because the first two are taken.

The constitution declares **modifiers** separately from **rules** (`config/rules/programme.v1.yaml`,
section `modifiers`). A rule passes, fails or vetoes; a modifier transforms a prescription before
the policy engine sees it. Each modifier carries an `id`, a `statement`, a `when`, a `then` and
an `implemented_by` entry. Declaring one is a **constitution version bump** (the document is at
1.14.0), which is why it needs the owner's approval.

It is declared in the constitution at 1.16.0 (1.15.0 plus the reduce mode), with the
compensation application added as `MOD-VOL-004` in 1.17.0; it is implemented by
`strength_coach/prescribe/volume_budget.py::apply`. Every item whose sets change cites
`MOD-VOL-003`; the prescription note carries the arithmetic. The budget is off unless
`athlete_profile.volume_budget_enabled` is set (`DEC-VOLUME-07/08`).
- No prescription notes: `prescription` has no notes column. The arithmetic goes in the
  `MOD-VOL-003` `prescription_modifier` detail; the cuts go in `volume_exemption`.
- `prescription_modifier` rows for every changed item, with the profile id.
- The budget itself is computed. Two tables are added during implementation:
  `volume_exemption` (step 1, append-only) and `prescription_profile` (step 4).

## 9. UI / CLI / API

- `strength-coach volume --week`: target, exempt, effective target, completed, projection, cap,
  feasibility.
- `state --volume-budget on|off --main-lift-policy preserve|reduce|drop`; the Athlete page has
  the same two fields. The budget is off until enabled.
- Prescribe page: a "Weekly volume" panel (target / done / remaining / cap / minimum sessions)
  and +/− set badges on items.
- Programme forecast: budget-aware allocation across projected dates, with the unreachable
  warning; the forecast simulates previous projected sessions as completed rather than treating
  every date as isolated.
- Workout end: "week 49/57; 8 sets remaining; 1 session left".
- Settings (v3): modality list with classes, factors, dependencies and diff preview, including
  the guarded spinal cap/costs with warning + double confirmation (§7.6).
- CLI/API parity: `settings modalities`, `settings profile`, `settings spinal --cap ... --confirm`,
  `GET/POST /api/modalities`, `/api/profiles`; the same core functions as the CLI (AGENTS.md §10).

## 10. Implementation sequence

Each step is a reviewable commit or small series. Every step ends with the full suite and a
deliberate golden update where a prescription changes.

**0. Settle four details (design, no code).**
1. **Exemption storage.** `prescription` has no notes column (confirmed in step 0), so record
   the sets a safety modifier removes in a small append-only `volume_exemption` table
   (prescription_id, effective_on, pattern, sets, source) and sum the week's rows. A missed
   session has no prescription, so no rows.
2. **Projection source.** Use the rolling `schedule.next_session_type` plus
   `sessions_per_week_target` minus completed sessions; do not depend on a persisted programme
   forecast. Recompute every build.
3. **Time cap and warm-ups.** Warm-ups are attached after deload, so the budget uses a config
   warm-up allowance (default 5 min) in the time estimate; the measured clock remains
   post-workout.
4. **Target derivation.** Store `weekly_total` and `weekly_target` explicitly in
   `config/volume.v1.yaml` with a test that the total equals the six-session template sum (114/2)
   and the per-group targets sum to the total; a template or one-sided edit then fails the test
   or the config load rather than silently moving the dose.

**1. Read-only budget (no prescription change) — implemented 2026-10-26.**
- `prescribe/volume_budget.py`: target, completed, exemptions, projection, effective
  target, allocation, feasibility. It lives in `prescribe` because it needs the session
  templates and the rolling schedule, which `features` may not import.
- `budget:` config section, default off.
- Per-group week status, persistent four-week status and non-essential top-up capacity, with
  the capacity drawn from the actual session template.
- `volume --budget`, `GET /api/volume/budget`, read-only Prescribe panel.
- Tests: arithmetic, ISO-week boundary, 56/58 phases, worked examples, feasibility, exemption
  summing, template consistency, per-group status/capacity.
- Gate: full suite; compare the report with 3–4 real weeks. No prescription change.

**2. Apply trim and accessory top-up (first prescription change) — implemented 2026-10-26 behind
 the profile flag.**
- `_apply_volume_budget` after continuity, before under-MEV; non-essential sets only; trim to
  the top of the band and top up under groups where capacity exists; exemptions recorded.
- Per-group trigger: act on a group outside its own band, not only on the total; top up only
  where capacity exists; trim the group that is over, never a different group's accessories.
- Declare `MOD-VOL-003`, constitution 1.15.0 (amended to 1.16.0 for step 2b), `implemented_by`; flag defaults off, enabled in
  the athlete's profile after review.
- Tests: long-session trim, essential floors, MRV/spinal still win, exemptions not re-added,
  citation, golden updated deliberately.
- Gate: full suite, a real-week check, no MRV or spinal breach.

**2b. Main-lift reduce (opt-in) — implemented 2026-10-26.**
- Only when the profile has `main_lift_policy: reduce` and the budget is enabled. A group counts
  as filled when `completed >= effective_target` **before today**; its main-lift items are then
  trimmed to `main_lift_floor` (default 3), never below the floor, never by adding sets, and never
  in `preserve`. The session type does not change: a squat session still has a squat.
- Top-up is disabled in `reduce`; the freed sets are not sent to another group until step 9.
  `drop` is not part of step 2b. A main lift with a safety ref is left alone.
- Tests: filled group, floor, safety skip, preserve unchanged, no cross-group top-up, citation.
- Gate: full suite and a real-week check; enable `reduce` in the profile only deliberately.

**3. Top-up review (included in step 2).**
- Step 2 already tops up non-essential accessories under the same profile flag; there is no
  separate switch. Review 2–3 real weeks with the per-item/per-pattern/total/time caps and the
  blocked warnings, then adjust the caps or defaults.
- No new code is planned here unless the review shows a defect; any separate opt-in would be a
  new decision.

**4. Profile store and settings loader.**
- `prescription_profile` (append-only), repository/query, precedence profile > config >
  default, profile snapshot on the prescription.
- The budget reads the same settings object; no budget-code change.
- CLI `settings profile`, API; no UI yet.

**5. Settings UI and the guarded spinal setting.**
- Settings page: modalities/factors, diff preview, profile save; budget fields.
- Spinal: warning, double confirmation, reason, profile; `PRG-SPINE-001` params and taxonomy
  costs read one override; tests for the guard and the single source.
- CLI/API parity.

**6. Forecast and workout panels.**
- Budget-aware programme projection across dates; Prescribe/Workout weekly panel; `volume`
  report; docs update.

**7. Migrate the remaining flags.**
- DUP, deload, MRV, under-MEV, readiness valve, e1RM into the registry; behavior-preserving;
  golden tests; hard-safety stays on the constitution path.

**8. Later refinement.** Fractional/indirect sets (direct 1, indirect 0.5) if the ledger warrants
it; not v1.

**9. Cross-group quota compensation (9a preview and 9b application implemented).**
- 9a **implemented 2026-10-26**: one optional non-essential slot per session type, candidates
  `dumbbell_bench_press` (push) and `rdl` (hinge), similarity weights and a read-only preview.
- 9b **implemented 2026-10-26**: with `apply: true` and the budget on, the engine adds the
  selected slot through `build_item`, cites `MOD-VOL-004`, and refuses if the load is not
  executable. Constitution 1.17.0.
- 9c **design agreed 2026-10-26, not implemented**: total full → skip/short; lift-specific
  full with total under → a distinct multi-slot `volume_fill` with the original type recorded;
  automatic after the opt-in, with confirmation at competition/peak; `MOD-VOL-005`.
- `reduce` is step 2b, not here; step 9 only handles cross-group compensation and `drop`.

## 11. Tests (for the implementation phase)

- target arithmetic per pattern; the 114/2 cycle average.
- normal week (56/58) inside tolerance → no change.
- missed session → top-up to cap; unreachable warning with the feasibility numbers.
- short session → remaining; long session → trim; floors respected; essentials never trimmed.
- readiness/deload/spinal/constraint removals lower the effective target and are not re-added.
- minimum session default is debt; config can exempt it from the target.
- symptom flare suppresses top-up for that pattern.
- MRV cap still wins after top-up; spinal trim still wins.
- time cap binds before the set cap.
- no cross-week debt; ISO-week boundary.
- forecast allocation across projected dates.
- config validation: cap < target feasibility, negative tolerance, unknown pattern.
- registry: default profile reproduces today's prescriptions; disabling each module changes only
  its cited outputs; hard-safety waiver required.

## 12. Decisions (accepted 2026-10-26; steps 1–2b, 9a and 9b implemented; steps 3–8 and 9c not)

| # | decision | accepted choice |
|---|---|---|
| 1 | Target source | cycle average (51 targeted + 6 untargeted = 57/week) |
| 2 | Session cap | 30 sets total plus the per-pattern table and the time cap |
| 3 | Automation | automatic trim + automatic accessory top-up, phased |
| 4 | Exemptions | safety/recovery removals lower the **effective weekly target**, not the session cap; missed sessions, early ends and minimum sessions are debt by default |
| 5 | Week boundary | ISO week, no cross-week debt |
| 6 | Main-lift top-ups | opt-in only |
| 7 | New rule | `MOD-VOL-003` **declared in constitution 1.16.0** (approved 2026-10-26, `DEC-VOLUME-07`; amended for reduce in 1.16.0, `DEC-VOLUME-11`); runs only when the profile enables it |
| 8 | Settings layer | budget as a config module first, registry and profiles later |
| 9 | Hard-safety toggles | constraints, injury ceilings and load validation stay hard; the spinal cap is **guarded** (warning + double confirmation), not a plain switch |
| 10 | Future-session basis | remaining planned sessions projected at template sets, recomputed each build |
| 11 | Spinal load in Settings | **guarded**: warning + double confirmation + reason + append-only profile; `PRG-SPINE-001` stays in force and is parameterised, not disabled |
| 12 | Cross-group compensation | confirmed as a later **volume-first mode**: per-group quotas, inverse-similarity weights, `main_lift_policy` preserve by default, `drop` opt-in; parameters and evidence still open |
| 13 | Strength-preserving default | main lifts stay at template sets even when the group quota is full; `main_lift_policy` is an append-only `athlete_profile` field (`preserve` default, `reduce`/`drop` opt-in); compensation is accessory-only under `preserve`; "no squats" is `drop` |
| 14 | Compensation parameters | one optional non-essential compensation slot per session type; candidates `dumbbell_bench_press` (push) and `rdl` (hinge), executable load only; weights squat↔hinge 0.7, squat↔bench 0.2, hinge↔bench 0.2, push↔pull 0.3, floor 0.1; all sets count; main lifts stay in `preserve`; main-lift top-up opt-in; `MOD-VOL-004` for slot replacement |
| 15 | Frequency above three | the budget supports 4+ by spreading the same 57-set target, or an explicit higher target; the programme/forecast stays 1–3 and four-plus is manual single-session only; a fourth heavy full-body day is not assumed |
| 16 | Reduce/drop timing | `reduce` is **step 2b, implemented 2026-10-26**: it trims a filled group's main lift to the configured floor, keeps the session type, and disables top-up; `drop` remains **step 9c**, after the 9a compensation slot pool, because it removes and relabels a main lift; both are opt-in via `main_lift_policy` |
| 17 | All parameters config-backed | total/per-group targets, daily/session total and per-group caps, tolerance/band minimum, trim/top-up switches, accessory floor and per-item top-up ceiling, set seconds/warm-up/time cap, and the reduce floor all live in `config/volume.v1.yaml`; the profile only adds on/off, policy and a tightening `max_session_minutes` (`DEC-VOLUME-12`) |
| 18 | 9a/9b compensation | 9a preview: slot pool, similarity weights and `compensation` report. 9b application: with `apply: true` and the budget on, one non-essential slot is added with a real load (`MOD-VOL-004`, constitution 1.17.0); no history refuses. 9c is `drop` |
| 19 | 9b application | one slot added through `build_item`; executable load required; refusal is a warning, not a guessed load; `MOD-VOL-004`; all later caps still run (`DEC-VOLUME-14`) |
| 20 | Missing compensation load | retry with the e1RM basis, then ask the athlete for an e1RM (UI prompt/CLI) and rebuild; refuse only if still unusable (`DEC-VOLUME-15`) |
| 21 | 9c drop design | two branches: total at/above the high band → technique-focused session; below the high band with a filled group → first-class multi-slot `volume_fill` filling into the high band. `volume_fill`/`technique` count as sessions with distinct exposure semantics; original type/reason recorded; no silent relabel. Automatic after `main_lift_policy: drop` opt-in; confirm 7 days before competition (config); `MOD-VOL-005`; not implemented (`DEC-VOLUME-16/17`) |
| 22 | 9b high-band guard | 9b stays additive (source accessory remains) but stops at the weekly high tolerance band; status `weekly_full` and no added slot when already there (`DEC-VOLUME-17`) |

Step 1 is implemented read-only (the module, the `volume_exemption` table and the config
section). Step 2 is implemented behind the off-by-default profile flag, step 2b adds the opt-in
`reduce` mode, and 9b adds the opt-in compensation slot: `MOD-VOL-003`/`MOD-VOL-004` are in
constitution 1.17.0, `_apply_volume_budget` runs after continuity, and safety cuts are recorded
in `volume_exemption`. Steps 3–8 and 9c (`drop`) remain unimplemented. The rationale and the rejected
alternatives are in §3–§7; the decision records are `DEC-VOLUME-06`, `DEC-VOLUME-07` and
`DEC-SPINE-06`.

## 13. Assumptions

- **ASSUMPTION-40** — the default weekly target is the six-session template average (51 targeted
  + 6 untargeted sets), not a landmark value. It keeps a normal week unchanged.
- **ASSUMPTION-41** — the 30-set total cap and the per-pattern caps are fatigue-management
  choices, not measured maxima; the time cap remains the practical limit.
- **ASSUMPTION-42** — safety and recovery removals lower the effective weekly target; they do
  not lower the session cap or the MRV ceiling. Only scheduling shortfalls are reallocated.
- **ASSUMPTION-43** — the budget uses the ISO week and creates no cross-week debt.
- **ASSUMPTION-44** — automatic top-ups are accessory-only; main-lift top-ups are opt-in.
- **ASSUMPTION-45** — future sessions are projected at template sets; the projection is
  recomputed on every build and is not a stored plan.
- **ASSUMPTION-46** — the Settings range for the spinal cap (0–12) and costs (0–5) is a
  guardrail, not a measured bound; values outside it require a config edit.

- **ASSUMPTION-47** — cross-group compensation weights are inverse-similarity heuristics (squat
  and hinge similar, squat and bench less so) with a floor, not measured set equivalence; the
  mode is opt-in and `preserve` is the default.
- **ASSUMPTION-48** — the compensation slot pool (`dumbbell_bench_press`, `rdl`) and the
  similarity matrix are design heuristics, not measured equivalence; the slot is non-essential
  and the main lift stays in `preserve`.
- **ASSUMPTION-49** — the reduce floor default (three sets) is a coaching assumption,
  configurable, not a measured minimum; the main lift stays in the session.

## 14. Evidence

- **Weekly volume is the dose.** The 2025 meta-regression (67 studies, 2,058 participants) found
  volume raises hypertrophy and strength with diminishing returns, more pronounced for strength:
  https://doi.org/10.1007/s40279-025-02344-w
- **The same weekly sets in one vs three sessions.** Calzavara 2026 (18 trained men, 6 weeks,
  3 sets/exercise/week at 80% to failure) found similar hypertrophy and higher volume load in the
  distributed group (+58% squat, +76% leg press), with strength differences only directional
  (p ≈ 0.07): https://doi.org/10.1519/JSC.0000000000005665
  This is the closest direct support for compressing a weekly target into fewer sessions, but it
  used a small weekly dose, not 57 sets.
- **Frequency mostly distributes volume; once a week per muscle is the weak end.** Schoenfeld
  2016 (2× > 1× for hypertrophy at equal volume; 3× vs 2× unresolved):
  https://doi.org/10.1007/s40279-016-0543-8 ; Grgic 2018 (no strength effect when volume is
  equated): https://doi.org/10.1007/s40279-018-0872-x
- **Acute fatigue rises with per-session volume.** The 2025 review of 51 studies found total
  volume, proximity to failure and set duration are the main determinants of performance
  impairment and perceived fatigue: https://doi.org/10.1519/JSC.0000000000005194
- **Autoregulation is not clearly superior.** Load-based autoregulation trials have not beaten a
  fixed programme; there is no volume-autoregulation trial:
  https://doi.org/10.1186/s40798-021-00404-9
- **No trial of make-up volume.** Searches returned coaching articles and detraining studies, not
  interventions. The cap, tolerance, exemption list and allocation order are therefore design
  choices, not findings. They are recorded as ASSUMPTION-40–49.

### Limits of the evidence

- Calzavara 2026 is 18 trained men over 6 weeks with 3 sets/exercise/week; it supports compressing
  a small weekly dose, not 57 sets into one session.
- The 2025 meta-regression is study-level and observational; the fractional volume quantification
  is a modelling choice, and its frequency results are compatible with small effects.
- There is **no trial** of a per-session set cap, of make-up volume, or of volume autoregulation.
  The 30-set cap, the ±10% band, the exemption list and the allocation order are design choices
  (`ASSUMPTION-40`–`49`), not findings.
- The app's own W6 audit found the readiness counterfactual is not identifiable retrospectively
  ([READINESS-AUDIT.md](READINESS-AUDIT.md)); the budget is a programming heuristic, and the
  phased rollout (display → opt-in → automatic) is the safeguard.
- **No trial of cross-group set equivalence.** The similarity weights for the later
  volume-first mode are a heuristic (`ASSUMPTION-47`), and strength is specific: bench sets do
  not replace squat sets for squat strength.

## Related

- [FREQUENCY-AND-VOLUME.md](FREQUENCY-AND-VOLUME.md) — the reproduced behaviour and the options
- [VOLUME-MANAGEMENT.md](VOLUME-MANAGEMENT.md) — ledger, landmarks, MRV cap, under-MEV
- [MINIMUM-SESSION.md](MINIMUM-SESSION.md) — the explicit short-session path
- [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md) Q26
- [LIMITATIONS-REGISTER.md](LIMITATIONS-REGISTER.md) LIM-51
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
