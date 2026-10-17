# V0 SCOPE — the smallest end-to-end slice

## 1. The slice

One command:

```bash
python -m strength_coach.cli run --date 2025-06-10 --llm off   # any date in your export
```

that:

1. ingests both CSVs,
2. cleans them under the documented sentinel policy,
3. reconstructs sessions,
4. calibrates VBT from history **as of that date** (no look-ahead),
5. produces a **critique** of the most recent session with rubric scores,
6. produces a **prescription** for the next Day B session,
7. writes an append-only record of both,
8. and prints a rationale where every load cites a rule id or a data point.

**Why Day B for v0:** it is the cleanest single-day template (trap-bar deadlift +
close-grip/pause bench), it is the only day with a per-exercise RIR override (trap bar
3–4), and it contains **no direct erector work**, which sidesteps the unanchored erector
ramp (PRG-EREC-001) that is blocked on Q5. Day A/C would drag in unresolved-day-identity
and erector-ramp questions on day one.

## 2. In scope

| Area | v0 includes |
|---|---|
| Ingest | both CSVs, raw preserved, quarantine of null-date rows, `source_row` traceability |
| Cleaning | per-field zero sentinels, unit normalisation, `reps_unit` (reps vs seconds), typo flags, **no deduplication** (DQ-DUP-01) |
| Sessions | one per date, workout label retained, `POSSIBLE_DOUBLE_SESSION` flag |
| Load | `load_basis` resolution (DQ-BW-01), total vs external load |
| Features | tonnage (external only), e1RM with method+quality tags, per-lift baseline, weekly spinal cost, session frequency |
| VBT | calibration with the L0–L4 fallback ladder, `calibration_id` versioning; velocity targets **or an explicit `uncalibrated`** |
| Rules | load `config/rules/programme.v1.yaml`; evaluate PRG-RIR-001, PRG-DP-001, PRG-SCHED-001, PRG-SPINE-001; PRG-EREC-001 returns `unknown` |
| Prescribe | deterministic Day B prescription: per item sets/reps/load/RIR/rest/essential/rationale refs; fatigue modifier MOD-FAT-001 |
| Critique | rubric items that are measurable now: RIR adherence, progression adherence, weekly spinal cost, missing essential work, redundancy. Each with score + evidence refs |
| Policy | veto/downgrade with fallback prescription |
| Store | SQLite, append-only, migrations |
| Trace | run + run_event, replayable |
| LLM | **interface only**, plus `NullLLM`. One optional narrative call behind `--llm on`; the run must be identical in structure with it off |
| Tests | unit + integration + one golden prescription per day type present in the window |

## 3. Explicitly out of scope for v0

Each of these is deferred *with a reason*, not forgotten:

| Deferred | Why |
|---|---|
| RAG / vector store | rules are cited by ID; exact lookup is better than semantic search here. RAG is only for programme prose, later |
| Critique/prescription agents (real LLM) | the deterministic core must be proven first; `NullLLM` exercises the failure path from day one |
| Days A and C | blocked by the SSB question (H1) and the erector ramp anchor (Q5) |
| Erector dose ramp (PRG-EREC-001) | returns `unknown` — no symptom input, no anchored week 1 |
| Velocity-loss scoring | not computable from set means (SANITY-CHECKS §C); v0 reports `velocity_decay_proxy` with `measurable: false` |
| Session-duration scoring | no timestamps exist (DQ-SESSION-01) |
| Power-work module | `Avg_power` absent on 66% of sets; the power rule cannot be scored |
| ACWR | contested; advisory only, and not needed for a single-day prescription |
| Bevel / HRV / RHR / grip strength | normalisation layer is designed but there is no data yet |
| Rotation scoring | needs the app-vs-self provenance decision (see SANITY-CHECKS §B) |
| Labelled 10-session eval set | v0.1; v0 ships the harness skeleton and 3 hand-marked sessions |
| UI | explicitly deferred by the brief |

## 4. Acceptance criteria

v0 is done when all of these are true:

1. `python -m pytest` passes; every domain function in `utils` and `domain` is unit-tested.
2. `python tools/profile_data.py` reproduces `docs/EVIDENCE.md` exactly.
3. `python tools/baseline.py --as-of <date>` reproduces the baseline for that date
   (the quantitative baseline lives in the private docs).
4. A prescription for the chosen date is **executable**: every load is a positive multiple of a
   plausible increment, every main-lift RIR is inside its window, no two erector exposures
   coexist, weekly spinal cost is inside the cap.
5. Deleting the LLM entirely (`--llm off` or a raising client) produces the same
   prescription, differing only in narrative fields.
6. Re-running the same `run` is idempotent in content and appends no duplicate artifacts.
7. The critique's rubric includes the three known failure patterns from this history:
   grinding sets (RIR 0–1 on primary compounds), hinge/erector stacking, and exercise
   rotation — with rotation split by workout label.
8. Every numeric rationale field references a resolvable rule ID or data-point ID.

## 5. Rough effort estimate

Given the utils/domain layer already exists and is tested:

| Piece | estimate |
|---|---|
| ingest + clean + quarantine | 1 day |
| session reconstruction | 0.5 day |
| store + migrations + repositories | 1 day |
| features (tonnage, e1RM, spinal, frequency) | 0.5 day (mostly written in `features.baseline`) |
| VBT calibration + ladder | 1 day |
| rules loader + registry + policy | 1 day |
| prescription engine (Day B) + fallback | 1 day |
| critique rubric (deterministic) | 1 day |
| CLI + trace | 0.5 day |
| tests + golden + fixes | 1.5 day |
| **total** | **~9 working days** |

The estimate assumes the 8 open questions are answered around the time ingest lands. Q1
(RIR semantics) and Q2 (load basis) block the prescription engine specifically, because
both change the load a single rep-resolution away.
