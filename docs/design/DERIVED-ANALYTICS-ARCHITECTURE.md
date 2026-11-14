# Derived analytics layer — repository audit and architecture

**Status:** design proposal, 2026-11-14. No runtime behaviour, schema, cache or analytical
semantics were changed by this document. It records an audit of the current analytics and a
proposed shared, persistent, rebuildable derived layer for the backend, web UI, iOS and the
Training Intelligence capabilities.

Audited at: backend `llm-integration` `de686c7`, portfolio `llm-integration` `de7dd18`,
iOS `llm-integration` `43292bb`. Measurements below are from the ODROID-class deployment host
(Linux 6.18.44 aarch64, 4 cores, Python 3.13.5) on a synthetic 377-session / 6,786-set database,
using the method in `tools/intelligence_benchmark.py` and the §18 profiling in
`docs/INTELLIGENCE-IMPLEMENTATION.md`.

## 1. Executive summary

The backend has no persistent analytical layer. Every dashboard, report and capability reads
`clean_set`/`session` rows, re-derives per-set e1RM and other fields, and re-aggregates the same
history. On the deployment host this makes an overview request 2.7 s and a monitoring report
about 49 s, and it repeats the same work in several modules with independent formulas.

The proposal is a **selective, versioned, rebuildable materialisation** owned by the existing
analytical modules: per-set derived values, per-session/exercise aggregates, per-ISO-week spinal
and volume aggregates, and result snapshots only for the very expensive reports. Owners keep
their formulas and output shapes; the tables are an accelerator read through the same public
functions. Source data remains append-only; derived rows are disposable and rebuilt from source
whenever a source revision or methodology version changes.

The layer removes the repeated full-history scans and the per-set e1RM recomputation. It does
not remove the remaining costs of report assembly, readiness queries or the first access after
a cold start; those are listed as residual bottlenecks. No improvement is claimed beyond the
measured current numbers; every target in §7 is a benchmark to be established by the phased
implementation.

## 2. What the audit found

### 2.1 Layering today

| Layer | Location | Role |
|---|---|---|
| Source data | `clean_set`, `session`, `readiness_day`, `session_feedback`, `symptom_log`, `prescription` | Append-only facts; single authority for performed work |
| Analytical owners | `strength_coach/features/*`, `strength_coach/critique/facts.py`, `strength_coach/rules/*` | Compute metrics and interpretations; each owns its definition |
| Transport | `web/server.py`, `cli.py`, `intelligence/capabilities/*` | Serialise owner results; the intelligence envelope adds provenance |
| Clients | `web/static/*`, iOS `StrengthCore`, MCP | Display only; no client-side training arithmetic |

There is **no** materialised analytics table. The tables that look analytical are outputs, not
inputs: `critique`/`rubric_score` (retired history), `observation` (AFC-3 output),
`maintenance_review` (human decisions). Only two process-local caches exist in the web layer
(`_cache_get`/`_cache_set` for performance ratios and the programme forecast, keyed on the
database file stamp), plus `lru_cache` for configuration documents. None survives a restart,
none is shared with the CLI or the MCP capability, and none is keyed on a methodology version.

### 2.2 The expensive pattern

The same three steps repeat across consumers:

1. load a **full-history** `clean_set` frame (often twice in one request);
2. `derived.enrich()` it, which calls `derived.add_e1rm()` and re-derives e1RM, velocity flags
   and effort classes for every set;
3. aggregate it into the small result the caller actually needs.

Measured on the synthetic database (median of 2–3 runs, same connection):

| Operation | Owner | Measured |
|---|---|---:|
| `monitoring_analysis.build_analysis` | `features/monitoring_analysis.py` | **49,198 ms** |
| `outcomes.report(8 weeks)` | `features/outcomes.py` | **4,873 ms** |
| `strength_trend.observations` (one lift, one year) | `features/strength_trend.py` | **3,126 ms** |
| `deload.decision` | `features/deload.py` | 1,734 ms |
| — `RuleContext.from_store` / `History.load` | `rules/context.py` | 1,247 ms |
| `progress.dashboard(4 weeks)` | `features/progress.py` | 1,016 ms |
| — `performance_points` (e1RM ratio) | `features/progress.py` | 494 ms |
| — `_sets` (all clean sets into pandas) | `features/progress.py` | 202 ms |
| — `volume.compute` | `features/volume.py` | 346 ms |
| — `attendance.summary` | `features/attendance.py` | 108 ms |
| `get_training_overview` (full request, 20 runs) | `intelligence/capabilities/overview.py` | 2,730 ms p50 / 2,874 ms p95 |

The overview profile (§18) splits the request into `deload.decision` 65% (before the recent
selective-rule change; now 1,696 ms) and `progress.dashboard` 34%. Envelope and provenance cost
about 40 ms. Scaling is linear: 100 sessions 1,079 ms, 200 1,810 ms, 377 3,110 ms (pre-change),
600 4,578 ms.

### 2.3 Where the work is duplicated or repeated

| Calculation | Owners that implement or reproduce it | Consumption |
|---|---|---|
| Per-set e1RM | `domain/e1rm.py` (authority); `features/derived.add_e1rm` (vectorised); `features/progress._session_lift_e1rms`; `features/strength_trend._best_with_quality`; `features/outcomes._strength`; `features/monitoring_analysis`; `features/e1rm_calibration`; `features/exercise_history` | Progress, Outcomes, Performance, Monitoring, Intelligence, prescription previews |
| Full `clean_set` scan + `enrich` | `rules/context.History.load`; `progress._sets`; `progress._session_lift_e1rms`; `outcomes._sets`; `monitoring_analysis.build_analysis`; `strength_trend._observations` | Each request re-scans independently; the overview alone scans the table three times |
| Session/exercise aggregates (best e1RM, tonnage, hard sets, working sets) | Recomputed by each report from the frame | Dashboard, Outcomes, Monitoring, Progress |
| Weekly spinal costs | `rules/registry.weekly_spinal_costs` over the whole context, on every deload decision and prescription build | Deload, prescription policy, intelligence |
| e1RM ratio (prior 84-day best, 56-day points) | `progress.performance_points`, also `/api/performance/ratios` and the web cache | Progress, overview, intelligence |
| Readiness coverage | `queries.readiness_series`, `progress.dashboard`, `outcomes._readiness`, `monitoring_analysis` | Repeated per request, cheap (about 1 ms in the overview) |

Two important boundaries hold today and must keep holding:

- The web and CLI call the same owner functions; the intelligence capability composes them and
  does not reimplement any metric.
- Prescriptions, readiness decisions and policy verdicts remain server-side; no client computes
  them.

## 3. ODROID bottleneck analysis

The selective deload change removed one third of the rule-evaluation cost; the context build is
untouched. The table separates what a derived layer can remove from what it cannot.

| Cost | Measured | Removed by derived data? | What remains |
|---|---:|---|---|
| Whole-history `clean_set` scan + `derived.enrich` in `History.load` | 1,247 ms | Yes: per-set e1RM and effort/velocity fields, plus weekly spinal aggregates, become lookups | Query of the derived week/set rows, symptom and block lookups; report assembly |
| `progress._session_lift_e1rms` + ratio history | 494 ms | Yes: per-session/exercise best e1RM is a stored aggregate | The small ratio loop over 56 days; no frame build |
| `progress._sets` + `volume.compute` | 202 + 346 ms | Partly: weekly pattern set counts and volume rows can be stored; the owner still renders the table | Aggregation over a few weekly rows |
| `outcomes.report` | 4,873 ms | Yes for strength/volume attendance parts; the report still assembles several sections | Readiness, symptom and deload summaries (cheap queries) |
| `monitoring_analysis.build_analysis` | 49,198 ms | Partly: per-session/exercise and weekly aggregates cut the loops; a result snapshot may still be needed for the whole report | Snapshot read plus assembly if a snapshot is used |
| `strength_trend.observations` (one lift, one year) | 3,126 ms | Yes: per-session/exercise e1RM and per-set derived rows | Range query and rolling median over a few hundred rows |
| Attendance, readiness coverage, envelope, provenance | about 40–110 ms each | No meaningful benefit; keep on demand | Unchanged |

**Residual bottlenecks.** Report assembly and serialisation, the readiness and symptom queries,
the first read after a cold start (SQLite page cache), and any calculation whose window is
inherently large (monitoring over years). These are not removed by materialisation and should
not be presented as solved.

## 4. Proposed architecture

### 4.1 Principles

1. **Owners stay authoritative.** Every metric keeps exactly one definition, in the module that
   owns it today. Derived tables store the output of those definitions, never a second formula.
2. **Source data stays append-only.** Derived rows are disposable and may be deleted and rebuilt;
   `clean_set`, `session` and the rest keep their current rules.
3. **Versioned and rebuildable.** Every derived row carries a `method_version`; a change to a
   formula creates a new version and a rebuild, never an in-place reinterpretation.
4. **No partial results.** A consumer sees either complete derived data for its version or the
   current on-demand path. A half-built table is never read as valid.
5. **Selective.** Only expensive, repeatedly computed values are stored. Attendance, readiness
   counts and other cheap reads stay on demand.
6. **No consumer bypass.** Web, CLI, iOS and MCP call the same owner functions; they never read
   derived tables directly.

### 4.2 Data model

Proposed tables (names provisional; a migration would be a separate approved task):

| Table | Grain | Columns (sketch) | Written by |
|---|---|---|---|
| `derived_set` | one leaf `clean_set` row | `set_id` (PK/FK), `method_version`, `e1rm_kg`, `e1rm_quality`, `e1rm_usable`, `velocity_mean`, `velocity_loss_pct`, `effort_class`, `intensity_pct`, `computed_at` | `features/derived` materialiser |
| `derived_session_exercise` | session x exercise | `session_id`, `exercise_id`, `method_version`, `working_sets`, `hard_sets`, `best_e1rm_kg`, `tonnage_kg`, `total_reps`, `mean_load_kg`, `computed_at` | owner materialisers (progress/outcomes/strength_trend) |
| `derived_week` | ISO week x exercise | `iso_week`, `exercise_id`, `method_version`, `weighted_spinal_cost`, `sets`, `hard_sets`, `pattern`, `computed_at` | `rules/registry.weekly_spinal_costs` materialiser |
| `analytics_snapshot` | report kind + window | `kind`, `window_start`, `window_end`, `method_version`, `data_stamp`, `payload_json`, `created_at` | the owning report module |
| `analytics_build` | family + version | `family`, `method_version`, `status` (pending/running/ready/failed), `cursor`, `started_at`, `finished_at`, `error` | rebuild coordinator |

**Granularity rationale.** Per-set rows are the natural unit because e1RM, effort and velocity
are per set and because corrections create new leaf rows. Session/exercise rows answer the
dashboard and report loops. Weekly rows answer spinal costs and volume, which are the two
aggregations that must cover the whole history to preserve current details. Result snapshots
are reserved for reports whose assembly itself is expensive (monitoring, and possibly outcomes);
they are not a generic cache.

**What is deliberately not materialised:** attendance summaries, readiness coverage, evidence
envelopes, provenance hashes and anything whose computation is already a small query. Storing
them would add invalidation surface without addressing a measured bottleneck.

### 4.3 Ownership and interfaces

| Responsibility | Owner |
|---|---|
| Facts and their append-only rules | `store/` and the existing migrations |
| Metric definitions and output shapes | the existing `features/*`, `rules/*`, `adherence.py`, `workout.summary` |
| Derived computation for a family | the same owner module, via a `materialise_*` function that calls its existing code |
| Derived storage, versioning, rebuild state | a small shared `features/derived_store.py` coordinator; it contains no metric formulas |
| API, CLI, MCP, web | unchanged; they call owner functions and receive the same payloads |
| iOS | unchanged; it consumes the existing API contracts |

Read path: an owner function checks whether `derived_store` has complete rows for its version
and the current source stamp. If yes it reads them; if not it computes on demand exactly as
today. The public signature and the returned payload do not change, so clients cannot tell which
path ran except by latency. Derived tables are never exposed through the API.

### 4.4 Incremental updates and invalidation

| Source event | Effect |
|---|---|
| New workout completed (`workout.end`) | Compute `derived_set` rows for the session, then its session/exercise and week rows, in one transaction |
| Import (`importer.import_export`) | Queue the imported sessions and let the worker (or a caller-driven batch) materialise them |
| History correction / supersede / remove set | Delete derived rows for the superseded leaf set ids and recompute the affected session aggregates; never leave the old row readable |
| Void / unvoid | Rebuild the session and its week rows |
| Exercise remap | Rebuild the affected sets, session/exercise rows and week rows |
| Config change (spinal costs, taxonomy, volume landmarks) | Bump the affected family version or config stamp and rebuild only the dependent family |
| Methodology change | Bump `method_version`, mark the family `pending`, rebuild in the background; readers fall back until `ready` |
| Interrupted / failed build | Only committed batches are visible; `analytics_build` records the cursor and error; the next start resumes, and readers keep using on-demand |

Correctness rule: a derived row is valid only if its `method_version` equals the current version
and its source stamp (maximum leaf set id and `PRAGMA data_version` observed at build) matches
the database. A mismatch triggers recomputation rather than a stale read.

### 4.5 Startup, backfill and operations on the ODROID

The ODROID is headless and always on; a slow first run is acceptable, a stale or partial read
is not.

- **Migration.** Creates the empty derived tables and one `analytics_build` row per family with
  status `pending`. Source data is untouched and the server starts normally.
- **Backfill.** A background worker in the web process (a single bounded thread, like the
  existing prescription worker) walks sessions in date order in batches, commits each batch, and
  updates the cursor. It runs at low priority and yields between batches. A long first run is
  expected; normal restarts resume rather than restart the build.
- **Reads during backfill.** Owner functions keep using the on-demand path until the family is
  `ready` for the current version. No endpoint is served a partial table. Where a response has
  room for it, a `status: rebuilding` note can be added later; that is a contract decision, not
  part of this design.
- **Incremental after backfill.** Writes materialise the touched session synchronously (small);
  anything larger is queued to the same worker.
- **Observability.** `analytics_build` plus a read-only status endpoint and log lines report
  family, version, progress, batch time and errors. A failed family stays on the on-demand path
  and is visible rather than silent.
- **Rebuilds.** A methodology or configuration change marks the family `pending` and rebuilds;
  old rows are ignored by version and can be vacuumed later. No in-place edits of derived rows.

Why asynchronous: a first backfill over years of history is minutes, not milliseconds, and must
not block startup or the request that triggers it. Why not a separate service: the deployment is
a single SQLite file on one host, and a second writer would add coordination without benefit.

### 4.6 Performance expectations (targets, not claims)

The numbers below are what the layer is intended to enable; each must be measured on the
deployment host before it is reported as achieved.

| Path | Measured now | Benchmark target |
|---|---:|---:|
| `get_training_overview` p50 | 2,730 ms | under 1,000 ms |
| `deload.decision` | 1,696 ms | under 200 ms |
| `progress.dashboard` | 1,016 ms | under 250 ms |
| `progress.performance_points` | 494 ms | under 50 ms |
| `outcomes.report(8 weeks)` | 4,873 ms | under 1,000 ms |
| `monitoring_analysis.build_analysis` | 49,198 ms | under 5,000 ms |
| `strength_trend.observations` (one lift, one year) | 3,126 ms | under 300 ms |

Residual after the layer: report assembly, readiness/symptom queries, provenance and JSON
serialisation, SQLite cold reads, and the first request after a rebuild. Monitoring may still
need a snapshot rather than only aggregates.

## 5. Alternatives and trade-offs

| Approach | Complexity | Storage | Invalidation risk | Startup | Performance | Verdict |
|---|---|---|---|---|---|---|
| On-demand only (today) | lowest | none | none | instant | 2.7 s overview, 49 s monitoring | Rejected: the deployment host cannot carry it |
| In-memory cache | medium | none | process-local, lost on restart, not shared with CLI/MCP | instant | helps repeats only; cold call unchanged | Rejected as the primary fix |
| Full persistent materialisation of everything | high | large | high (every metric) | slow first build | best | Rejected: unnecessary storage and invalidation surface |
| **Selective materialisation + on-demand fallback** | medium | small (per-set, session/exercise, week, few snapshots) | bounded and versioned | background backfill, resume-safe | removes the measured scans; cold reads and assembly remain | **Recommended** |

The recommended design keeps one code path per metric: the owner computes it, and the same
owner reads the stored result when it is valid. No second formula exists to drift.

## 6. Implementation roadmap

| Phase | Scope | Depends on | Acceptance |
|---|---|---|---|
| 0. Design approval | This document; owner decision on tables, versions and snapshot scope | none | Approved design and a decision record |
| 1. Foundation | Migration for the five tables, `derived_store` coordinator, build state, status endpoint, no consumers migrated | 0 | Migration applies/reverts cleanly; empty tables; status visible; no behaviour change |
| 2. Per-set + session/exercise materialisation and backfill | `derived_set` and `derived_session_exercise` written by the owning modules; background backfill; on-demand fallback | 1 | Derived values equal the on-demand values on the synthetic and fixture data; interrupted build resumes; no partial reads |
| 3. Migrate progress + strength_trend | `progress.performance_points`, `_sets`/volume and `strength_trend.observations` read derived rows when ready | 2 | Identical payloads; measured dashboard and trend latency; tests for fallback |
| 4. Migrate rules context | `derived_week` feeding `RuleContext`/`weekly_spinal_costs`; deload and prescription policy read it | 2 | Verdict details identical (including weekly cost map); deload benchmark; policy tests unchanged |
| 5. Migrate outcomes and monitoring | Aggregates first, then optional snapshots for monitoring | 2–4 | Payloads identical; snapshot invalidation tested on correction, import and method bump |
| 6. Verification and INT integration | ODROID benchmark of overview, deload, outcomes, monitoring; decide the transport gate | 3–5 | Measured results recorded in the ADR; transport enabled only if the gate is met |

Each phase is additive and reversible: dropping the derived tables and the read branches
returns the system to the current on-demand behaviour.

## 7. Risks and unresolved decisions

- **Duplication by accident.** The main risk is a second implementation appearing in the
  materialiser. Mitigation: the materialiser calls the owning function; tests compare derived
  and on-demand payloads on the same fixtures.
- **Staleness.** A missed invalidation hook can serve old numbers. Mitigation: source stamp and
  version check on read, plus a startup reconciliation against the maximum leaf set id.
- **Detail drift.** Deload verdict details include a weekly cost map; the derived week table
  must reproduce it exactly, including intensity factors, or the map changes. This needs
  equivalence tests before the rules context is migrated.
- **Snapshot scope.** Whether monitoring needs a result snapshot or the aggregates suffice is
  unresolved and should be decided from a measured prototype, not assumed.
- **Storage and vacuum.** Per-set rows are small but not free; a retention and vacuum policy is
  needed for superseded rows.
- **Cross-repository consistency.** iOS and the INT capabilities keep their current contracts;
  no client changes are needed. The portfolio plan should reference this design rather than
  restate it.

**Non-goals:** changing metric definitions, altering the deload policy, introducing lookback
truncation, adding a generic cache, changing MCP transport, or migrating the iOS client.

## 8. Reproduction and verification

Audited HEADs: backend `de686c7`, portfolio `de7dd18`, iOS `43292bb` on `llm-integration`.

Commands used:

    python tools/intelligence_benchmark.py --sessions 377 --runs 20 --json
    # component timing: time.perf_counter around progress.dashboard, deload.decision,
    # RuleContext.from_store, outcomes.report, monitoring_analysis.build_analysis,
    # strength_trend.observations, on a read-only connection to the synthetic database

The benchmark and profiling method are recorded in `docs/INTELLIGENCE-IMPLEMENTATION.md` §18.
No source file, schema, cache or production database was modified for this report.

