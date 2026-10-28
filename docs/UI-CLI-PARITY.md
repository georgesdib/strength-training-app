# UI ↔ CLI PARITY

**Status:** current audit, 2026-10-23.
**Standard:** a capability has first-class parity when the UI calls the same core function as the
CLI. The in-browser Terminal was removed on 2026-10-28 (`DEC-WEB-02`), so the fallback for an
uncovered action is now the CLI itself; that is not parity either.

---

## 1. Fixed gap: UI prescriptions are now persisted

Before this change, `/api/prescribe` returned a plan but wrote no `prescription` row. The UI
could start a workout from that plan, but the artifact only existed in the workout snapshot.

Now, when the athlete **starts a workout from a UI prescription**:

1. the plan is written as a `prescription` row and its `prescription_item` rows;
2. `MOD-*` provenance is written to `prescription_modifier`;
3. the workout is inserted with that `prescription_id`;
4. all of this happens in one transaction;
5. a failed start (including an active workout) rolls everything back.

`/api/prescribe` remains a **read-only preview**. Repeated previews do not create duplicate
prescriptions. The artifact is created on commitment, not on preview.

This is deliberate: the UI is a planning surface until the athlete starts the workout.

## 2. First-class parity

| Area | CLI | UI | Notes |
|---|---|---|---|
| Import CSVs | `import` | Import page | same importer |
| Readiness entry | `readiness set` | Readiness form | same merge/validation |
| Readiness presets/context | `readiness preset/context` | Readiness page | same service |
| Readiness override/settings/volume | `readiness ...` | Readiness page | same config/service |
| Readiness calibration/shadow/feedback | `readiness ...` | Readiness/Outcomes | same reports |
| Workout start/perform | CLI subset | Workout page | UI-first start; both write the same workout |
| Workout sets/update/remove/end/abandon/import | `workout ...` | Workout page | same workout functions |
| Review one session | `review` | Review page | same marks/rubric |
| Post-lift form rating | no CLI command | Workout + History edit | UI-only capture; same rubric item from stored ratings |
| Minimum effective session | `run --minimum-session` | Prescribe controls | same volume-only core; `MOD-MIN-001` |
| Technique throttle | `run --technique-throttle [--throttle-pattern]` | Prescribe controls | same load/RIR core; `MOD-TECH-001` |
| Programme forecast | `programme` | Programme page | same forecast |
| Outcomes | `outcomes` | Outcomes page | same report |
| Readiness feedback | `readiness feedback` | Outcomes panel | same report; workout snapshots included |
| Cardio | `cardio` | Cardio page | same summary/write |
| Measurements | `measure` | Measures page | same metric service |
| Exercise catalogue | `exercise list/set` | Exercises page | same catalogue/admin |
| Athlete profile/constraints/suitability | `state` | Athlete forms | individual edits only; see gaps |
| e1RM set/list | `e1rm set/list` | Athlete page, Exercises tab, post-workout panel | same overrides |
| Strength test recording | `test` | Athlete page, post-workout panel | same exposure/test path |
| Symptom logging | `symptom` | Athlete page | same region validation |
| Exposure logging/status | `exposure ...` | Athlete page | same guard |
| Exercise selection | `select` | Prescribe panel | same selection engine |
| Retrospective validation | `validate` | Prescribe panel | same report |
| Fatigue model | `fatigue` | Prescribe panel | same shadow report |
| High-intensity exposure | `exposure` | Athlete page | same service |

## 3. Documented non-parity

These are known and intentional or still open.

| Gap | Current state | Decision |
|---|---|---|
| UI prescribe preview artifact | `/api/prescribe` is read-only until workout start | intentional; start commits the artifact |
| CLI `run --propose` / `--llm` narrative | no UI proposal/chat surface | documented CLI-only (`DEC-LLM-*` / WEB-UI limitations) |
| `review --pending` bulk queue | UI reviews a selected recent session; no batch queue | open; CLI only since `DEC-WEB-02` |
| `state --import` YAML | UI has individual state forms only | open; CLI only since `DEC-WEB-02` |
| `e1rm calibrate --window-days` | UI shows the calibration table, no window control | partial |
| `e1rm tests-needed --window-days` | UI shows the same coverage table with the default window | partial |
| `test --status` standalone cadence | cadence shown in prescription notes | partial |
| `symptom --show` raw history | UI shows injury signal/current tables | partial |
| `volume --weeks/--date` | UI panel uses the default 4-week window | partial |
| Volume budget | `volume --budget`; `state --volume-budget/--main-lift-policy`; `run --drop-confirm` | Prescribe **Volume budget** panel; Athlete profile fields; compensation preview/application; Settings **Drop / volume fill**; `GET/POST /api/settings/drop` | full |
| Settings profile (step 5) | `settings profile show/set/unset/reset --guard-confirm --reason` | Settings **Settings profile** editor; `GET/POST /api/settings/profile` | full |
| Modalities (5b/5c) | `settings modalities list/show/set` with guard flags | Settings **Modules**; `GET/POST /api/modalities`; profile factor editor | full |
| `exposure ratio` | Prescribe **Exposure ratio** panel (same `compute`) | full |
| `select --fatigue` | Exercise selection panel **Fatigue-informed suggestion** block | full |
| `exercise demands set/clear` | Exercises details `Demand profile` rating form | full |
| `continuity --date` | UI panel uses the default date | partial |
| `fatigue --date` | UI panel uses the default date | partial |
| `validate --max-dates` | UI button uses 12 dates | partial |
| `block --force` reset | profile/block form exists; explicit reset path is not first-class | partial |
| `web` command | the UI is the web server | CLI-only by definition |

## 4. UI-only capabilities

- Outcomes page (strength + longevity + data coverage).
- Readiness feedback panel.
- Quick readiness presets/context UI.

These are UI surfaces over core functions; they do not violate parity.

## 5. Rules for future features

1. Implement the decision in Python once.
2. Expose it in the CLI and UI where practicable.
3. The UI must call the same function, never reimplement the arithmetic.
4. If a capability is reasonably UI-inappropriate (bulk YAML import, host operation), record
   the exception here and in `docs/WEB-UI.md`.
5. A failed UI write must not leave a partial prescription, workout or provenance row.

## 6. Relevance to D

Minimum-effective-session mode must:

- use one shared decision function;
- persist `MOD-MIN-001` through the same `prescription_modifier` path;
- appear in the frozen workout plan;
- be exposed in both the UI and CLI;
- be measurable through planned-versus-actual sets in readiness/session feedback.

The UI prescription-persistence gap is now fixed for the commitment path. The remaining gaps
above do not block D.

## Related

- **UI surface:** [UI-MAP.md](UI-MAP.md)
- **Evidence:** [WEB-UI.md](WEB-UI.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
