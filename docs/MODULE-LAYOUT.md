# MODULE LAYOUT AND TEST STRATEGY

## 1. File layout

`[x]` exists today, `[ ]` planned. Nothing marked `[ ]` should be built before approval.

```
pyproject.toml                       [x] deps, pytest config, ruff
AGENTS.md                            [x] instructions for contributors/agents
README.md                            [x] overview + quickstart
config/
  exercises/taxonomy.v1.yaml         [x] exercise identity + properties
  rules/programme.v1.yaml            [x] the constitution, 5 encoded rules + modifiers
  calibration/overrides.v1.yaml      [ ] per-lift manual velocity overrides
  templates/days.v1.yaml             [ ] Day A/B/C templates
  thresholds.v1.yaml                 [ ] increments, caps, bands
data/raw/training_log.csv            [x] immutable source
data/raw/readiness.csv               [x] immutable source
data/coach.db                        [ ] SQLite store
docs/*.md                            [x] the proposal + evidence
strength_coach/
  utils/                             [x] pure shared helpers (permanent)
    paths.py io_utils.py dates.py numeric.py stats.py exercises.py reporting.py
  domain/                            [x] pure domain arithmetic
    e1rm.py                          [x] Epley + RIR-adjusted, rep caps
    load.py                          [x] load-basis resolution, rounding
    rir.py                           [ ] RIR normalisation & sentinel policy
    velocity.py                      [ ] presence, decay proxy
    progression.py                   [ ] double-progression decision
    fatigue.py                       [ ] readiness composite + modifiers
    spinal.py                        [ ] exposure counting, erector dose
  ingest/                            [ ]
    readers.py clean.py sessions.py readiness.py quarantine.py
  store/                             [ ]
    schema.sql migrations/ db.py repositories.py
  features/                          [x] partially
    baseline.py                      [x] per-lift/session baseline (used by critique)
    session.py weekly.py vbt_calibration.py
  rules/                             [ ]
    loader.py registry.py policy.py rag.py
  prescribe/                         [ ]
    templates.py engine.py fallback.py
  critique/                          [ ]
    facts.py rubric.py
  agents/                            [ ]
    llm.py critique_agent.py prescription_agent.py tools.py
  eval/                              [ ]
    backtest.py labelled_rubric.yaml scenarios/
  cli.py                             [ ]
tools/
  profile_data.py                    [x] regenerates docs/EVIDENCE.md
  baseline.py                        [x] regenerates docs/BASELINE.md numbers
tests/
  conftest.py                        [x] fixtures + raw-CSV availability guard
  test_dates.py test_numeric.py      [x] sentinels
  test_stats.py                      [x] robust stats
  test_exercises.py                  [x] taxonomy + recorded decisions
  test_io_utils.py                   [x] raw reading fidelity
  test_e1rm.py test_load.py          [x] domain arithmetic
  test_clean.py test_sessions.py     [ ] planned with ingest
  test_rules.py test_policy.py       [ ] planned with rules
  test_prescribe.py                  [ ] planned with prescription engine
  test_critique.py                   [ ] planned with rubric
  golden/                            [ ] snapshot prescriptions
```

## 2. Where code is reused

The rule from the brief: **if a calculation is needed in more than one place, it lives in
one tested module and is imported.** Concretely:

| Calculation | Single home | Used by |
|---|---|---|
| date parsing + null tokens | `utils.dates` | ingest, baseline, every window function |
| numeric coercion + zero sentinels | `utils.numeric` | ingest, baseline, readiness normalisation |
| robust median/MAD/band | `utils.stats` | VBT calibration, e1RM series, readiness composite |
| exercise identity + properties | `utils.exercises` | ingest, features, rules, prescription, critique, tools |
| e1RM (Epley/RIR/rep caps) | `domain.e1rm` | features.baseline, critique, prescription rationale |
| load-basis + rounding | `domain.load` | ingest.clean, prescription engine, critique |
| RIR window & suspect values | `domain.rir` | rules registry, critique rubric, features |
| velocity presence/decay | `domain.velocity` | features.vbt_calibration, critique |
| double-progression decision | `domain.progression` | prescription engine, critique |
| weekly spinal cost | `domain.spinal` | features.weekly, rules.PRG-SPINE-001, critique |

Note the deliberate consequence: **the critique and the prescription call the same
progression and spinal functions.** They cannot disagree about what the rule says.

## 3. Test strategy

Five layers, cheapest first.

1. **Unit tests on pure functions** — every function in `utils` and `domain`. Table-driven,
   no I/O. Assert the *domain reason*, not just the output: e.g. "RIR 0 is preserved"
   rather than "returns 0".
2. **Property tests** (planned, `hypothesis`) — rounding is idempotent and never rounds up;
   `robust_band(low <= median <= high)`; e1RM is monotonic in load and in reps.
3. **Integration tests against the real CSVs** — marked `@pytest.mark.integration`. These
   assert structural invariants: every exercise name resolves, null-date rows are
   quarantined, `velocity == 0` never coexists with measured `TUT`, and clean VBT counts
   per lift stay stable. A silent change in
   cleaning becomes a test failure.
4. **Golden/snapshot tests** — full prescriptions for a handful of historical dates,
   stored as YAML. Any change to the engine that alters a prescribed load shows up as a
   diff to be reviewed, not a surprise later.
5. **Backtest harness** — replays a historical week using only data available up to that
   day, then checks executability and rubric agreement against a hand-labelled set
   (see `docs/V0-SCOPE.md` and the eval design in `docs/ARCHITECTURE.md`).

### Non-obvious tests that already exist because they caught real bugs

- `test_rir_zero_is_preserved` — reusing the *date* null tokens for numerics silently
  erased genuine `RIR = 0` observations.
- `test_leg_curls_are_knee_flexion_not_biceps` — regex ordering sent `Lying Leg Curls` to the biceps family.
- `test_historical_hyperextension_is_not_back_extension` — pins DEC-BACKEXT-01, which
  would otherwise be quietly reverted by a well-meaning "normalisation".
- `test_zero_dispersion_collapses_without_floor` — documents the MAD-collapse hazard that
  the VBT module must guard against.

### What is deliberately not tested

- The LLM's prose. It is validated structurally (every citation must resolve, every number
  must match a tool result), never by string comparison.
- Anything requiring a live network call. The LLM client is injected; tests use a fake.
