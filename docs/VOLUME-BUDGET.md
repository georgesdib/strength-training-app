# Volume budget guide

This is the operator guide for the **Volume budget** panel in Settings. It explains what each
control changes, how saving works, and which values remain in the athlete State form rather
than this panel. The technical specification and formulas remain in
[`VOLUME-MODULATION-PLAN.md`](VOLUME-MODULATION-PLAN.md).

## 1. What the budget does

The volume budget compares the week's planned and completed working sets with a configured
weekly target. Within a tolerance band it changes nothing. Above the band it trims non-essential
accessories; below it it may add accessory sets. A separate session cap limits how much can be
put into one workout. These are coaching guardrails, not measured individual thresholds.

The budget is active only when the athlete profile enables it. Its main-lift policy
(`preserve`, `reduce`, `drop`) is also athlete state. Those controls stay in **State → Edit
profile**; the Volume budget panel shows their effective values and links back to State.

## 2. Where to edit

Use **Settings → Volume budget**.

- Values are saved as an append-only settings-profile version in SQLite.
- The precedence is **profile override → local overlay → committed config → code default**.
- The committed file, `config/volume.v1.yaml`, holds the engineering defaults and is not
  edited by this panel.
- `config/volume.local.yaml` is a legacy local overlay. If present, the panel warns that it
  still supplies values the profile does not override. Profile values win.
- Saving does not rewrite either YAML file and does not change an older profile version.

Every save needs a **reason** and an **effective date**. The date defaults to today; a future
date is allowed. One prescription can therefore keep using the old values after a future-dated
profile version is written.

Changing weekly targets, session caps, the MRV cap or landmarks also requires typing
`VOLUME`. That is deliberate: these changes move the dose or the safety boundary.

## 3. Targets and caps

| control | what it changes |
|---|---|
| weekly target per movement group | planned hard sets for one week |
| effective target per movement group | target used when set accounting is `effective` |
| session total cap | maximum planned working sets in one session |
| per-pattern session cap | maximum planned sets for one movement group in a session |
| tolerance | deadband around the weekly target; a per-group band is at least `band_min` |
| band minimum | minimum per-group tolerance band in sets |
| main-lift floor | minimum main-lift sets kept by reduce mode |
| accessory floor | minimum accessory sets kept when trimming |
| top-up maximum | maximum sets added to one item |
| trim above target / top up below target | enable each direction of the budget |
| seconds per set, warm-up allowance, session time cap | planning-time estimate inputs |

The weekly and effective totals shown above the table are **derived** from the rows; they are
not separate editable values. The server rejects a total that no longer equals the sum of its
per-group targets.

The **session total cap** is different: it is an independent configured limit for the whole
session, not the sum of the per-pattern caps. The panel shows that sum as a diagnostic only,
because a session does not contain every movement pattern and the two limits serve different
purposes.

## 4. Volume policy

| control | what it changes |
|---|---|
| apply MRV cap | trim accessories when a pattern is already above MRV |
| ledger coverage | whether a week with no sets is unknown or a real zero |
| set accounting | raw hard sets, or direct plus configured indirect weight |
| under-MEV progression | add one accessory set after persistent under-MEV weeks |
| under-MEV weeks / add sets / per-item max | the under-MEV rule's timing and ceiling |
| MEV / MAV / MRV landmarks | the per-pattern coaching bands used by the ledger |

MRV cap and landmark changes are treated as high-impact and need `VOLUME`.

## 5. Drop / volume fill

The drop branch replaces a filled session with a technique session or a smaller `volume_fill`
session. It is active only when the budget is enabled and the athlete's main-lift policy is
`drop`.

| control | what it changes |
|---|---|
| enable drop | allow the drop branch |
| competition confirm days | how many days before a competition the per-session confirmation is required |
| max slots per group | maximum fill slots added for one movement group |
| technique minutes | time cap of a technique session |
| candidate pool JSON | exercises, sets, reps, RIR, rest and load source for fill slots |

The Prescribe **Confirm drop in competition window** checkbox appears only when this policy is
active and the selected date is inside the competition window. Outside it the control is hidden.

The high band is derived from the weekly target and tolerance; it is not a separate setting.

## 6. Compensation

Compensation is an advanced cross-group transfer. The preview can suggest moving volume from a
filled group to an under-target receiver; application is a separate switch. The similarity map
and candidate slots are edited as validated JSON because they are a structured candidate pool,
not a small set of scalar controls.

## 7. Common validation errors

- A weekly total no longer equals the sum of its per-group targets.
- A target or session cap is negative.
- A session cap omits a managed movement group or names an unknown one.
- A floor is below one set, or the accessory floor exceeds the top-up maximum.
- Tolerance is outside 0–1, or a time input is not positive.
- A drop or compensation candidate uses an unknown exercise group, load source or session type.
- A high-impact change is missing the typed `VOLUME` confirmation.
- The reason is blank.

Fix the reported field and save again. A failed save writes no profile version.

## 8. What stays in State

These are athlete decisions, not settings-profile defaults:

- volume budget on/off
- main-lift policy: `preserve`, `reduce` or `drop`
- sessions per week target
- maximum session minutes

The Volume budget panel shows their current values. Change them in **State → Edit profile**.

## Related

- **Technical plan:** [VOLUME-MODULATION-PLAN.md](VOLUME-MODULATION-PLAN.md)
- **Volume landmarks:** [VOLUME-MANAGEMENT.md](VOLUME-MANAGEMENT.md)
- **Web UI and API:** [WEB-UI.md](WEB-UI.md)
- **Data model:** [DATA-MODEL.md](DATA-MODEL.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [../ROADMAP.md](../ROADMAP.md)
