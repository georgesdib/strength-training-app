# ROADMAP

The resume point for this project. If you are picking this up cold — human or agent — read
this file first, then [`AGENTS.md`](AGENTS.md) for the rules of the codebase.


Last updated: 2026-11-18 · **v1.7.1 released (longevity correctness, privacy and integration)** · version `1.7.1`


---

## 1. How to resume

```bash
cd strength-training-app
.venv/bin/python -m pytest            # default suite: 2315 tests (2026-11-18 run)
.venv/bin/python tools/profile_data.py   # data profile (needs data/raw/)
.venv/bin/python tools/baseline.py       # strength baseline
```

Then read, in order:

1. [`USER-GUIDE.md`](USER-GUIDE.md) — how to use what exists
2. **this file** — where we are and what is next
3. [`docs/DECISIONS.md`](docs/DECISIONS.md) — decisions that are expensive to reverse
4. [`docs/OPEN-QUESTIONS.md`](docs/OPEN-QUESTIONS.md) — what is still ambiguous, with defaults
5. [`docs/V0-SCOPE.md`](docs/V0-SCOPE.md) — the agreed scope and its exclusions
6. [`AGENTS.md`](AGENTS.md) — invariants, layering, definition of done

**Resume rule:** update the status table below in the same commit as any phase change. If the
table disagrees with the code, the table is wrong — fix it before adding features.

## 2. Status

| # | Phase | Status | Artifacts |
|---|---|---|---|
| 0 | Design + approval | **done** | `docs/ARCHITECTURE.md`, `DATA-MODEL.md`, `DATA-QUALITY.md`, `RULES-FORMAT.md`, `VBT-CALIBRATION.md`, `docs/archive/MODULE-LAYOUT.md`, `V0-SCOPE.md`, `OPEN-QUESTIONS.md`, `SANITY-CHECKS.md`, `TRAINING-GUIDELINES.md` |
| 1 | Ingest (clean + sessions) | **done** | `ingest/clean.py`, `ingest/sessions.py`, `config/templates/inference.v1.yaml` |
| 2 | Derived features + VBT calibration | **done** | `features/derived.py`, `features/baseline.py`, `features/vbt_calibration.py`, `domain/e1rm.py`, `domain/load.py`, `domain/rir.py` |
| 3 | Store (SQLite, append-only) | **done** | `store/migrations/0001_initial.sql`, `store/db.py`, `store/repositories.py`, `store/importer.py` |
| 4 | Rules loader + policy engine | **done** | `rules/loader.py`, `registry.py`, `context.py`, `policy.py`; predicates for all five rules |
| 5 | Prescription engine (four session types) + deterministic fallback | **done** | `prescribe/templates.py`, `config.py`, `loads.py`, `engine.py`, `fallback.py`; `config/thresholds.v1.yaml` |
| 5.5 | Athlete state — DATA-MODEL §11 tables | **done** | `store/migrations/0003_athlete_state.sql`, `prescribe/constraints.py`, `cli state` / `cli block`; hard constraints veto |
| 6 | Critique rubric + trace | **done, since retired** | `critique/facts.py` (facts only) and `trace/run.py` remain; the scoring rubric was removed 2026-11-13 (`DEC-EVAL-09`), and historical `critique`/`rubric_score` rows stay readable |
| 7 | LLM layer (narrative only) | **done** | `agents/client.py`, `config.py`, `narrative.py`; `config/llm.example.toml`, `tools/llm_check.py` |
| 8 | Backtest harness + labelled eval set | **done, since retired** | the harness, labelled-set format and mark loader were removed 2026-11-13 (`DEC-EVAL-09`); `eval/fatigue_diagnostics.py` remains |
| 9 | CLI (`run` / `import` / reports) | **done** | `cli.py`; prescriptions persisted; `review` and `calibrate` were retired 2026-11-13 (`DEC-EVAL-09`), and marks stay readable through the read-only review sheet |
| v0.2 | Input flexibility + programme view | **done** | readiness entry/score/devices/settings + gate (§4.1/4.9), continuity (§4.6), injury signal (§4.7), local web UI with import/state editing/Programme/Cardio/Terminal/calibration (§4.10/4.11), cardio capture + weekly summary (§4.13), labelled set (§4.14), session RPE/length, recent stress, per-lift readiness, e1RM calibration + bounded correction + age decay |
| v0.3 | Strength/data depth | **done** | manual logging via live workout mode (§4.2/§4.21, closed), import adapters closed (§4.3), learned readiness weights evaluated and closed (§4.9), LLM proposal view closed as CLI-only (§4.11), continuity calibration (§4.12; calibrated factor rejected, fixed fallback), exercise selection apply + comparability + display-only history (§4.15; weakness/ratios in §4.20), strength fitness-fatigue shadow model (§4.16; retrospective rejected), rolling session types / upper-body balance / set reduction / volume management v1 / under-MEV accessory progression / warm-up ramp / 3RM cadence / descriptive progress dashboard (§4.17), live workout mode (§4.21, closed), read-only 4/8/12-week outcomes review, longevity context, prescription-modifier provenance and quick readiness presets/context and readiness feedback, UI prescription persistence (A0/A/B/C/E), minimum effective sessions (D) the methodology/privacy docs (F), W1/W7 attendance metrics and the session-time cap |
| v0.4 | Audit, documentation and form closeout | **done 2026-10-25** | form assessment/prospective follow-up, fatigue diagnostic closure, UI documentation P0–P4, parent-ratio evidence review, weakness test plan, calibration milestone (§4.22) |
| v1.0 beta | Workable app + guided Workflow UI | **released 2026-10-27** | full strength loop, guided readiness → preview → workout → post-workout, effective volume accounting, template editor, schedule fallback/rebalance; user testing in progress |
| v1.1 beta | Performance + monitoring analysis | **released 2026-10-31 (b2); b1 2026-10-30** | raw e1RM Performance view, rolling median, breaks, degraded observations, dose, configured relative-strength ratios, read-only monitoring analysis, calibration transparency; Phase 5A review follow-up |
| v1.2 | Stable release + opt-in resolver | **released 2026-11-03** | beta label removed; deterministic template resolver shipped as opt-in (`resolver.enabled` default false) with acceptance audit closed; cardio depth, reproducible impulse/shadow load and comparable calibration depth deferred to v1.5 (§4.13a/§4.14) |
| v1.3 | UI closure, measurement/readiness cleanup and documentation infrastructure | **released 2026-11-06** | UI redesign P0–P3 closed; body fat moved to measurements with historical migration, readiness inputs cleaned up, measurement chart windows, readiness override beside the score, and the manifest-backed documentation archive; no prescription change |
| v1.4 | VBT target analytics | **released 2026-11-13** | structured/frozen target metadata; Prescribe and Active Workout target visibility and feedback; completed-workout and History target comparisons; Performance longitudinal cohorts with band/RIR evidence and within-set drift; no migration, prescription change or iOS model change |
| v1.4.1 | Patch: native-summary performance and portability test | **released 2026-11-14** | completed-workout summary reads one snapshot and skips unused ratios (native report ~13.3 s → ~7.0 s); the portability test no longer calls the retired review/calibrate CLI; no metric, schema or prescription change |
| v1.5 | Read-only training intelligence (LLM integration) | **released 2026-11-15; constrained proposer withdrawn 2026-11-17** | capability layer, MCP server (ten tools, three resources), REST facade, deterministic weekly review, server narration, web/CLI narrate, server and web chat with the deterministic dossier, plan-aware tools, token budgets, selector retirement and the evaluation harness; no training-decision, prescription or schema change, and the iOS client renders the same envelopes. The constrained proposer (`DEC-LLM-09`) was withdrawn on 2026-11-17, so any write capability needs a new decision rather than a revived plan (§4.24) |
| v1.6 | Cardio depth | **delivered (1.6.0), impulse retired** | v1.6.0 ships the imported cardio corpus, linking, analytics and dashboards (portfolio cardio stage plan); the reproducible cardio impulse/shadow load (§4.13a) was retired 2026-11-18 as product direction (`DEC-LONGEVITY-03`), so it is no longer planned; the deeper labelled calibration set is retired (`DEC-EVAL-09`, §4.14) |
| v1.7 | Longevity assessment | **released 2026-11-18** | `assessment` block on the cardio summary and the phone route, `get_longevity_assessment` capability (MCP tool 11, iOS route, chat dossier), iPhone Today section with a separate health-data consent, time-in-zone panel, web panel with on-demand prose; no migration (§4.36, portfolio plan) |
| v1.7.1 | Longevity corrective release | **released 2026-11-18** | execution-time health/plan tool allowlist, recovery-tail exclusion, elapsed-time time-in-zone with explicit coverage, three-state adequacy above 300 minutes, HR-ingestion cache invalidation, canonical web panel, VO₂max provenance, remote-narration consent; no migration (§4.36) |
| — | Training-day session fragments | **done 2026-11-01** | one local training day may contain multiple session fragments; attendance and budget use days, volume/spinal use combined sets, e1RM uses one day-level observation; no schema migration; see [`docs/TRAINING-DAY-MODEL.md`](docs/TRAINING-DAY-MODEL.md) |
| — | Deterministic dynamic template resolver | **Steps 0–6 complete 2026-11-01/03; merged to `development` 2026-11-03; released in v1.2.0 as opt-in (`resolver.enabled` default false)** | plan and confirmed decisions at [`docs/archive/PROGRAMME-BUILDER-PLAN.md`](docs/archive/PROGRAMME-BUILDER-PLAN.md) and [`docs/DECISIONS.md`](docs/DECISIONS.md) (`DEC-RESOLVER-01`–`12`); Step 1 delivered policy/settings/provenance; Step 2 delivered and remediated the internal deterministic generator core (`generator.py`, `resolver_settings.py`, accepted pattern-flexibility mapping); remediation covers shared injury/constraint eligibility, power-slot safety, require_can_do/unrated/rotation-default semantics, fallback repair, structural availability, whole-session/duplicate-aggregated authoritative spinal scoring, completed-workout precedence, history merge, retired redundant rotation/preference weights and policy/catalogue digests; Step 3 adds the opt-in top-set/back-off structure, top-set persistence and role-aware workout logging, and the hinge maximal-week programme change; Step 4C wires the flag-on resolver path through candidate pools, bounded beam and read-only evaluator, adds pool-aware scheduler availability, rejects selection overrides, and records generated-session provenance; the 4C audit remediation enforces required patterns on final assignments, separates evaluator failure stages, fingerprints beam configuration and DataFrame schemas, and uses the same auto-candidate/slot matching in scheduling; Step 5 adds the dedicated Settings -> Resolver panel, append-only scalar settings, validated policy YAML with atomic writes and 20 timestamped backups, read-only preview with choices/alternatives/suggestions, inline suitability rating, top-set preview, regenerate/diff and a start handoff; the Step 5 remediation adds shared CLI/web readiness enforcement, atomic backup creation, shared resolver-enable confirmation, deterministic restore with a reported pre-restore snapshot, and a full-prescription preview diff; Step 6 adds generated-slot snapshot provenance for critique/exemption reads with a legacy-null fallback, top-set role-aware critique coverage, a real-database copy smoke test, flag/policy rollback verification and the rollout documentation; forecast remains fixed option (c); the flag remains off; **2026-11-18:** the deterministic per-slot rotation schedule was replaced by an exposure-based preference with probabilistic exploration in `DEC-RESOLVER-15` ([`DWELL-AND-ROTATION.md`](docs/DWELL-AND-ROTATION.md), [`RESOLVER-ALGORITHM.md`](docs/RESOLVER-ALGORITHM.md)) |
| future | Derived analytics layer | **Milestones A, B and C implemented 2026-11-14; all planned consumers migrated; C-1 maintenance worker deployed 2026-11-15** | §4.35; shared versioned, rebuildable analytics (per-set, session/exercise, weekly; snapshots optional and deferred) owned by the existing analytical modules; motivated by the ODROID overview (2.7 s p50) and monitoring (49 s) measurements |
| future | Resolver prescription structure and programme context | **WP0 complete 2026-11-19; WP1 not started** | §4.37; ordered set groups over a frozen plan, execution substitutions and additions, top-set tri-state default `off`, programme header, role-quality hierarchy, derived actual structure, later phone gateway; [portfolio plan](https://github.com/georgesdib/strength-app/blob/main/docs/plans/RESOLVER-PRESCRIPTION-STRUCTURE.md) |
| future | Athlete Feedback & Coaching (AFC) | **AFC-2, AFC-2i, AFC-3 and AFC-4 implemented 2026-11-13; physical iPhone acceptance owner-confirmed 2026-11-14; AFC-5 scoped (docs only); backend, web and native iOS presentation** | §4.33; canonical plan [`AFC plan`](https://github.com/georgesdib/strength-app/blob/main/docs/plans/AFC.md); composes the existing adherence, VBT, readiness, feedback and volume services; AFC-1 dissolved and planned-session compliance excluded by `DEC-W7-01`; Phase 5A instruments frozen; AFC-2i renders the same report contract in the iPhone app (`DEC-AFC-03`) |
| — | Symptom attribution and injury-signal verification | **done 2026-11-01** | Phases 1–2 closed: verification hygiene and optional session/lift attribution with required onset/confidence, migration `0047`, CLI/API/web and display-only views. Phase 3 was split into a separate roadmap phase (§4.28) |
| future | Exercise-level symptom research (Phase 3) | **planned; unscheduled** | separate pre-registered descriptive research question; mechanical exposure and regional symptoms, not athlete attribution; no model, score, suitability rule or prescription change; Today follow-up `injury_attribution_phase3`; plan §10 and §4.28 |
| — | 2026-10-26 pass | **done 2026-10-26** | declared breaks — append-only range, `break` CLI, Athlete panel, freeze in the trained-week cycle (`DEC-CONTINUITY-04`, `LIM-50`); P1 measured-test coverage view (`e1rm tests-needed` + Athlete table); symptom settling made fail-safe — a level-1 reading without a recorded 48 h settlement is a flare (`DEC-SYMPTOM-04`, Q25 closed) and `docs/SYMPTOM-LOGGING.md` documents the episode workflow; minimum-session target shown against the measured clock (`DEC-MIN-02`, `LIM-47` mitigated); gaps table folded into `docs/LIMITATIONS-REGISTER.md` |
| — | 2026-10-28 fatigue signals Phase 0 | **done 2026-10-28** | five decisions (`DEC-EXPOSURE-02`, `DEC-DEMAND-01`, `DEC-RESIDUAL-01`, `DEC-SELECT-12`, `DEC-SHADOW-01`), five assumptions, `LIM-56`, ACWR doc drift corrected; `docs/FATIGUE-SIGNALS.md` maps Parts A–D onto the real engine stages and `docs/EXERCISE-DEMANDS.md` defines the companion catalogue. No code, no behaviour change |
| — | 2026-10-28 audit fixes | **done 2026-10-28** | independent beta audit: continuity calibration **accepted** and the decision rewritten (`DEC-CONTINUITY-06`); injury ceiling applied independently of readiness, low back excluded (`DEC-INJURY-04`); readiness set cut takes precedence over the under-MEV top-up (`DEC-VOLUME-33`); browser mutations require loopback Host + same Origin + JSON content type and the CLI refuses non-loopback `--host` (`DEC-WEB-01`); Terminal removed (`DEC-WEB-02`); rubric calibration filtered to the current version (`DEC-EVAL-06`); programme horizon 1–26 weeks and one job per database (`DEC-PROGRAMME-09`) |
| Phase 5A | Prospective validation | **active next stage; 2026-10-30 to 2027-01-22** | `phase5a_review` Today follow-up; see §2A |
| Phase 5B | Evidence-driven implementation | **gated; not approved or underway** | starts only after Phase 5A gate and explicit approval; see §2A |
| — | 2026-10-31 power complement | **done 2026-10-31** | added canonical `broad_jump` to the hinge and `medicine_ball_chest_pass` to both bench days, each quality-limited 3×3–5 before the main lift; box jump remains on squat; power work shares one fixed bucket (9 sets/week); evidence in [`docs/JUMP-VARIANTS.md`](docs/JUMP-VARIANTS.md) and [`docs/THROW-VARIANTS.md`](docs/THROW-VARIANTS.md), decisions `DEC-POWER-04/05` |
| — | 2026-10-30 monitoring Phase 4 | **done 2026-10-30** | read-only calibration observation layer around the active calibration; formula/method version and current-as-of semantics exposed; reusable descriptive dose/lag/missingness analysis service with Performance UI and GET /api/monitoring-analysis; CLI remains a thin wrapper; no calibration calculation/application changes, no model adoption and no schema change |
| — | 2026-10-30 monitoring Phase 3 | **done 2026-10-30** | Performance view and API/CLI for raw e1RM observations, rolling median, series breaks and dose; functional session-type/deload/quality filters; degraded observations shown separately; explicitly configured relative-strength ratios with eligibility-aware history; comparable-session descriptive summary; no target ratios, diagnosis, decay or calibration. Equipment breaks remain undetectable because equipment is not stored |
| — | 2026-10-30 monitoring Phase 2 | **done 2026-10-30** | completed-workout descriptive summary (completion, raw strength, dose, special exposure, feedback) with API/CLI/end-screen; approved append-only `session_feedback.productivity` 1–5 migration preserving existing rows; no ratios, longitudinal trends or prescription control |
| — | 2026-10-28 knee-flexion accessory | **done 2026-10-28** | `lying_leg_curls` 3×8-12 added to the squat and hinge sessions with `nordic_curl` as an opt-in candidate; `knee_flexion` is a managed ledger key (MEV 3 / MAV 4–8 / MRV 10, target 6/week, cap 4) and the `hamstring_eccentric` pattern maps onto it; weekly total 57→63, effective 68.25→74.25; programme summary regenerated; remaining unprescribed groups recorded as accepted gaps (`LIM-54`) (`DEC-KNEEFLEX-01`, `ASSUMPTION-50`) |
| — | 2026-10-27 audit follow-up | **done 2026-10-27** | back-flare alignment (`DEC-SPINE-07/08`), quality-limited power (`DEC-POWER-02/03`), same-date plan accounting (`DEC-VOLUME-30/31/32`), readiness RIR re-solve (`DEC-READINESS-18`), generated programme summary; independent audit report [`docs/archive/AUDIT-FOLLOW-UP-REPORT.md`](docs/archive/AUDIT-FOLLOW-UP-REPORT.md); `LIM-53` closed; **audit fully closed 2026-10-27, no open follow-ups** |
| — | 2026-10-25 corrective pass | **done 2026-10-25** | e1RM selector + plausibility advisory (`DEC-E1RM-SOURCE-01`, `DEC-E1RM-PLAUS-01`), `MOD-SPINE-001` spinal trim, group-level volume status (`DEC-VOLUME-05`), technique throttle in the API and Prescribe form (`MOD-TECH-001`), e1RM overrides in Exercises and post-workout; legacy A/B/C labels removed from rule scopes and taxonomy `day_roles`; squat loading kept out of the spinal cap as a recorded scope decision (`DEC-SPINE-04`, later superseded by `DEC-SPINE-05`); constitution 1.13.1 (`DEC-RIR-04`; `MOD-TECH-001`/`MOD-MIN-001` declared) |
| — | Post-workout form assessment | **done 2026-10-25** | optional per-lift 1–5; Workout + History edit; rubric 1.2.0 |
| v0.1 | Complete | **done** | 3.1-3.4, 3.6-3.7 done; 3.5 video descoped; 3.8 labelled set moved to §4.14 |
| — | Performance | **resolver sequential build 133.15 s → 42.13 s historical; clean-set snapshot A/B 46.19 s → 35.41 s on the current 375-session DB; multiprocessing not justified** | `docs/PERFORMANCE-PROFILE.md`; schedule/settings/policy/E1RM/VBT caches plus the per-generation clean-set snapshot, no behaviour change |
| — | UI | **local web done; hosted UI deferred** | `strength_coach/web/`, `docs/WEB-UI.md`, `http://127.0.0.1:8000`; six task areas and actionable Today; integrated 4/8/12-week Progress with reusable dependency-free SVG line/bar charts, selectable e1RM, pattern/exercise working-set trends, observed-day calendar/frequency, lagged dose associations, bounded original-plan vs logged execution, retained sRPE/main-lift summaries and explicit data gaps; basis/unit-safe load/reps graphs and consolidated exercise dialog; Settings defaults, seven-day plan cache, History form override, resolver and VBT work; **UI redesign P0–P3 complete; final audit passed 2026-11-06** in `docs/archive/UI-DESIGN-IMPLEMENTATION-PLAN.md` |
| — | Engine audit W0–W12 | **closed 2026-10-23** | `docs/archive/AUDIT-CLOSEOUT.md`; open items in `docs/LIMITATIONS-REGISTER.md` |
| — | 2026-11-06 documentation manifest + archive | **done 2026-11-06** | Public documentation now has one authoritative manifest (`docs/manifest.yaml`) consumed by the Docs API/viewer and tests, a curated index (`docs/README.md`), and an archive of 27 completed plans/closed audits under `docs/archive/` with an index. The W0–W12 reports are grouped in `docs/archive/audits/`, the HTTP API reference is split into `docs/API.md`, and readiness has a reference map. Categories replace the flat list in the Docs viewer; `docs/design/` remains maintainer-only and `private/` is never listed or served (boundary tests added). Links and tests updated; no application, API, schema or prescription change |
| — | 2026-11-06 demand evidence + readiness/measurement cleanup | **done 2026-11-06** | Demand-profile form cites existing evidence ids from the reviewed catalogue through a preselected, iOS-safe checkbox list (a native multi-select shows "0 items" on iPhone). `conventional_deadlift` is a taxonomy `primary_compound` (`DEC-RESOLVER-13`, `main_lift` unchanged) so `PRG-RIR-001`'s RIR window covers its logged sets; its local UI override is removed and the generated programme/workout docs are regenerated (digest only). Readiness drops the unused nutrition/hydration inputs (`DEC-READINESS-20`, constitution 1.21.0 guard list only) and body fat moves to the periodic measurement log as `body_fat_pct` (`DEC-MEASURE-02`, migration 0051 copies 828 historical values and future imports are idempotent). The never-written readiness `composite`/`composite_basis` columns and `composite.enabled` config key are removed (migration 0050). LIM-59 closed as a design choice; no prescription or load arithmetic changed |

### Version plan (2026-10-25)

| version | boundary | status |
|---|---|---|
| v0.2 | readiness, continuity, injury, web UI, cardio capture, measurements, session RPE/length, recent stress, per-lift readiness, e1RM calibration/decay | **done** |
| v0.3 | everything strength/data-depth that is not cardio: manual logging, adapters closed, LLM proposal view CLI-only, continuity calibration, exercise selection, strength fitness-fatigue model | **done** |
| v0.4 | audit/documentation/form closeout: form assessment, fatigue diagnostic, UI docs P0–P4, ratio review, weakness plan, calibration milestone | **done 2026-10-25** |
| v1.0 beta | workable app, guided Workflow UI and the current strength/volume feature set | **released 2026-10-27; beta** |
| v1.1 beta | monitoring and Performance surfaces | **released 2026-10-31 (b2); beta** |
| v1.2 | beta removal plus opt-in deterministic resolver | **released 2026-11-03; stable** |
| v1.3 | UI closure, measurement/readiness cleanup and documentation infrastructure | **released 2026-11-06; stable** |
| v1.4 | VBT target metadata, active/historical target feedback and longitudinal target analysis | **released 2026-11-13; stable** |
| v1.5 | read-only training intelligence: capability layer, MCP server, REST facade, narration and chat | **released 2026-11-15; stable** |
| v1.6 | cardio depth and reproducible cardio impulse/shadow load | **delivered (1.6.0): corpus, linking, analytics, dashboards; the impulse (A2/A3) was retired 2026-11-18 (`DEC-LONGEVITY-03`)** |
| v1.7 | longevity assessment (§4.36): aerobic adequacy as context, VO₂max status, per-pattern headroom, sample-based time-in-zone and advisory prose on iPhone and web, with the three post-1.6.0 readiness/cardio fixes | **released 2026-11-18** |
| v1.7.1 | longevity correctness, privacy and integration (§4.36): execution allowlist, tail exclusion, elapsed-time integration, above-band state, cache invalidation, canonical web panel, VO₂max provenance and remote-narration consent | **released 2026-11-18** |
| — | training-day session fragments | **done 2026-11-01** (see §4.27) |
| — | post-workout form assessment | **done 2026-10-25** |
| future | LLM integration: read-only intelligence delivered; constrained proposer withdrawn | **read-only delivered; no write path (§4.24)** |

**Rule:** cardio work does not enter v0.3; video is descoped. The strength model (§4.16) is
strength-only and closed with v0.3. Audit/documentation/form closeout is v0.4. v1.0 is the beta
release for user testing; v1.1 is the monitoring beta; v1.2.0 removed the beta label and
shipped the resolver as an opt-in feature; v1.3.0 closed the UI redesign and consolidated the
measurement/readiness and documentation work; v1.4.0 shipped the VBT target analytics and v1.4.1
patched the native summary performance and the portability test; v1.5.0 shipped the read-only
training intelligence workstream. Cardio depth moves to v1.6, and the deeper labelled calibration
set is retired (`DEC-EVAL-09`). v1.6.0 shipped the cardio stage on 2026-11-18; the impulse was retired the same day
(`DEC-LONGEVITY-03`) in favour of the longevity assessment, which shipped as v1.7.0 with the
post-release readiness/cardio fixes. v1.7.1 corrected the longevity assessment's consent,
intensity, time-in-zone, cache and presentation issues without a migration.

### What works end to end today

A real export can be cleaned, flagged, quarantined, grouped into sessions, given a programme
day guess, calibrated for velocity targets, and **persisted**: one import writes `raw_row`,
`clean_set`, `session` and `quarantine` inside a replayable `run`/`run_event` trace, and
re-importing the same file writes no duplicate rows. The constitution can now be evaluated
against that history: `rules` parses the YAML into hash-bearing `Rule` objects, the registry
supplies one predicate per `check.fn`, and `policy` returns a verdict per rule with citable
evidence. A session for **each of the four rolling session types is now generated**: loads solved from a selected e1RM — a 28-day median by default, `best_usable` or `most_recent` by config (`DEC-E1RM-SOURCE-01`) — or from double
progression for accessories, rounded down to the athlete's 0.5 kg microplates, with
MOD-FAT-001 reducing loads when sleep or energy is <= 2. Every item cites a rule id and a
stored set, and the prescription refuses to be executable if a load, the RIR window, the
erector-day rule or the weekly spinal cap would be broken. At the weekly cap (the normal cycle
sits exactly on it) a non-essential erector slot is trimmed rather than left dead
(`MOD-SPINE-001`); essential overages still veto and name the exposures. A main-lift load whose
e1RM sits far above the lift's recent median raises a display-only advisory rather than a load
change (`DEC-E1RM-PLAUS-01`). The web UI exposes the one-session technique throttle on the Prescribe
form (`MOD-TECH-001`) and appends e1RM overrides from an Exercises row or the ended-workout
panel, where a recorded test feeds the measured/formula calibration. A performed session used to
be **critiqued** by a deterministic rubric with evidence references; that rubric is retired
(`DEC-EVAL-09`) and no session is scored any more, though the historical critiques remain readable
through `GET /api/review/<session>`. An **optional narrative** can explain the prescription: the
model receives the facts as JSON, may not compute, and its output is recorded as a `run_event`
rather than written into a prescription or a score. With no model configured (`NullLLM`) the run
is structurally identical and loses only the prose. **The full v0 slice runs**:
`strength-coach run --date` imports if needed, prescribes the date, persists the prescription
inside a run trace, and prints a rationale that cites a rule or a stored fact.

## 2A. Phase 5 — prospective validation and evidence-driven improvements

Phase 5 is split into two gated stages. Only Phase 5A is active. Phase 5B must not begin
until the 22 January 2027 review gate is completed and the user explicitly approves it.

### Phase 5A — Prospective validation

| Item | Value |
|---|---|
| Status | **active next stage** |
| Observation start | 2026-10-30 |
| Formal review date | 2027-01-22 |
| Duration | 12 weeks |
| Today follow-up | `phase5a_review` — Phase 5A — Prospective validation review |

Objective: evaluate the existing monitoring system prospectively on real training data
collected during normal use.

During Phase 5A:

- do not change monitoring model parameters, thresholds, metric definitions or eligibility;
- do not change calibration factors/logic or prescription/optimisation behaviour;
- do not introduce predictive models or tune thresholds to observations;
- do not treat correlations as causal or silently change a metric because its result is unexpected;
- data-integrity or incorrect-calculation bug fixes are permitted only when documented,
  justified and tested;
- AFC (§4.33) is read-only composition and must not change `attendance.pct`, the flags in
  `features/prospective.py`, monitoring/exposure/calibration configuration, or the end-screen
  capture controls for session RPE, duration and productivity ([`AFC plan`](https://github.com/georgesdib/strength-app/blob/main/docs/plans/AFC.md) §5).

Evaluate/classify every metric using the existing monitoring analysis infrastructure:

- data quality: completeness, missingness, consistency, provenance;
- measurement reliability: stability and repeatability;
- metric behaviour: distributions, variability, sensitivity, responsiveness;
- calibration: evidence supporting the existing approach;
- training response: plausible correspondence with performance and exposure, without causal claims;
- practical utility: interpretability without overstated certainty.

Evidence classes: **supported**, **provisionally supported**, **insufficient evidence**,
**not validated**, **not applicable**, each with rationale.

**22 January 2027 review gate:** document the evidence and choose exactly one:

A. proceed to Phase 5B;
B. extend Phase 5A once by approximately four weeks, documenting the missing evidence;
C. close Phase 5A without Phase 5B, documenting which metrics remain unvalidated.

**Documentation at the same gate:** fold the maintainer-only monitoring design history
(docs/design/) into [docs/MONITORING-ANALYSIS.md](docs/MONITORING-ANALYSIS.md) and retire or mark
the separate design trail; tracked in §4.19. Do it only after this review classifies the metrics.

Completing the Today follow-up requires an explicit decision; it never starts Phase 5B or
changes monitoring automatically.

**Closed-item check:** parent/variant e1RM ratios remain closed as weakness, injury or automatic-selection measures (DEC-SELECT-09). The configured relative-strength ratios in Performance are descriptive only and do not reopen that decision. See DEC-MON-03.

### Phase 5B — Evidence-driven implementation (gated)

| Item | Value |
|---|---|
| Status | **gated; not approved or underway** |
| Start | only after the Phase 5A gate and explicit user approval |
| Initial duration | 4–8 weeks |

Each proposed change must identify the Phase 5A finding, evidence, expected effect,
unintended consequences, acceptance criteria, tests and documentation/limitations updates.
Changes must be classified as measurement/data-quality correction, metric-definition
correction, calibration improvement, threshold/classification adjustment, new analytical
capability, or rejected proposal. Rejected proposals are documented with reasons.

Phase 5B is complete only when every Phase 5A finding is assessed, supported changes are
implemented or explicitly rejected, tests pass, no critical data-integrity/monitoring defect
remains, and validated versus unvalidated capabilities are clearly distinguished.

Phase 5B must not introduce predictive/prescriptive behaviour merely from a descriptive
association without separate justification and validation.

## 3. Completed work (archive)

v0.1 and the closed v0.2-v1.x subsections are recorded in [ROADMAP-DONE.md](ROADMAP-DONE.md).
That file is a historical audit record and is not a default read; this roadmap keeps current
and future work only.

## 4. v0.2 — input flexibility and the programme view

v0.1 assumes three things that the athlete has now explicitly challenged: that input arrives
as one CSV in one known shape, that only one day is prescribed at a time, and that readiness
is only available on days the export happened to record. v0.2 loosens all three.

Nothing here changes the constitution or the append-only rule. Missing data still yields
`unknown`, never a default.


> Closed subsections (4.1-4.8, 4.10-4.12, 4.14-4.17, 4.21-4.23, 4.25-4.27, 4.29-4.32, 4.35-4.36
> and 4.9.1-4.9.5) are in [ROADMAP-DONE.md](ROADMAP-DONE.md); their numbering is preserved there.

### 4.9 Readiness score and follow-ups  (core + devices done; learned weights closed)

Implemented (2026-10-19/20):

- global 0.00-1.00 score from sleep, energy, mood, stress and soreness, with a three-field
  minimum and a sleep/energy requirement;
- category scores; the injury signal is a ceiling, never an average;
- global/category overrides at the score scale, append-only, reason required; override wins over
  computed readiness and changes the load, but never bypasses constraints or injury ceilings;
- 20% cap on combined readiness + continuity reduction (guardrail, no direct evidence);
- readiness-required gate for current/future CLI and web workouts;
- calibration report against the 306 black-box legacy labels, with main-lift load features,
  date split and baseline; report only, no auto-apply;
- baseline-relative HRV/RHR at 0.5 weight, only with 7 readings in the previous 28 days;
- optional device-computed wearable readiness (0-100) at a 10% blend.

Full design and evidence: [`docs/READINESS-SCORE.md`](docs/READINESS-SCORE.md) and
[`docs/READINESS-WEIGHT-EVIDENCE.md`](docs/READINESS-WEIGHT-EVIDENCE.md).

#### 4.9.6 Per-lift readiness validation — open, unscheduled

The per-lift score is implemented and downward-only (`DEC-LIFT-READY-01`): global base plus the
previous session's e1RM trend, mean RIR and VBT, with weights 0.20/0.15/0.15 (`ASSUMPTION-25`).
It is not a validated instrument: it is retrospective, RIR is imprecise, VBT is sparse and
load-dependent, there is no lift-specific pre-session soreness/pain input, and no prospective
test shows that lowering a lift's load on this score improves outcomes. It can only lower a
load and never replaces the global readiness score; see [`docs/LIFT-READINESS.md`](docs/LIFT-READINESS.md)
§5 and `LIM-62`.

**Follow-up, when prioritized:** add a lift-specific pre-session 1–5 soreness/readiness rating,
define a standardised velocity check at a fixed load, collect measured e1RM tests for a better
trend, then test prospectively whether a low per-lift score predicts a missed rep or a worse
session. Do not change the load policy from this score until that validation exists. Not
scheduled; it is not part of v1.6.

### 4.13 Cardio workouts and an impulse fatigue model  (capture v0.2 done; cardio model v1.5; strength model is §4.16)

**Capture retired 2026-11-17.** Manual cardio logging (`cardio_log`, the web form, the `cardio` CLI
command) was removed in favour of the imported corpus; the portfolio cardio stage plan is the
canonical account and closed on 2026-11-18 at release 1.6.0. That stage deferred the web
time-in-zone chart and HealthKit deletion detection (replaced by hiding a workout); its test debt is
recorded there. The impulse item below was retired on 2026-11-18 (`DEC-LONGEVITY-03`); the
[longevity assessment plan](https://github.com/georgesdib/strength-app/blob/development/docs/plans/LONGEVITY-ASSESSMENT.md) replaces it with sample-based time-in-zone,
which adds no load model.

The app currently measures resistance training only. Cardio is a separate exposure with a
different fatigue signature, and a single "fatigue score" would hide that. This item adds the
data and a model, initially advisory and in shadow mode.

**Delivered 2026-10-20 and superseded 2026-11-17.** The first cut was an append-only `cardio_log`
with a `cardio` CLI command and `GET/POST /api/cardio`. It never held a row, and the imported
corpus replaced it: `cardio_log`, the command, the routes and the form are gone (`0069`), the
longevity review reads the corpus, and hiding a workout replaces manual correction. The model below
was never built and was retired on 2026-11-18 (`DEC-LONGEVITY-03`); no prescription reads cardio
data.

**Priority:** the longevity review ranks cardio capture as the largest gap between the
programme and the primary goal — cardiorespiratory fitness is the strongest modifiable
mortality signal, and the app currently records none of it
([`docs/LONGEVITY-REVIEW.md`](docs/LONGEVITY-REVIEW.md)). Capture is useful before the fatigue
model exists; the model stays shadow-mode until there is data.

**Scope**

1. **Cardio capture** — modality, duration, average/max HR, HR zones, distance or power where
   available, session RPE, notes. Append-only; no free-text parsing in the core.
   **Done (migration 0011):** modality, duration, average/max HR, distance and sRPE; HR zones
   and power are not captured yet.
2. **Training impulse** — compute a documented impulse per session: HR-based TRIMP where the
   data supports it, otherwise session-RPE × duration. Say which one was used and why.
3. **Fatigue model** — start with an impulse-response / fitness-fatigue model:
   - a fitness (positive, slow-decaying) and fatigue (negative, faster-decaying) term;
   - at least two systems: cardiovascular and neuromuscular/spinal, rather than one global
     impulse;
   - time constants and weights are config, per athlete when enough data exists;
   - the model reports a **fatigue state**, not a diagnosis.
4. **Interaction with the existing layers** — cardio fatigue may inform readiness and load
   selection, but it must not override constraints, the injury signal or readiness overrides.
   Cardio that loads the knees/low back must be linked to the injury regions so it is not
   invisible exposure. Avoid double-counting the same session as both resistance and cardio.
5. **Shadow first** — compute and display the impulse and fatigue state for weeks without
   changing a prescription. Only then consider a load/RIR effect.

**Evidence and limits**

- The Banister impulse-response model relates training impulses to performance, but its
  parameters are ill-conditioned and unstable; a good fit does not make the parameters
  identifiable ([Hellard 2006](https://doi.org/10.1080/02640410500244897)).
- A single impulse reduces different training types to one number; the proposed
  three-dimensional model separates energy-system-specific adaptation, which is the direction
  this item should take rather than one global fatigue scalar
  ([Kontro 2026](https://doi.org/10.1371/journal.pone.0341721)).
- HRV, sRPE and subjective wellness can be inputs to an impulse-response model, but the
  relationships are not a validated individual prescription
  ([Piatrikova 2021](https://doi.org/10.1123/ijspp.2020-0201)).
- Fitness-fatigue models need longitudinal individual data; a generic parameter set is a
  prior, not a measurement ([Wang 2025](https://doi.org/10.1371/journal.pone.0337824)).

**Open questions (historical — the item was retired 2026-11-18; none of these is live)**

1. Which cardio modalities are in scope (walking, cycling, rowing, running, intervals)?
2. Is TRIMP available from the athlete's devices, or is sRPE the only usable impulse?
3. Should the model have two systems (cardio/neuromuscular) or three (add metabolic/energy
   system), and how do they interact?
4. Do cardio sessions link to injury regions by pattern (e.g. running → knee) or only by
   explicit tags?
5. Does fatigue modify load, RIR, volume or only the displayed readiness context?
6. How many weeks of data before an individual time constant is shown?
7. Can a cardio session count as readiness/load evidence without a symptom follow-up?

**Acceptance**

A cardio session can be recorded and cited; its impulse is reproducible and labelled by
method; the fatigue state is displayed with inputs and time constants; a shadow period changes
no prescription; constraints and injury ceilings remain vetoes; no cardio session silently
counts as resistance volume or vice versa.

### 4.13a v1.6 plan — cardio depth  (deferred from v1.2; approved 2026-10-25)

**Goal:** make cardio a first-class, reproducible exposure; add only a shadow cardio-load
context; and deepen calibration enough to decide whether any rubric definition should change.
No automatic cardio load effect and no parent-variant/weakness implementation in this phase.

**Status 2026-11-18 — A0 and A1 are delivered; the impulse stays here.** The A0 data audit is measured and
published in the portfolio cardio stage plan
([C0 audit](https://github.com/georgesdib/strength-app/blob/development/docs/plans/CARDIO-C0-AUDIT.md),
[plan](https://github.com/georgesdib/strength-app/blob/development/docs/plans/CARDIO-STAGE.md)): 1,431
HealthKit workouts, 546 k usable HR samples, 320 of 378 sessions with a single same-day workout
candidate, and exactly one historical exact identifier. Capture completion (A1) shipped with that stage,
which closed on 2026-11-18 at release 1.6.0. The impulse/shadow load (A2/A3) and the model decision
(A4) were **retired the same day** (`DEC-LONGEVITY-03`): TRIMP, sRPE impulse, acute:chronic ratios
and unified fatigue scores are closed as product direction, and A5 (interaction review) follows them.
The replacement is the [longevity assessment plan](https://github.com/georgesdib/strength-app/blob/development/docs/plans/LONGEVITY-ASSESSMENT.md): deterministic aerobic adequacy, VO₂max
status and per-pattern headroom, with sample-based time-in-zone as the only new cardio computation.
Nothing reads cardio data to change a prescription.

**Principles**

1. Capture and data quality before modelling.
2. Impulse must be reproducible and labelled by method.
3. Cardio and strength fatigue stay separate; no single global fatigue scalar.
4. Shadow first; a model may not change a load, RIR, set or selection until it beats a simple
   baseline and completes a frozen prospective period.
5. Calibration changes are separate from model changes and require the existing per-item gate.
6. No optimiser, ML model, LLM programme generation, parent-variant targeting or weakness
   targeting.

**Workstream A — cardio**

| phase | deliverable | gate / acceptance |
|---|---|---|
| A0. Scope and data audit | Confirm modalities (walking, cycling, rowing, running, intervals), available HR fields, resting-HR source and explicit injury-region tags; measure current coverage | A short audit states how many sessions have duration, average/max HR, sRPE and modality; unresolved questions are recorded, not guessed |
| A1. Capture completion | Close only the gaps the audit proves necessary; keep append-only; no free-text parsing in the core | A cardio session can be recorded with its method-relevant fields and cited from the UI/CLI |
| A2. Impulse v1 | Compute one documented impulse: HR-based TRIMP where average HR, resting/max HR and duration exist; otherwise sRPE × duration. Store the method and inputs | Fixed test cases reproduce the impulse; every value says which method was used and why |
| A3. Shadow load context | Show 7-day and 28-day cardio load and a separate cardio/neuromuscular context; do not fit a fitness–fatigue model yet | Display includes inputs, method coverage and time window; no prescription reads it |
| A4. Model decision | Only after at least 12 weeks and ~24 cardio sessions: fit a cardio fitness/fatigue candidate and compare with the simple 7/28-day load and readiness-only baselines | No model is fitted on readiness as if it were performance; if it loses, keep descriptive load only |
| A5. Interaction review | Decide whether cardio context may inform readiness display, never constraints/injury/loads | Any load/RIR effect is a separate decision after a prospective result |

**Workstream B — calibration depth**

| phase | deliverable | gate / acceptance |
|---|---|---|
| B0. Comparable data | Use Workout mode so prescriptions have snapshots; collect optional per-rep CSV where available | Comparable counts are reported per item, not just mark counts |
| B1. Review the measurable items | **done 2026-11-07** — written review in [RUBRIC-CALIBRATION.md](docs/RUBRIC-CALIBRATION.md); rotation is a definitional split (app-assigned neutral), essential work is coverage-limited | Acceptance met: the review classifies the remaining disagreements as rubric, measurement or data-coverage; no retune |
| B2. Reach the item gate | **retired 2026-11-13** — the loop ended before the gate was reached (`DEC-EVAL-09`) | No further marks are collected; the historical counts stay in RUBRIC-CALIBRATION.md |
| B3. Rubric decision | **not taken; retired with the rubric** (`DEC-EVAL-09`) | No definition or weight change; this is closed, not deferred |

**Sequence and timing**

- **Weeks 1–2:** A0, A1, B0.
- **Weeks 3–4:** A2, A3; start the shadow load display.
- **Weeks 5–12:** collect cardio and comparable workout data; B1 review at the midpoint.
- **Week 12+:** A4 model decision; the B2/B3 rubric decision was retired with the rubric
  (`DEC-EVAL-09`).
These are planning windows, not promises; missing data pauses the dependent phase.

**Success criteria**

- Cardio coverage is measured and most sessions have a labelled impulse method.
- The shadow context is reproducible and changes no prescription.
- No cardio session silently counts as resistance volume, and no cardio session is invisible
  to an explicit injury-region tag.
- Calibration reports per-item comparable n, not only high-confidence mark counts.
- Any future load effect has a retrospective baseline win and a frozen prospective test.

**Out of scope**

- Parent-variant e1RM ratios and weakness/injury targeting — parent ratios remain unscheduled,
  display-only at most; see [PARENT-VARIANT-WEAKNESS-EVIDENCE.md](docs/PARENT-VARIANT-WEAKNESS-EVIDENCE.md).
- A single combined cardio/strength fatigue score.
- Optimiser, ML, automatic programme generation.
- Automatic cardio-driven load or RIR changes.

**First actions**

1. Run the A0 cardio data audit and record coverage/method gaps.
2. Confirm the cardio modalities and resting-HR source with the athlete.
3. Add the A2 impulse contract and fixed test cases before any model work.
4. Keep collecting live workouts and per-rep data for B0 in parallel.

### 4.18 LLM-guided suggested programme  (future; not scheduled)

**Idea:** the model could eventually propose a *suggested programme* — session emphasis, exercise
choices, weekly volume allocation and progression structure — rather than only narrating a
Python-built prescription.

This is explicitly future work, not a v0.3 deliverable. The existing invariants still apply:

- the model receives a structured state/evidence summary and a bounded menu of allowed
  exercises, sessions and volume bands;
- it may propose **choices**, never loads, reps, RIR, percentages or safety vetoes;
- Python validates every proposal against the constitution, constraints, injury signal, volume
  landmarks and comparability classes;
- a suggested programme is shown as a diffable proposal with evidence and assumptions, and is
  never applied without explicit approval;
- every proposal and approval is audited; the deterministic programme remains the fallback;
- the proposal must not invent evidence or hide uncertainty.

**Prerequisite:** a stable programme schema, a validated volume/selection policy and enough
reviewed sessions to evaluate whether the suggestions are better than the fixed programme.
**Status:** idea only; no implementation. It is now developed as the two-iteration workstream
in §4.24 and [`docs/LLM-INTEGRATION-PLAN.md`](docs/LLM-INTEGRATION-PLAN.md); this subsection is
kept as the original idea record. Its forward planning is now §4.34 and the portfolio Training
Intelligence plan; the proposer part is deferred/unscheduled.

**Next-phase design:** the final lean non-cardio fatigue-management plan is **closed**
([`docs/archive/NEXT-PHASE-FATIGUE-PLAN.md`](docs/archive/NEXT-PHASE-FATIGUE-PLAN.md)). It used the existing
data plus an sRPE/duration backfill for descriptive calibration and implemented the optional
deload plus four deterministic programme changes, and closed individual MRV as not estimable.
No programme experiments, no individualised MRV and no randomised deload trial. The remaining
deferred items stay listed in §4.19.

### 4.19 Open next actions

Completed and closed items were removed from this list on 2026-10-25; the status table,
[`CHANGELOG.md`](CHANGELOG.md) and [`docs/DECISIONS.md`](docs/DECISIONS.md) keep the record.

| priority | action | status |
|---|---|---|
| P1 | Record **≥3 measured tests per main lift** so `MOD-E1RM-001` can calibrate the formula (the bias question is data-starved, not mechanism-starved) | **next** — `e1rm tests-needed` reports counted tests per main lift against the gate (the Athlete page shows the same table); `e1rm calibrate` shows the ratio and CI; record from the Athlete page, an Exercises row or the post-workout panel |
| P2 | Fold the monitoring design history into docs/MONITORING-ANALYSIS.md | **scheduled 2027-01-22, with the Phase 5A review gate** — the canonical analysis already indexes the design trail; at the gate, summarise docs/design/... into the canonical document and retire or mark the separate trail. Do not do it earlier: Phase 5A classifies each metric, and the design must not be presented as settled first |
| P2 | Web authentication + per-user data | **backlog; overkill for now** — CLI-only user provisioning, auth DB, per-user coach DB, login/session/CSRF, password reset, birthdate/gender/timezone onboarding, TLS reverse proxy and home-network host. Temporary no-auth HTTP bind is accepted under `LIM-57` |
| P2 | Parent-variant e1RM ratios | unscheduled; display-only at most (§4.20.2) |
| P2 | Weakness/injury-targeted selection | deferred to after v1.3 / ~April 2027; gates in §4.20.3 and `DEC-SELECT-05` |
| P2 | Main-lift upward-revision ratchet | **deferred, not scheduled** — rejected as a controller in `DEC-E1RM-PLAUS-01`; revisit only if calibration cannot close the bias |
| P2 | Volume-ledger denominator and zero-week coverage | **implemented** — calendar-window denominator, complete-coverage zero-fill, break/deload reset for under-MEV; live profile coverage complete; design in VOLUME-MODULATION-PLAN §14, Q29 |
| P2 | Step 8 effective-set accounting | **implemented and live 2026-10-27** — 0.25 map, target 68.25, landmarks unscaled, effective budget/ledger, raw UI column, `hard`/`effective` switch; rollback one profile change (VOLUME-MODULATION-PLAN §15–16) |
| P2 | Volume modulation: weekly target + session cap | **complete/closed 2026-10-27** — steps 1, 2, 2b, 9a and 9b implemented: read-only budget, per-group accessory budget behind the off-by-default profile flag (`MOD-VOL-003`, constitution 1.17.0), opt-in main-lift `reduce`, compensation preview, and opt-in additive compensation application (`MOD-VOL-004`, executable load required, high-band guarded); **9c-1 drop engine** and **9c-2 identity/UX** implemented (labels/API/UI, startable empty technique, derived review, forecast actual types, migration 0038; `MOD-VOL-005`/constitution 1.18.0); **9c-3 confirmation/settings** implemented (Settings/API, local overlay, per-session confirmation); **7a settings registry/snapshot** implemented (deload reactive constants moved to config); **step 4 settings profile** implemented (append-only versions, budget wiring, snapshots); **7b profile-backed feature wiring** implemented (DUP, deload, volume, readiness, e1RM, plausibility); **step 5 Settings UI/guarded settings** implemented; **5b modality registry/UI** implemented (11 modules, CLI/API/UI parity); **step 6 budget-aware forecast/weekly panels**, **5c remaining modules** and **step 8 effective-set accounting** implemented and live; the plan is closed. Step 3 is a standing Today-page review follow-up, not a plan milestone. The programme forecast now supports 1–5 sessions/week; 4 uses Mon/Wed/Fri/Sun and 5 uses Mon/Tue/Thu/Fri/Sun. Design in `docs/archive/VOLUME-MODULATION-PLAN.md` |
| v1.1 | Fatigue signals: exposure, substitution, advisories | **Phase 0 done 2026-10-28** (five decisions; `docs/FATIGUE-SIGNALS.md`, `docs/EXERCISE-DEMANDS.md`). **Phase 1 done 2026-10-28**: `config/exercises/demands.v1.yaml` populated for **28/63** reachable ids (4 in-scope dimensions at 55.6 % known, 2 `supported` claims, 4 evidence entries). **Rating path done 2026-10-28**: git-ignored `config/exercises/demands.local.yaml` overlay merged over the reviewed file, with `exercise demands report|unrated|set|clear` and automatic rollback on a rejected write (digest covers both files). **Phase 2 done 2026-10-28**: `features/exposure.py` (7/28-day ratio, coverage, gap/deload/break abstention, exposure dedup, per-group ratios), `exposure ratio` CLI, `GET /api/exposure`, Prescribe **Exposure ratio** panel and the Part D low-exposure advisory; report-only, trim not implemented. **Demand display done 2026-10-28**: Exercises rows show `rated/4` and the details dialog shows the profile with confidence, reason, catalogue digest and overlay state; the same form rates or clears a dimension (`POST /api/exercises/demands`, same `set_claim` as the CLI). **Phase 3 done 2026-10-28**: `MOD-EXP-001` (constitution 1.20.0) trims at most one non-essential accessory set per affected group (≤2/session, floor 1) when `athlete_profile.exposure_trim_enabled` is on (default off), skipping main lifts, essential items, readiness cuts and under-MEV additions; `shadow_decision` table + repository exist (append-only triggers). Shadow writes and the review report land in Phase 6 so forecast builds never write rows. **Phase 4 done 2026-10-28**: `prescribe/fatigue_selection.py` suggests at most one accessory substitution when the exposure signal is high, the candidate is A/B comparable, covers the current lift's primary muscles and is rated strictly lower on an in-scope demand dimension; `GET /api/substitution`, the Exercise-selection panel block and `select --fatigue` expose it. Suggest-only; abstains when the trim already acted or the metadata is unknown. **Phase 5 done 2026-10-28**: `features/residual.py` computes the VBT-only execution residual (observed minus prescribed velocity) from linked workout sets, lift-scoped, 84-day window, with the ≥5 signal and ≥20/8-week/two-lift evaluation gates; `residual`, `GET /api/residual` and the Prescribe panel expose it. Shadow only. **Phase 6 done 2026-10-28**: `prescribe/shadow.py` writes exposure + substitution rows only when a prescription is persisted; `features/shadow_report.py` and `shadow`/`GET /api/shadow`/Prescribe **Shadow review** expose counts, abstentions, conflicts and the four gate checks. The gate never enables anything (`activation_allowed: false`); the fatigue-signals specification is fully implemented. |
| v1.6 | Cardio depth | **delivered (1.6.0)** — corpus, linking, analytics and dashboards; the impulse/shadow load was retired 2026-11-18 (`DEC-LONGEVITY-03`, §4.13a) |
| v1.7 | Longevity assessment | **released 2026-11-18 (1.7.0)** — `assessment` block, capability and MCP tool, iPhone Today section with its own health consent, time-in-zone panel, web panel with on-demand prose; no migration (§4.36, [plan](https://github.com/georgesdib/strength-app/blob/development/docs/plans/LONGEVITY-ASSESSMENT.md)) |
| v1.7.1 | Longevity corrective release | **released 2026-11-18 (1.7.1)** — execution-time allowlist, tail exclusion, elapsed-time integration with coverage, above-band state, HR cache invalidation, canonical web panel, VO₂max provenance and remote-narration consent; no migration (§4.36) |
| — | Deeper labelled calibration set | retired 2026-11-13 (§4.14, `DEC-EVAL-09`) |
| v1.5 | LLM integration: read-only delivered; constrained proposer withdrawn 2026-11-17 | §4.24; selector retirement done (Phase 1b) |
| future | Personalised volume-response model | idea only; shadow/gated (§13, Q28) |
| future | Athlete Feedback & Coaching (AFC) — deferred AFC-3 second cut | AFC-2, AFC-2i, AFC-3 and AFC-4 implemented 2026-11-13; physical iPhone report acceptance owner-confirmed 2026-11-14 (§4.33) |
| done (Phases 0–4, R1–R10, 6.0–6.7) | Native iPhone and watchOS client | Phase 0 complete 2026-11-07; Phases 1–2 complete and owner-confirmed on the physical iPhone (2026-11-07); Phase 3A closed 2026-11-08 (HealthKit readiness, physical acceptance owner-confirmed); Phase 4 closed 2026-11-08 (offline capture and replay, physical acceptance owner-confirmed); R1–R5 and R7–R11 closed (R11 delivered 2026-11-18); Phase 6.0–6.7 complete with physical Apple Watch acceptance owner-confirmed 2026-11-14 (§4.32); the AFC-2i session report is implemented. Apple PCC remains an optional AI-only network exception (§4.29; [`iOS client plan`](https://github.com/georgesdib/strength-app/blob/main/docs/plans/IOS-CLIENT-PLAN.md)) |

### 4.19.1 Deferred: web authentication and per-user data

**Status: backlog, not implemented. Temporary state: unauthenticated home-LAN HTTP (`DEC-WEB-03`, `LIM-57`).** The owner judged the full design overkill for now; this section is the agreed implementation proposal, not a claim that any part exists.

- **Auth store:** `data/auth.db` with `app_user` (id, username, password hash, `must_change_password`, disabled, timestamps), `session` (hashed token, user id, CSRF token, expiry, last seen) and `login_attempt` for rate limiting. Passwords use scrypt or Argon2id with a unique salt.
- **Private data:** one coach database per user at `data/users/<user-id>/coach.db`; no `user_id` columns added to the clinical schema. The authenticated request resolves the user's database. Move the existing `data/coach.db` into the first user's directory after a backup, never copy it into a shared store.
- **CLI-only provisioning:** `user create`, `user list`, `user enable/disable`, and `user reset-password <username>`. Reset requires **no old password**; it prompts for the new one twice or accepts `--password-stdin`, invalidates all sessions, and may set `must_change_password`. Local shell access is the admin boundary.
- **First user:** provisioned through the CLI with a temporary password, forced change at first login, and onboarding for birth date, gender and timezone. **Never commit the actual username, password, birth date or other profile values**; use placeholders in design docs.
- **Login and sessions:** username + password; server-side session token in the auth DB; `HttpOnly`, `SameSite=Lax`, `Secure` cookie when TLS is active; CSRF token; rate-limited failed logins; logout and password change invalidate sessions; unauthenticated APIs return `401`.
- **Profile onboarding:** require birth date and gender after first login. Store birth date (not age), gender as the agreed dropdown with `prefer not to say`, and IANA timezone. Do not use gender to compute load or volume; age remains wording/priority evidence only.
- **Home access/TLS:** Caddy or nginx terminates HTTPS; the app stays on loopback behind it or gains built-in TLS. Only the configured home hostname/origin is accepted. HTTPS is required before non-loopback credentials are accepted; no public-internet exposure.
- **Isolation and logs:** every API, import, export, backup and log query resolves the authenticated user. The current global Logs page must become per-user or admin-only.
- **Acceptance tests:** CLI create/reset/disable, hash verification, login/logout, forced password change, session expiry/invalidation, CSRF, rate limiting, per-user database isolation, profile onboarding, TLS/origin configuration, and non-loopback access.

### 4.20 Post-review follow-ups  (unscheduled)

Moved out of the strength-programme review so it can close. These are **not** v0.3 work.

1. **Prospective validation gate.** No current candidate. A model may enter a frozen prospective
   period only after it beats the fixed/persistence baseline in a retrospective walk-forward.
   The current continuity and fatigue models failed; they remain fixed/shadow-only. A prospective
   run is 8–12 weeks / 24–36 sessions with no retuning and no load effect.
2. **Parent-variant e1RM ratios.** Evidence review 2026-10-25: a ratio is a relative performance
   profile, **not** a weakness or injury measure. It may later be a descriptive prior/display
   aid with uncertainty, never a silent load conversion or targeting rule. Needs a formal parent
   relation and paired data. No schedule. See
   [PARENT-VARIANT-WEAKNESS-EVIDENCE.md](docs/PARENT-VARIANT-WEAKNESS-EVIDENCE.md).
3. **Weakness/injury targeting.** No positive targeting. A display-only own-history context is
   implemented. A gated testing plan is in
   [WEAKNESS-TARGETING-PLAN.md](docs/WEAKNESS-TARGETING-PLAN.md). Weakness targeting is gated by
   DEC-SELECT-05 (earliest after v1.3 / ~April 2027); injury targeting is unscheduled and remains
   constraint/penalty/ceiling only.

### 4.20.3 Weakness targeting test plan  (plan only; unscheduled)

[WEAKNESS-TARGETING-PLAN.md](docs/WEAKNESS-TARGETING-PLAN.md) defines the full test:

1. **Data:** 12 sessions for the target lift across 12 weeks, with snapshots, RIR and symptoms.
2. **Definition:** own-lift recent baseline minus current trend, with a pre-registered noise-aware
   threshold; never a parent-variant ratio or population norm.
3. **Retrospective screen:** fixed selection vs the targeting rule on the same chronological
   dates; screening only, not causal proof.
4. **N-of-1:** opt-in alternating fixed/targeted blocks, at least three pairs or report unknown,
   with stop rules for symptoms and guardrail lifts.
5. **Decision:** keep fixed, display-only, or bounded opt-in targeting after the N-of-1 result.
   Injury targeting stays unscheduled; injury remains exclusion/penalty/ceiling only.

No implementation, no automatic substitution and no load effect follows from this plan.

**Open decisions register**

| decision | state | where |
|---|---|---|
| Prospective validation of a future continuity/fatigue candidate | gate only; current candidates rejected | §4.20.1, DEC-VALIDATION-01 |
| Parent-variant e1RM ratios | unscheduled; display-only profile/prior, not weakness | §4.20.2; `PARENT-VARIANT-WEAKNESS-EVIDENCE.md` |
| Weakness targeting | plan only; deferred to after v1.3 / ~April 2027 | §4.20.3, `WEAKNESS-TARGETING-PLAN.md`, Q22, DEC-SELECT-05 |
| Selection A/B boundary (pause/narrow, SSB/high-bar) | dormant policy decision; current default is conservative (A only same exercise) | Q21, docs/SELECTION-COMPARABILITY.md |
| Cardio model | v1.6 | §4.13, Q14 |
| Low-bar competition squat and the weekly spinal cap | **closed 2026-10-25**: counts cost 1; cap raised 3 → 6; bench+hinge uses sumo 2.5 | `DEC-SPINE-05`, Q24, LIM-44 |

### 4.24 Future LLM integration workstream  (superseded in part 2026-11-14; see §4.34)

**Status: superseded in part 2026-11-14; not implemented.** The read-only half of this workstream —
architecture and contracts, the shared context/evidence builder, the athlete analyst, the programme
explainer, the MCP server and the Apple-platform work — is specified in §4.34 and the portfolio
[Training Intelligence plan](https://github.com/georgesdib/strength-app/blob/main/docs/plans/TRAINING-INTELLIGENCE.md).
Rows 1–3 and the exit gate below are superseded; the MCP clause of Iteration 2 is superseded; the
constrained proposer (rows 4–5) was **withdrawn 2026-11-17** and needs a new decision. Phase 1b, the
outbound-data inventory (plan §8.1) and the evaluation gates (plan §9) remain in force. No prompt,
source, schema, API, UI or training-rule change is part of what remains; the detailed requirements,
privacy rules and acceptance criteria live in
[`docs/LLM-INTEGRATION-PLAN.md`](docs/LLM-INTEGRATION-PLAN.md), whose status banner records the same
scope. The analysis below is kept as the historical record of the boundary.

The future architecture separates three capabilities that share one deterministic evidence
layer but have different permissions:

- **Athlete analyst** — read-only progression, programme-status and priority-coverage reports,
  with evidence links and explicit data-quality limits.
- **Programme explainer** — concise and expandable explanations of the actual persisted
  prescription, its modifiers and its warnings; no prescription change.
- **Constrained proposer** — structured structural proposals from canonical ids and allowed
  choices; Python resolves loads and re-validates; the deterministic baseline remains visible;
  the user must explicitly approve; shadow/opt-in rollout only.

AFC (§4.33, [`AFC plan`](https://github.com/georgesdib/strength-app/blob/main/docs/plans/AFC.md)) is the deterministic producer of the metrics,
observations and evidence these capabilities consume. The shared context/evidence builder in
Iteration 1 phase 2 serialises AFC evidence ids; it does not recompute adherence, VBT, readiness or
volume metrics. There is one evidence schema, defined in the AFC plan §6 and section 4 above.

The deterministic engine, taxonomy, comparability rules, history and prescription validation
remain authoritative. If no LLM is configured, the analyst/explainer/proposer functions are
simply unavailable; deterministic training is unchanged. External calls require the
field-level outbound-data inventory and sensitive-field safeguards in
[`docs/LLM-INTEGRATION-PLAN.md`](docs/LLM-INTEGRATION-PLAN.md) §8.1; structured injury,
symptom and health data are not assumed non-sensitive.

### Iteration 1 — practical capabilities, minimal infrastructure

Iteration 1 reuses the existing LLM client, structured proposal path, feature calculations,
repositories, prescription provenance, validators and trace. The shared deterministic
context/evidence builder is **new Phase 2 work**, not an existing component. Iteration 1 does
**not** require a vector database, RAG, embeddings, tool framework or autonomous agent
framework.

| phase | scope | depends on | status |
|---|---|---|---|
| 1 | Architecture and contracts: capability boundaries, permissions, context/evidence schema, prompt/schema versions, privacy, iteration boundary | owner approval | **superseded by INT-1** (portfolio plan) |
| 1b | **Retire the minimal LLM exercise selector** as a separate work item: remove only selector-specific chooser/CLI/API/UI/engine/tests/docs plumbing; preserve shared LLM client/config, narrative/proposal, deterministic selection, taxonomy, comparability, class-B confirmation and history; acceptance in plan §8.2 | the approved Training Intelligence contracts (INT-0/INT-1); **independent of the proposer** | **planned** |
| 2 | **New** shared context/evidence builder + athlete analyst: lift progression, programme status, strength/power/longevity review | phase 1; existing features/repositories/provenance; the AFC evidence contract (AFC-2/AFC-3) | **superseded by INT-2/INT-3** |
| 3 | Programme explainer: persisted prescription, modifiers, baseline/previous comparison, concise + detailed | phase 2; prescription provenance | **superseded by INT-2 (facts) + INT-5 (narration)** |
| 4 | Constrained proposer in shadow: structured schema, deterministic validation, Python load resolution, baseline comparison; no application | phases 1–3; existing proposal/validator path | **deferred/unscheduled** (write capability; new decision required) |
| 5 | Opt-in approval + evaluation: diff UI/CLI, explicit approval, provenance, shadow/opt-in gates; no selector work | phase 4; phase 1b; approved gates; privacy review | **deferred/unscheduled** with row 4 |
| exit | Iteration 1 exit gate: selector retired; analyst/explainer accepted; proposer shadow/opt-in gates green; no-LLM path tested | phases 1, 1b and 2–5 | **superseded** (INT-1 to INT-8 carry their own gates) |

**Dependency order (superseded for the read-only work):** v1.5 cardio/calibration work, then phase 1,
then 2 → 3 → 4 → 5; phase 1b runs after phase 1, in parallel with 2/3 if useful, and must finish
before the Iteration 1 exit. The current read-only order is INT-1 → INT-2 → INT-3 (§4.34); phase 1b
still precedes any server-side narration phase.
No capability code starts before the owner approves its contracts. The former proposal phases
4–5 are withdrawn with `DEC-LLM-09`; no write path runs.

**Selector retirement is not a refactor and not a proposer dependency.** The deterministic
selection engine, taxonomy, movement-family classifications, comparability rules, validation,
class-B `selection_confirmed` confirmation and history remain. Only the minimal LLM chooser is
removed. The proposer was withdrawn 2026-11-17; `DEC-LLM-09` is closed, not deferred.

**Wider proposal licence — withdrawn.** With the proposal surface removed there is no menu or
approval path to extend. If a write capability is ever revisited, it needs a new decision and the
same structural-only boundary.

### Iteration 2 — evidence retrieval and advanced architecture (conditional)

Iteration 2 begins only after the Iteration 1 exit gate. It starts with a needs assessment, not
with technology adoption. RAG, semantic/hybrid retrieval, a vector database, advanced
orchestration/tool use and an owner-operated MCP server over Tailscale are candidates, not
requirements; any one may be rejected. A vector database is permitted only if the retrieval
benchmark shows a simpler deterministic/keyword or hybrid approach is insufficient. **Superseded
in part (2026-11-14):** the MCP server is no longer an Iteration 2 candidate — it is planned as
INT-1/INT-2 (§4.34) with application authentication, and Tailscale remains reachability only. The
retrieval, vector-store and orchestration candidates are unchanged and remain conditional.

| phase | scope | depends on | status |
|---|---|---|---|
| 6 | Needs assessment: recurring gaps, trusted corpus, retrieval requirements, simpler alternatives, MCP/Tailscale tool boundary and authorization, benchmark, cost/latency/privacy/maintenance case | Iteration 1 exit gate; owner authorisation | **conditional** (MCP clause superseded by INT-1) |
| 7 | Advanced component trial: one approved component at a time (RAG, hybrid retrieval, bounded orchestration or MCP transport), off by default, baseline comparison | phase 6 decision; privacy review | **conditional** (MCP transport clause superseded by INT-1) |

**Proceed criteria for any Iteration 2 component:** documented recurring need; simpler
alternative tested; measurable benefit on a pre-registered evaluation set; acceptable cost,
latency, privacy and maintenance; no safety or deterministic-fallback regression; owner approval
and a new decision. Any MCP component must also be tailnet-only, application-authenticated,
read-only until separately approved, and prohibited from direct writes/prescription commitment.
No dates are assigned.

**Non-goals:** autonomous workout replacement, LLM arithmetic, LLM vetoes, unsupervised tool
use, self-directed database writes, adopting RAG/vector databases/agent frameworks merely
because they exist, a new provider/dependency without a demonstrated need, and any change to the
fixed programme methodology. Analyst and explainer outputs do not change training; proposer
changes require explicit approval.

**Exit gates:** Iteration 1 as above; Iteration 2 phase 6 owner disposition; phase 7 measured
benefit and no regression. No phase claims that prose quality or acceptance rate proves better
coaching.

### 4.28 Exercise-level symptom research (Phase 3)  (planned; unscheduled)

**Status:** planned research, not approved for implementation and not scheduled. No code,
schema, model or behaviour change exists in this phase. Today follow-up:
`injury_attribution_phase3`.

**Question.** Does a particular exercise show a different rate of later regional symptoms
than comparable sessions without it, after plausible confounders? This is a descriptive
association question, not a causal or diagnostic one.

**Data.** Mechanical exposure from `clean_set` working sets through the region links in
`config/injuries.v1.yaml`; the existing 0–3 regional symptom readings and follow-up window;
and the training-day/fragment grouping. Athlete attribution is **not** the label source; at
most it is a separate interpretability label.

**Method.** Pre-register the question, outcome window, confounders, missingness rules and
analysis before looking at results. Report exposure and symptom counts, missingness,
uncertainty and sparse-data states. The result stays descriptive.

**Out of scope.** No predictor, risk score, diagnosis, suitability rating, constraint,
selection, load or prescription change. No new symptom scale. No automatic adoption; any
later use needs a separate decision and validation.

**Prerequisites.** Enough prospective symptom and exposure data, a written pre-registration
and a separate owner decision to start. Phase 3 is independent of the closed Phase 1–2 plan
and is not a reason to reopen it.

### 4.33 Athlete Feedback & Coaching (AFC)  (AFC-2, AFC-2i, AFC-3 and AFC-4 implemented 2026-11-13)

**Status:** AFC-2, AFC-2i, AFC-3 and AFC-4 are implemented 2026-11-13; physical iPhone report
acceptance was owner-confirmed 2026-11-14.
Beyond AFC-2 this section is documentation only: no schema, API, rule or threshold change is part
of it. The full plan is [`AFC plan`](https://github.com/georgesdib/strength-app/blob/main/docs/plans/AFC.md).

AFC-2 was backend and web UI work; AFC-2i is a native iOS presentation phase over AFC-2's report.
Neither is Phase 7. Phase 7 is the existing LLM narrative layer (status-table row 7) and keeps that
designation.

**Purpose.** Turn the training, adherence, VBT, readiness and performance data the server already
computes into reliable, evidence-linked and actionable feedback. Deterministic calculations stay
authoritative, feedback stays traceable to stored rows, and missing data is reported as unknown
rather than as poor performance.

**Composition, not reimplementation.** AFC adds no second calculation of any metric owned by
`adherence.py`, `adherence_analytics.py`, `attendance.py`, `volume_budget.py`, `vbt_analysis.py`,
`vbt_performance.py`, `residual.py`, `readiness_feedback.py`, `session_feedback.py` or
`monitoring_analysis.py`. It composes them, starting from `workout.summary()`, which already
returns completion, strength, dose, special exposure, feedback, ratios, comparison, adherence and
VBT for a completed workout.

| phase | scope | data change |
|---|---|---|
| AFC-2 | post-workout report: shared evidence contract, end-screen adherence, evidence and real quality flags, removal of the duplicate `summary.completion` — **completed 2026-11-13** | none |
| AFC-2i | native post-workout report: render the AFC-2 summary/evidence payload after completion and from History — presentation and navigation only — **implemented 2026-11-13** | none |
| AFC-3 | longitudinal observations: repeated RIR deviation, repeated incomplete work, VBT residual deviation — **completed 2026-11-13**; second cut (stagnation) deferred to AFC-5 | small, append-only |
| AFC-4 | web UI coaching and nudges on existing hosts, with suppression — **implemented 2026-11-13** | small, append-only |
| AFC-5 | evidence-gated prescription adaptation — **scoped 2026-11-13, docs only**; separate and gated; does not block AFC-2 to AFC-4 | separate |

**AFC-2 is completed** (2026-11-13): `features/evidence.py` supplies deterministic evidence
ids, the summary's duplicate `completion` block is gone with `adherence` as the single metric
source, `quality.flags` is populated, the end screen renders adherence and data quality, the
readiness follow-up reads `adherence.analyse`, and the three Phase 5A guards from
`DEC-AFC-02` are in place. AFC-3 and AFC-4 are implemented below.

**AFC-2i is implemented** (2026-11-13; physical iPhone acceptance owner-confirmed 2026-11-14). It consumes the
delivered `GET /api/workout/<id>/summary` payload through the transport-only iOS facade —
`adherence`, `vbt`, `feedback`, `quality.flags` and `evidence` — in the existing workout
completion flow, and adds no calculation, capture, endpoint contract, schema or prescription change
(`DEC-AFC-03`, [`AFC plan`](https://github.com/georgesdib/strength-app/blob/main/docs/plans/AFC.md) §7). It depends on AFC-2 only, not on AFC-3 or AFC-4,
and it must not manufacture a coaching observation the payload does not carry. The summary now
carries at most one deterministic observation (`DEC-AFC-08`); the web end screen renders it, and
the iPhone report is a follow-up view change.

**AFC-3 is completed** (2026-11-13, first cut): `features/observations.py` reads the existing
`adherence` and `vbt_performance` payloads, applies `config/observations.v1.yaml` (3 of the last
5 comparable sessions, 8-week window) and reports to `GET /api/observations` and
`strength-coach observations`; observations are appended to the new append-only `observation`
table, idempotent on the evidence id, and abstentions carry a reason; excluded sessions
(imported, abandoned, technique, voided, adherence-unavailable) are counted and surfaced. VBT
inherits the cohort gate. `workout.summary()` is unchanged. The second cut — stagnation and
"improving performance with stable effort" — is deferred to AFC-5 (`DEC-AFC-07`).

**AFC-4 is implemented** (2026-11-13): Today carries at most one nudge promoted from an AFC-3
observation, with dismiss (per evidence window) and 14-day snooze recorded append-only in
`maintenance_review`; Progress adds a programme-KPI panel composed from attendance, volume,
adherence and the observation count. No notification channel and no new metric
(`DEC-AFC-05`).

**Tracked follow-ups.** The remaining AFC work is recorded as periodic review tasks rather than
prose: `afc_device_acceptance` (closed 2026-11-14, owner-confirmed) and `afc_5a_historical`
(AFC-5a, waiting until 2027-01-23). They appear in the review panel and change nothing by
themselves.

**Relationship to the critique rubric.** AFC is the canonical post-workout adherence
evaluation. The deterministic critique rubric is retired from the runtime (`DEC-EVAL-09`): no
session is scored, no review step follows completion, and its RIR and duration items are
superseded by `adherence` and `feedback`. Historical rows stay read-only and no rubric item feeds
a prescription or AFC metric.

**AFC-1 is dissolved.** Attendance is already computed, rendered and correctly labelled as
target-based; weekly set-volume attainment already exists in the volume budget. Planned-session
compliance stays out of scope under `DEC-W7-01` ([`LIM-05`](docs/LIMITATIONS-REGISTER.md) is
unchanged). The programme-level KPI panel is part of AFC-4.

**Phase 5A.** AFC is read-only composition and changes no instrumented definition: `attendance.pct`,
the prospective flags, monitoring/exposure/calibration configuration, or the end-screen capture
controls for session RPE, duration and productivity. AFC-2 extended `workout.summary()` and
`summary.js`; no feature module reads `summary()`. AFC-2i reads the same payload after completion
and touches no capture surface, so it stays outside the instrument.

**Out of scope.** Native iOS or watchOS *calculation, capture and instrumentation* — AFC-2i renders
the report only — a watchOS report, cardio models, VBT calibration, the training engine, automatic
adaptation, and the LLM capabilities in §4.24.

### 4.34 Training Intelligence — read-only capability layer and MCP server  (INT-1 and INT-1b implemented 2026-11-14)

**Status: INT-1 to INT-8 and INT-11 closed or delivered (INT-4c parked); INT-10 closed 2026-11-18 with its device acceptance waived (shipped in StrengthApp v1.2); INT-9 and INT-12 deferred; INT-13 is iOS-only and owner-closed 2026-11-17.** The read-only
capability layer, the canonical envelope, typed requests, the execution service, configuration
bounds and their tests exist in `strength_coach/intelligence/`; INT-1b adds the separately runnable
MCP server (`strength_coach/intelligence/mcp/`, Streamable HTTP, revision 2026-07-28 with legacy
clients), dedicated MCP client tokens with CLI provisioning, two tools (`get_training_overview`,
`get_session_details`) and one resource (`strength://athlete/profile`). The MCP SDK is an optional
extra and only the transport imports it. See
[`docs/INTELLIGENCE-IMPLEMENTATION.md`](docs/INTELLIGENCE-IMPLEMENTATION.md), including the
performance baseline — the development Mac and, separately, the deployment host (p50 3.10 s /
p95 3.17 s at 377 sessions, 2026-11-14). That host measurement exceeded the original
ADR-INT-010 one-second threshold; the owner's latency-aware budget (T-1, 2026-11-14) superseded
that gate and the transport is enabled on the trusted LAN. INT-2
delivered the rest of the read-only catalogue on 2026-11-14 and INT-3 delivered the weekly review, its
REST route and the iOS read surface; **INT-3 is closed 2026-11-15**. INT-5 delivered the server model
provider, narration and its routes; INT-6 delivered server/web chat. Aggregate evidence producers for
the aggregate capabilities remain deferred. INT-11 (local docs/code Explain) is implemented and closed with documented limitations: index, retrieval, explain endpoint, background startup refresh, web/iOS tabs and a 15-question evaluation; programme-block archive noise remains; the owner closed the iOS device-acceptance and release-tag items on 2026-11-17. INT-12 (web search/RAG) is deferred and has no backend code.

The iOS-side phases are tracked in the canonical [Training Intelligence plan](https://github.com/georgesdib/strength-app/blob/main/docs/plans/TRAINING-INTELLIGENCE.md): INT-7/7b/7c (Siri, Shortcuts, HomeKit, Action button) and INT-8 (plan review) are closed; INT-9 waits for iOS 27.3; INT-10 is closed (device acceptance waived, shipped in StrengthApp v1.2); INT-4c is parked on the PCC entitlement.

**Audit remediation 2026-11-14:** immediate token revocation/rotation without restart, a
structured metadata-only audit record per invocation, a configurable tool timeout and result-size
cap, a dedicated systemd unit with a deployment guide (installed on the ODROID 2026-11-15), and a live HTTP
integration test. The implementation page records the semantics and limitations.

**INT-2 delivered 2026-11-14:** seven further read-only capabilities (exercise progression,
readiness history, adherence analysis, persisted prescription, VBT analysis, programme block
summary, period comparison) and two more resources (`strength://programme/current`,
`strength://overview/current`), all composing existing owners. ADR-INT-010 later accepted the
latency-aware budget and enabled the transport; INT-2 adds no caching, no new REST route and no
model.

**Phase 1b selector retirement (2026-11-15):** the minimal LLM exercise-variant chooser and its CLI/API/UI/engine plumbing are removed; deterministic selection and class-B confirmation remain.

**INT-6 web chat delivered and closed (2026-11-15):** Programme Intelligence Chat posts up to 20 turns to `/api/intelligence/chat`, where the server supplies a fresh six-capability fact dossier. Session-only browser memory, only the recent ten messages, an 18k fact cap, a separate suggestions block, advisory warnings and daily budget. Four-case multi-turn matrix; model tool calling deferred.

**INT-5 server narration delivered (2026-11-15):** intelligence narrate and the web Narrate view
cover every registered capability, with a daily token budget, advisory number warnings, a
ten-capability evaluation harness and MCP parity. Phase 1b retired the old LLM exercise chooser.
Multi-tool orchestration is deferred by owner decision. Web access, web citations and RAG are deferred for both the web UI and iOS.

**INT-5 first slice (2026-11-15):** a **Narrate** web view calls `POST /api/intelligence/narrate` for any registered capability; the CLI equivalent remains. The validated narrative, trace and no-model error are shared. Multi-tool orchestration, evaluation, budget, MCP parity and Phase 1b retirement remain; the server needs a model key.

**INT-5 CLI first slice (2026-11-15):** `intelligence narrate` explains any
registered capability through the existing Null/OpenAI-compatible provider, validates the JSON
narrative against the envelope facts and records a run/run_event trace. Multi-tool orchestration,
evaluation, budget, MCP parity and Phase 1b retirement remain; the server needs a model key.

**INT-4e plan-aware chat delivered (2026-11-15):** a default-off plan-data
toggle adds prescription, programme summary and adherence to on-device and DeepSeek chat. Answers
are structured with a separate suggestion block; suggestions are proposals, not applied. The three
backend routes are deployed. The owner confirmed both providers; on-device may abbreviate a long prescription answer though the raw facts are complete.

**INT-4d DeepSeek chat delivered (2026-11-15):** a chat-only model choice,
direct from the iPhone, key in the Keychain, OpenAI-compatible tool loop over the five capabilities,
soft verification and no fallback. Weekly and overview explanations stay on-device. The owner
confirmed it on the iPhone with a real key; the four-round cap and error mappings are unit-tested.

**INT-4b chat delivered (2026-11-15):** a dedicated on-device Chat screen behind a separate
default-off toggle, with suggested prompts, non-streaming answers, a sources line, session-only
transcripts and grounding against the envelopes the tools returned. The five tools are registered
with a 5-to-3 context fallback; session details resolve the latest completed session. The manual
device matrix passed (five tools, refusal and transcript clearing). No UI test by owner decision.

**INT-4 delivered (2026-11-15):** the on-device narrative is available on the weekly review and the
Progress overview behind a default-off toggle, with availability reasons, detail presets, a compact
facts projection, a structured-number grounding validator, a token budget with trimming and a
deterministic fallback. The five native tool adapters are implemented and tested as an adapter
surface but not registered: their schemas overflowed the 8,192-token window at the Detailed preset.
The budget trims and retries; the grounding check accepts percentages and thousands separators and
ignores the digit in `e1RM`. The device run passed and no UI test is required by owner decision;
conditional tool registration remains a tuning item.

**INT-4 read surface (2026-11-15):** the iOS intelligence routes for overview, exercise progression,
readiness and session details are implemented alongside the weekly review, so the native adapter
can cover all five capabilities.

**INT-3 closed 2026-11-15:** `get_weekly_review` composes the deterministic Monday-Sunday
sections (activity, adherence, sessions, progression, volume, readiness coverage/direction,
programme, gated observations) from their owners, and the additive iOS read route
`GET /api/ios/v1/intelligence/weekly-review` returns the envelope unchanged under the existing
device bearer auth. Acceptance evidence is the golden fixture, the empty and imported-only week
tests, and the model-free screen. The iOS `StrengthCore` envelope/adapter and the Progress → Weekly review screen
were delivered on 2026-11-15 in the StrengthApp repository. The REST entrypoint and the MCP process
both open SQLite read-only; raw readiness fields are rejected over MCP unless the deployment sets
`allow_sensitive_readiness`, and the weekly review reports `week_complete`/`week_partial`. The
intelligence branch was merged into `development` on 2026-11-15.

The canonical cross-repository plan, audit, contract and decisions are in the portfolio
repository: [plan](https://github.com/georgesdib/strength-app/blob/main/docs/plans/TRAINING-INTELLIGENCE.md)
and [contract](https://github.com/georgesdib/strength-app/blob/main/docs/contracts/TRAINING-INTELLIGENCE-CONTRACT.md).
Owner approval of the plan's section 13 decisions remains required before the transport phase.

**MCP rollout follow-ups (updated 2026-11-14).** The extended HTTP benchmark on the ODROID
measured p95 6,201 ms (session details), 4,058 ms (overview), 3,800 ms (programme) and 1,663 ms
(readiness). The owner accepted a latency-aware budget (T-1) and the **transport is enabled on
the trusted LAN with the full tool catalogue**. The original one-second blanket gate is
superseded by T-1; existing benchmark numbers remain the reference until T-3 remeasurement.

- **C-1 - Automatic maintenance worker (done 2026-11-15).** Installed on the home host:
  `strength-analytics-maintenance.service` and `.timer` are enabled, the timer runs on boot +5
  minutes and every 15 minutes, and the web unit's `ExecStartPost` triggers one reconciliation
  after a restart. The first run (2026-11-15 08:15) exited 0 and `/api/analytics/status` reports
  core ready/verified. There is no long-lived worker: each run invokes this checkout's current
  code and venv, so a `git pull` plus a web restart is picked up on the next tick.
- **T-1 - Owner latency decision (accepted 2026-11-14).** Fast capabilities target p95 ≤ 500 ms;
  slow and very_slow target p95 ≤ 7 s and remain callable without a hard latency rejection; the
  server tool timeout is 20 s. ADR-INT-010 now records this budget and the transport is enabled.
- **T-2 - Full catalogue with transparent latency metadata (implemented).** All ten capabilities remain
  discoverable and callable through `tools/list`; slow capabilities are **not hidden**. Each tool
  description carries its measured HTTP p95 and classification (fast / slow / very_slow), plus
  guidance to prefer fast tools, avoid repeated expensive calls, and never trade correctness for
  latency. The metadata is one module (`strength_coach/intelligence/latency.py`) and is explicitly
  a historical measurement, not a runtime guarantee. T-2 no longer depends on hiding slow tools;
  transport enablement still depends on T-1.
- **T-3 - Optimise the slow capabilities (closed 2026-11-14, first pass).** Bounded the
  deload flare lookup, cached readiness config loading and reused one summary rule context. HTTP
  p95: overview 4,058 -> 672 ms, programme 3,800 -> 278 ms, readiness 1,663 -> 377 ms; session
  details 6,201 -> 5,684 ms and remains very_slow within the accepted 7 s budget. Latency metadata
  updated from the new run. T-3 is closed as a first pass; **T-3a** (optional, not started) covers
  further session-details work. It is not a blocker for the full catalogue.

The items are compatible: T-1 sets the operational budget, T-2 is a rollout/communication change,
C-1 keeps materialisation current, and T-3 improves latency. The LLM objective remains open until
T-3 is measured and the transport decision is reviewed; existing benchmark numbers stay valid
until that remeasurement.

**Operational status (2026-11-15).** The MCP server runs under `strength-intelligence-mcp.service`
(installed the same day with `deploy/install-intelligence-mcp.sh`, user `dsh`, host-specific
paths), enabled at boot, from the production checkout's virtual environment on `10.0.0.44:8765`
(the LAN address; loopback is no longer bound). The `allowed_hosts` list contains `10.0.0.44:*` and
`odroid.local:*`; a mismatched Host is rejected with 421 even with a valid token. Full tool
catalogue, token file under the checkout's git-ignored config. It reads the production database
read-only; the unit grants `ReadWritePaths` on the data directory because SQLite WAL needs
`-shm`/`-wal` even for a read-only connection. Validated over real Streamable HTTP on 2026-11-15:
all ten capabilities answered, `get_weekly_review` 623 ms and `get_session_details` 5.7 s.
**Migration collision resolved:** the production database's 0060 is development's
`0060_plank_variants.sql` (checksum 7ed6); the analytics migrations had reused 0060-0062. They are
renumbered **0061-0063** on `development`, so the production schema applies cleanly without
deleting the recorded row. A fresh copy was migrated and built successfully after the renumber.
T-3 first pass is implemented and remeasured: bounded deload flare lookup, cached readiness
config loading and one summary rule context. Overview is down to 672 ms p95, programme 278 ms,
readiness 377 ms; session details is 5,684 ms and remains very_slow within the accepted 7 s budget.
T-3 is closed as a first pass; T-3a is the optional session-details follow-up. The production
cutover steps are in [`docs/PRODUCTION-DEPLOYMENT.md`](docs/PRODUCTION-DEPLOYMENT.md).

**Scope.** A provider-neutral capability layer over the existing services, a separately deployable
read-only MCP server (Streamable HTTP, authenticated, tools and resources only), an additive read-only
iOS intelligence surface, Weekly Training Review, and optional on-device/server narration. Every
metric is composed from its existing owner; there is no second calculation and no new evidence schema.

**Backend areas.** Created in INT-1: `strength_coach/intelligence/{envelope,errors,methods,context,config,auth,registry,service}.py`,
`strength_coach/intelligence/capabilities/`, `config/intelligence.v1.yaml` and `tests/test_intelligence_*.py`.
Created in INT-1b: `strength_coach/intelligence/mcp/`, `intelligence/{tokens,resources}.py`, the
`intelligence` optional extra, the `strength-intelligence-mcp` console script, `tools/intelligence_benchmark.py`
and the MCP tests. Created in INT-5: `strength_coach/intelligence/model/` (narrative, chat, evaluation harness).
Not created: a packaged deploy unit (systemd example); deployment is documented in the implementation
page instead. Implemented: the INT-11 local knowledge index, retrieval and explain surfaces. Planned only: INT-12 web-search/RAG.

**Hard constraints.** Read-only: no tool, route or capability may create, edit, void, start, complete
or prescribe. SQLite is opened read-only in that process. No free-text notes, symptom narratives or
unnecessary health values by default. No MCP prompt, sampling, roots or subscriptions. No beta Apple
API. No change to workout execution, prescription/readiness/fatigue algorithms, cardio, migrations or
existing endpoint shapes.

**Relationship to §4.24 and §4.33.** This workstream **supersedes the read-only part of §4.24** and
the Apple Intelligence/PCC items in the iOS client plan; §4.24 keeps the historical record and its
Phase 1b selector retirement, which is still required before a server-side narration phase. The
constrained proposer is deferred/unscheduled. §4.33 (AFC) remains the deterministic producer of the
evidence this layer serialises. This workstream adds no model capability to Iteration 1 and does not
reopen any completed phase.

### 4.37 Resolver prescription structure and programme context  (proposed 2026-11-19; WP0 complete)

**Status authority.** The [portfolio plan](https://github.com/georgesdib/strength-app/blob/main/docs/plans/RESOLVER-PRESCRIPTION-STRUCTURE.md) is canonical for behaviour and acceptance. This section tracks backend implementation only. **WP0 is complete (2026-11-19):** the role-quality config, synthetic fixtures and `DEC-RESOLVER-21` are in; no runtime code, migration or wiring has changed. WP1–WP8 are not started.

**Scope.** Ordered planned set groups over a frozen plan; execution substitutions and additions instead of plan editing; one top-set tri-state with default `off`; a server-computed programme header reused by Today and intelligence facts; a deterministic role-aware evaluator hierarchy; order-based actual-sequence analysis without stored set roles; a deterministic candidate shortlist; and a later phone gateway for offline watch execution.

**Work packages.** WP0 decisions and fixtures (done 2026-11-19); WP1a server ordered groups; WP1b frozen plan, execution substitutions and migration `0058`; WP2 iPhone, Watch and web groups, prefill and execution view; WP3 tri-state intent; WP4 programme header and intelligence facts; WP5 actual data and derived structure; WP6 evaluator hierarchy; WP7 candidate ordering; WP8 phone gateway. The full dependencies and exit gates are in the plan §6.1.

**Release trains.** Release A is the coordinated cutover (WP1a, WP1b, WP2, WP3, WP4; finish or abandon in-flight workouts first). Release B is server-only actual data and evaluation (WP5, WP6, WP7; WP6/7 gated on the fixed-history comparison and owner review). Release C is the additive phone gateway (WP8).

**Non-negotiables.** No composite score, no per-muscle volume targets, no named phases, no stored set role on the wire, no client-computed loads. The top-set default is `off`; the evidence review's opt-in conclusion is retained. Migration `0058` is additive and nullable on `workout_set` and `clean_set`; no historical rewrite.

## 5. Known gaps and risks

This section keeps **no list**. Every accepted limitation is registered with an id, a status and
a "revisit when" in [`docs/LIMITATIONS-REGISTER.md`](docs/LIMITATIONS-REGISTER.md); forward-looking
work lives in §4.19 and the v1.5 plan in §4.13a. The table that used to sit here was folded into
that register on 2026-10-26 — `LIM-45`–`LIM-49` are its new rows, and the rest already existed
(`LIM-07`/`LIM-10` duration and timestamps, `LIM-14` spinal cost, `LIM-24`/`LIM-43` e1RM bias).
Two rows that described *planned work* were not limitations and did not move: calibration
comparability is tracked in §4.14, and the cardio impulse (§4.13a A2/A3) was retired on 2026-11-18
(`DEC-LONGEVITY-03`).

## 6. Idea backlog (not approved, not scheduled)

Recorded so genuinely open ideas are not lost, explicitly **not** commitments. Delivered and
rejected ideas are recorded in §6.1; the LLM workstream lives in §4.24.

- Readiness composite driven by `metric_definition`: make the daily metric list, direction,
  weight and baseline config/registry-driven rather than hard-coded. Not delivered: the table
  is used for measurements; daily readiness needs weight/role/baseline metadata and shadow
  validation. The daily input cadence and the score's non-authoritative status are unchanged.
- Personalised volume-response model — future, shadow-only: estimate productive/tolerable
  volume per group/lift with calibrated uncertainty and a pre-registered prospective gate; no
  prescription change until validated. Fixed budget and safety guards remain authoritative.
  Idea only; see `docs/archive/VOLUME-MODULATION-PLAN.md` §13 and Q28.
- Athlete Feedback & Coaching (AFC) — programme KPIs, post-workout report, longitudinal observations and nudges (§4.33; [`AFC plan`](https://github.com/georgesdib/strength-app/blob/main/docs/plans/AFC.md); not scheduled).

### 6.1 Delivered or rejected from the former backlog

- Set-based weekly volume auditing — delivered by movement pattern (`features/volume.py`);
  per-muscle-group accounting is not planned because the programme is organised by movement
  pattern and no exercise-to-muscle mapping exists.
- Rotation scoring split by session provenance — delivered (`DEC-CRITIQUE-02`;
  `critique/rubric.py`, since retired with the rubric in `DEC-EVAL-09`): app-assigned rotation is
  neutral, self-directed churn is penalised.
- Top set + back-off — delivered as an opt-in resolver structure; the evidence review found no
  direct trial against the default 4-5 × 3-5 @ RIR 2-3 prescription and does not justify making
  it the default. See [TOP-SET-BACKOFF-EVIDENCE.md](docs/TOP-SET-BACKOFF-EVIDENCE.md).
- Per-set/rep manual velocity overrides — delivered (`vbt_override`, append-only); the
  per-lift override with expiry idea is dropped.
- Grip-strength readiness input — rejected (`DEC-GRIP-01`); grip remains a periodic
  measurement, not a daily readiness input.

## 7. How to change this roadmap

- Phase status changes go in the table, in the same commit as the work.
- New phases get a number and an acceptance criterion before any code is written.
- Anything that changes a rule, a threshold that affects a load, or a recorded decision must
  also append to [`docs/DECISIONS.md`](docs/DECISIONS.md).
- Personal goals, injuries and preferences are **not** recorded here — this repository is
  public. They live in the git-ignored `private/`.

## Related

- **UI surface:** [docs/UI-MAP.md](docs/UI-MAP.md)
- **Evidence:** [docs/REFERENCES.md](docs/REFERENCES.md)
- **Decisions:** [docs/DECISIONS.md](docs/DECISIONS.md)
- **Open questions:** [docs/OPEN-QUESTIONS.md](docs/OPEN-QUESTIONS.md)
- **Roadmap:** this file
