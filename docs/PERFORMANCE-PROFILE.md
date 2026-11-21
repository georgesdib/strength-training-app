# PRESCRIPTION PERFORMANCE PROFILE

**Status:** implemented and measured on the deployment target 2026-11-04 on `development`.
Updated 2026-11-05: per-generation `clean_sets` snapshot implemented and A/B rebenchmarked;
§8 statuses clarified.
Updated 2026-11-10: §9 adds an iMac coding-host re-run of the resolver and programme forecast;
the ODROID-C4 figures in §2–§8 are unchanged.
Updated 2026-11-18: §11 records four Python-side hot-path changes and their measured effect;
the ODROID-C4 figures in §2–§9 are unchanged and §11 has no deployment-target numbers yet.
No prescription behaviour changed.
**Workload:** deterministic resolver build for 2026-11-04, squat, target field 30 minutes
(minimum-session trimming not applied), resolver enabled, against the owner's local database
(552 sessions). Seven prescribed items.
The 2026-11-05 A/B below uses the current 375-session database with the same seven-item output.

**Hardware:** Hardkernel ODROID-C4, 4× ARM Cortex-A55, 3.7 GB visible RAM, Linux aarch64,
Python 3.13.5. All benchmark results in §2–§8 were produced on this machine; §9 is a
separately labelled re-run on the iMac coding host.

## 1. Baseline method

- Wall and CPU time: `time.perf_counter` and `resource.getrusage`.
- Function-level profile: `cProfile` on `resolver.build_resolved`.
- Query count and peak memory: SQLite trace callback and `tracemalloc`. These add substantial
  overhead, so they are reported separately and are not used as latency measurements.
- Baseline is commit `312d1ef` in a detached worktree; the optimized tree is the current
  `development` branch. Both read the same database snapshot and use the same prescription
  inputs.

## 2. Baseline and result

| Run | Wall | CPU | Notes |
|---|---:|---:|---|
| Baseline `build_resolved` | **133.15 s** | **131.86 s** | commit `312d1ef` |
| Optimized `build_resolved` | **42.13 s** | **41.72 s** | current development, same ODROID-C4 |
| Reduction | **68.4%** | **68.4%** | 3.16× faster; same 7 items, same order |
| 2026-11-05 A/B, no snapshot | **46.19 s** | **45.69 s** | current 375-session DB; direct _build_resolved |
| 2026-11-05 A/B, snapshot | **35.41 s** | **35.06 s** | same DB and same 7 items; public build_resolved |
| Snapshot reduction | **23.3%** | **23.3%** | 10.78 s wall / 10.63 s CPU |

The optimized path returned the same item list:

```text
box_jump, ssb_squat, bench_press_narrow, back_extension,
dumbbell_row, lying_leg_curls, ab_wheel
```

The 42.13 s optimized figure predates the per-generation `clean_sets` snapshot (§4.7);
the snapshot is implemented and rebenchmarked here. The 2026-11-04 42.13 s figure used a
552-session database and is not directly comparable to the 2026-11-05 A/B, which holds the
current 375-session database and the seven-item output constant: 46.19 s without the snapshot
vs 35.41 s with it (CPU 45.69 s vs 35.06 s).

Peak traced memory on the optimized run: **21.1 MB**. The traced run recorded **311 SQL
statements**. The trace callback and `tracemalloc` made that run slower (172.9 s) and were not
used for the latency comparison.

## 3. Profile findings

Baseline `cProfile` time was 251.98 s; optimized `cProfile` time is 78.57 s. Profile overhead
is high, so use the ratios, not the absolute values.

| Stage / function | Baseline | Optimized | Finding |
|---|---:|---:|---|
| `beam.search` | 239.9 s | 67.3 s | four full evaluator builds |
| one `evaluate_assignment` | 60.0 s | 16.8 s | repeated volume/schedule/config work |
| `volume_budget.report` | 161.4 s | 15.1 s | called 12 times; schedule dominated |
| `schedule.next_session_type` | 156.1 s | 9.5 s | 12 calls, now 11 cache hits |
| YAML `safe_load` | 82.2 s | 14.7 s | config/policy re-parsing |
| `e1rm_calibration` | 18.0 s | 11.4 s | repeated identical factors |
| `vbt_calibration.calibrate` | 13.3 s | below top | repeated identical frame |
| `settings_registry.snapshot` | 15.2 s | 1.2 s | immutable config snapshot |

The dominant structural inefficiency was **four complete sequential evaluator builds**, each of
which recomputed the same rolling schedule, volume report inputs, settings and calibration data.
The scheduler was being asked for the same next session type repeatedly because each
`volume_budget.report` call asked again.

## 4. Implemented optimizations

1. **Per-connection schedule memoisation** (`prescribe/schedule.py`)
   - Caches the complete `next_session_type` choice, not just availability.
   - Key includes the connection, date, prior types, SQLite `data_version`, `total_changes`,
     and the session-template/resolver-policy file mtimes.
   - Eliminated 11 of 12 expensive schedule calculations in the benchmark.
   - Largest single contribution: removes roughly 140 s from the baseline profile.

2. **Immutable settings-registry snapshot cache** (`settings_registry.py`)
   - Cached by the exact config file set, mtime and size.
   - Profile writes do not invalidate it; config edits do.
   - Page/profile writes still rebuild the effective feature settings.

3. **Resolver policy parse cache** (`prescribe/resolver_policy.py`)
   - Parsed policy objects are keyed by YAML body and digest; validation is not bypassed.

4. **E1RM factor cache** (`features/e1rm_calibration.py`)
   - Keyed by connection, date, window, effective calibration/decay config, SQLite
     `data_version` and write count.
   - Returns immutable `LiftCalibration` rows; measured-test or settings writes invalidate it.

5. **VBT calibration cache** (`features/vbt_calibration.py`)
   - Keyed by a SHA-256 digest of the enriched DataFrame, effective params and method version.
   - Different rows or parameters never reuse a result.

6. **Spinal-defaults cache** (`settings_registry.py`)
   - Cached by the programme rule file mtime/size.

7. **Per-generation clean-set snapshot** (`store/queries.py`, `prescribe/resolver.py`)
   - `resolver.build_resolved` opens one scoped snapshot; nested `clean_sets` calls with
     identical filters share one query/frame across the four complete evaluator builds.
   - The snapshot is build-scoped, invalidated by SQLite `data_version`/write count, and
     returns defensive deep copies so a caller cannot mutate the cached frame.
   - No cross-request cache and no change to exercise choice, load arithmetic, readiness,
     safety validation or persistence.
   - 2026-11-05 A/B on the current 375-session database: direct no-snapshot build **46.19 s**
     (CPU 45.69 s) vs public build **35.41 s** (CPU 35.06 s), both returning the same seven
     items in the same order.

Together the settings, policy, E1RM, VBT and spinal caches took the cProfile result from
113.89 s to 78.57 s (the first schedule cache took the baseline 251.98 s to 113.89 s).

No change was made to exercise choice, load arithmetic, readiness, safety enforcement, evaluator
selection, persistence or append-only writes.

## 5. Cache correctness and invalidation

| Cache | Invalidated by |
|---|---|
| schedule result | DB data version, connection write count, template/policy file changes |
| settings snapshot | any config YAML mtime/size/content set change |
| resolver policy parse | different YAML body/digest |
| e1RM factors | DB data version/write count, date/window or calibration/decay config change |
| VBT calibration | different frame content, params or method version |
| spinal defaults | programme rule file mtime/size |
| clean_sets snapshot | DB data version/connection write count; end of the generation build; filters are part of the key |
| existing browser prescription cache | unchanged; seven-day browser cache, cleared on start/discard |

Correctness rule: caches only return immutable values or values treated as read-only. Database
writes are detected through SQLite state; config writes through file stamps/content. A cache is
never allowed to make a stale readiness, training-history, suitability or settings value
authoritative.

## 6. Parallelism assessment

**Recommendation: do not add multiprocessing now.**

The remaining four evaluator builds are nominally independent, but on the ODROID-C4:

- each process would need its own SQLite connection and a copy of the in-process context;
- the work includes Python/NumPy/pandas objects that would need pickling or re-derivation;
- worker startup, memory replication and deterministic result merging would add complexity;
- the authoritative selection, load solving and safety validation must stay sequential;
- the end-to-end path is already hidden behind the polled prescription job, so a long build no
  longer causes a browser failure.

The measured sequential result is a **3.16× speedup** on the target ODROID-C4 without
concurrency risk. Parallelism is not justified by the remaining profile, and a process backend
would be premature on a 4 GB device.

**Global CPU-job admission:** resolver preview, Workflow prescription and programme forecast
share one process-wide semaphore. Admission and job registration happen under the same lock;
the worker thread starts only after the lock is released; a second CPU-heavy request gets a
409. This keeps one expensive build at a time on the four Cortex-A55 cores.

**VBT cache isolation:** cached calibration results are deep-copied on store and retrieval, so
a caller mutating `targets` or `excluded` cannot affect a later result.

## 7. ODROID-C4 deployment guidance

These numbers were measured on the target hardware: **Hardkernel ODROID-C4**, 4× Cortex-A55,
3.7 GB visible RAM, Linux aarch64, Python 3.13.5. The observed **21 MB peak** is well within
4 GB, and the workload is CPU-bound rather than memory-heavy. The historical optimized build
is 42.13 s on this machine, down from 133.15 s; the current same-DB A/B is 46.19 s without the
snapshot and 35.41 s with it.

Use the existing polled Workflow/Settings job path. Do not add workers by default. If the
remaining 42 s is still unacceptable, the next candidate is reducing the resolver beam's
full-evaluation count. The shared immutable clean-set snapshot is now implemented (§4.7); a
broader generation context remains a candidate, not a commitment. Do not add processes or
persistence complexity by default.

## 8. Remaining limitations and status

1. **Acceptable limitation — four full evaluator builds remain.** They are the largest residual
   cost. The four builds are the beam's four complete candidate evaluations; removing them
   would change candidate coverage or selection, not just performance.
2. **Implemented mitigation — repeated `clean_sets` reads.** `resolver.build_resolved` now
   opens a per-generation snapshot (§4.7), so identical clean-set filters are queried once
   across the four evaluator builds. Callers receive defensive copies; the snapshot is
   invalidated by DB state and ends with the build. Measured 2026-11-05 on the current
   375-session database: **46.19 s without the snapshot vs 35.41 s with it**, same seven items.
3. **Informational only — representative benchmark.** The profile uses one date (2026-11-04)
   and one session shape. The historical run used the owner's 552-session database; the
   2026-11-05 A/B used the current 375-session database. Other dates with larger deltas, drops
   or resolver constraints may differ.
4. **Informational only — no process-based parallel backend.** Multiprocessing was assessed and
   rejected: SQLite connections, pickling/re-derivation, deterministic merging and memory on a
   4 GB device outweigh the benefit; one CPU-heavy build runs at a time.
5. **Informational only — hardware/Python-specific numbers.** Benchmarks use the ODROID-C4 and
   Python 3.13.5; re-run after OS or Python upgrades if absolute latency matters.

## 9. iMac coding-host re-run (2026-11-10)

**Not the deployment target.** This section repeats the resolver build and the programme
forecast on the **iMac coding host**. It records local build times and the hardware gap only:
the ODROID-C4 figures in §2 and §7 remain the deployment numbers and are unchanged.

**Hardware:** iMac, Intel Core i5-6500 (4 cores), 8 GB RAM, macOS 12.7.6, Python 3.14.8.
**Database:** a SQLite backup of `data/coach.db` (376 sessions) at a temporary path; the
resolver was enabled on that copy only. The live database was opened read-only for the backup.

### 9.1 Resolver build

Same inputs as §2: date 2026-11-04, squat, `minimum_target_minutes=30`,
`top_set_intent="off"`, public `resolver.build_resolved` with the clean-set snapshot on.

| Run | Wall | CPU |
|---|---:|---:|
| iMac, run 1 | 6.98 s | 6.84 s |
| iMac, run 2 | 6.84 s | 6.72 s |
| iMac, run 3 | 6.74 s | 6.67 s |
| ODROID-C4, 2026-11-05 A/B with snapshot (§2) | 35.41 s | 35.06 s |

All three runs returned the same seven items in the same order as the ODROID run:
`box_jump`, `ssb_squat`, `bench_press_narrow`, `back_extension`, `dumbbell_row`,
`lying_leg_curls`, `ab_wheel`. The iMac database is one session newer (376 vs 375), so this is
a close re-run, not a byte-identical A/B. The iMac is about **5×** faster — expected of a
desktop Core i5 against four Cortex-A55 cores, and not evidence about deployed latency.

### 9.2 Programme forecast

`features.programme.build_programme` with its fixed path (`use_resolver=False`), start
2026-11-10, three sessions per week, one fresh process per row:

| Horizon | Sessions | Wall | CPU |
|---|---:|---:|---:|
| 2 weeks | 6 | 29.0 s | 28.6 s |
| 4 weeks | 12 | 50.3 s | 49.7 s |
| 26 weeks (maximum) | 78 | 323.0 s | 319.2 s |

Cost grows roughly linearly with session count, with a small shared history load at the start.
DEC-PROGRAMME-09 records "about a minute" for a six-session forecast on an unnamed reference
machine; the iMac completes that horizon in 29 s. The 26-week maximum takes over five minutes
here, which is why the forecast is one background job and the horizon is clamped to 26 weeks
rather than unbounded. These session builds use the fixed path; the resolver figures in §9.1 do
not apply to them.
## 10. Intelligence capability latency — ODROID direct run (2026-11-18)

**Method.** `tools/intelligence_benchmark.py --db data/coach.db --runs 30`, direct (in-process)
execution on the ODROID-C4, against the live production database opened with `mode=ro` and
`PRAGMA query_only` (379 sessions, 8,009 clean sets, 231 MB). Five warm-ups and 30 measured
requests per capability; all eleven capabilities returned `ok` 30/30 with no errors. The run
overlapped one real write (the phone's recovery-HRV sync), so the figures include a live writer.
p95 sat within 1–2 % of p50 everywhere: the work is CPU-bound and deterministic, not IO-jittery.

| capability | p50 ms | p95 ms |
|---|---:|---:|
| `get_prescription` | 1.2 | 1.7 |
| `get_exercise_progression` | 24.4 | 25.7 |
| `get_vbt_analysis` | 33.6 | 37.1 |
| `get_adherence_analysis` | 59.3 | 60.6 |
| `compare_training_periods` | 137.7 | 143.7 |
| `get_programme_block_summary` | 207.5 | 209.6 |
| `get_longevity_assessment` | 433.4 | 437.2 |
| `get_readiness_history` | 434.4 | 437.8 |
| `get_training_overview` | 578.1 | 593.7 |
| `get_weekly_review` | 595.3 | 600.7 |
| `get_session_details` | 4,350.8 | 4,498.4 |

**Where the longevity call goes** (same machine, ten requests each): `activity_summary` 98 ms,
`latest_vo2max` 0.1 ms, `volume_budget.headroom` 319 ms, whole assessment with patterns 421 ms,
time-in-zone alone 191 ms.

**Findings and follow-ups.**

1. **Time-in-zone was the defect and is fixed.** It loaded all 590,289 heart-rate samples to answer
   a 28-day question (the window holds 25 workouts and 4,882 samples): 11,078 ms p95. Scoping the
   sample query to the window took it to 191 ms (`66f48d9`). The per-year report still loads the
   full corpus by design, because it spans every year.
2. **`get_session_details` remains the only tool that makes a chat turn feel slow** (4.5 s; two
   `RuleContext` builds plus `workout.summary`). Unchanged here and unrelated to longevity.
3. **Three quarters of the longevity call is the weekly volume budget.** `BudgetConfig.load`
   re-parses YAML on every call and `report()` builds a full future projection the advice never
   reads. Not optimised: one call per Today open or chat turn does not justify it. The cheap lever
   if that changes is a per-file-mtime config cache, then a lighter current-status query.
4. **These are direct-mode figures.** The tool descriptions carry HTTP figures from 2026-11-14;
   the 437 ms direct entry stays as recorded, because MCP has no consumer today and the HTTP
   variant would refine a tool description nothing reads. Refresh it only if MCP acquires a client. The transport is named per row in `intelligence/latency.py`.
5. HTTP adds 10–15 % on this hardware (readiness: 377 ms HTTP vs 434 ms direct), so the two
   transports are not interchangeable when comparing.

## 11. Python hot-path work (2026-11-18)

**Status:** implemented and confirmed on the ODROID-C4 on 2026-11-18 (§11.5).
The MacBook figures in §11.2–§11.4 located the work; §11.5 is the deployment result.

### 11.1 Method

The owner's database was not opened. The benchmark database is synthetic, built from the
checked-in taxonomy and session templates: **407 sessions and 9,160 clean sets**, deliberately
close to the production shape in §10 (379 / 8,009). Same inputs as §2–§9: date 2026-11-04,
squat emphasis, `minimum_target_minutes=30`, `top_set_intent="off"`, resolver enabled.

Calibration: the baseline build is **2.47 s p50** here against 27.77 s p50 for the same build
on the ODROID-C4 (§11.5), so this host is about **11×** the C4 for the untouched path. The
synthetic database over-weights the two cached paths, and §11.5 shows the deployed gain is
smaller than the local one. The local figures are used for locating the work, not as a
latency claim.

### 11.2 Where one build went (baseline)

| Phase | Share |
|---|---:|
| Four full `build_prescription` evaluations (the beam) | **91 %** |
| `candidate_pools` | 8 % |
| fingerprint, snapshot validation, policy load | 1 % |

Deterministic counts inside those four builds:

- **195 SQL statements**, with **5 ms** of `sqlite3` C time. The database is not the bottleneck.
- **19.6 M Python calls.** `cProfile` attributes 37 % to pandas object access, 29 % to PyYAML,
  21 % to `strength_coach` itself and 0.3 % to C extensions.
- **899 `DecayConfig.load` calls** (one per prescribed item per candidate build) for one file.
- **5 `History.load` calls**: a clean-set query plus `derived.enrich` over the whole record, five
  times, for the same past.
- **16 `spinal_exposures` recomputations**, each walking every working set with `itertuples`
  (2.65 M `ExtensionArray.__getitem__` and 2.65 M `__iter__` calls per build).

### 11.3 Changes

| Commit | Change |
|---|---|
| `aca8459` | `DecayConfig` parsed once per (path, mtime, size); the object is frozen and scalar-only, so it is shared. |
| `c63b9e7` | The beam's four evaluations share one `History`. It is passed beside `inputs`, not inside it, so the prescription input fingerprint still describes the request. |
| `1b14e71` | `spinal_exposures` groups in column space. Every working row still counts as a set, intensity still averages only rows carrying load and e1RM, and `skipna=False` keeps one missing ratio poisoning its group mean. |
| `0cb8d7a` | `utils/yaml_files` caches a parsed config document per (path, mtime, size); each loader still builds its own frozen dataclass from it. The constitution was already content-hash cached and is unchanged. |

### 11.4 Measured effect on the coding host

| Tree | p50 | Change |
|---|---:|---:|
| baseline | 2.465 s | — |
| + decay-config cache | 2.195 s | −11 % |
| + shared `History` | 1.826 s | −17 % |
| + grouped spinal exposures | **1.575 s** | −14 % |
| all three | **1.575 s** | **−36 % (1.57×)** |

The steps are sequential, not additive: the `History` change removes work the other two also
touch. The config cache (`0cb8d7a`) leaves this path essentially unchanged (117 YAML parses per
build versus 129); its effect is per request in a long-lived process, see §11.5.

Output was identical at every step: the same seven items in the same order, the same set counts,
spinal cost/headroom and warnings on 2026-11-04, 2026-06-10 and 2025-12-03.

### 11.5 On the ODROID-C4 (deployment target)

Same harness, same live database (379 sessions), same inputs, two measured runs each, against
the source database opened read-only and backed up with SQLite's backup API. `d7181d6` is the
commit before this work; `e826867` is the current `development`.

| Run | `d7181d6` | `e826867` | Change |
|---|---:|---:|---:|
| Resolver build, p50 | 27.77 s | **23.71 s** | **−14.6 % (1.17×)** |
| Resolver build, min | 27.72 s | 23.67 s | −14.6 % |
| Forecast, 2 weeks / 6 sessions, p50 | 43.54 s | 40.16 s | −7.8 % |

The prescribed items were identical in both runs (`box_jump, ssb_squat, bench_press,
back_extension, dumbbell_row, lying_leg_curls, ab_wheel`).

A second round took the same harness on the same database after four more changes (look up
group means in a dict instead of `Series.get` on a MultiIndex; eleven more config loaders through
`utils/yaml_files`; the e1RM calibration report memoised per database state; `prior_to` views
memoised on the context):

| Run | before (`e826867`) | after (`3e4ca8e`) | Change |
|---|---:|---:|---:|
| Resolver build, p50 | 23.71 s | **16.64 s** | **−30 %** |
| Forecast, 2 weeks / 6 sessions, p50 | 40.16 s | **22.06 s** | **−45 %** |

Cumulative against the pre-work commit `d7181d6`: resolver **27.77 s → 16.64 s (−40 %, 1.67×)**,
two-week forecast **43.54 s → 22.06 s (−49 %, 1.97×)**, same seven items throughout.

`resolver.full_evaluations` (default 4, range 1–4, settings-profile) now exposes how many beam
finalists are evaluated; the beam width is unchanged and the value is recorded in
`generated_session.beam_config`. Lowering it trades selection coverage for speed and is a
coaching decision, not an optimisation; the default keeps the behaviour measured above.

Two notes on the numbers:

1. Both are below §2's 35.41 s because the harness warms the process caches with one unmeasured
   build and the input date has moved on; the comparable pair is this table's two columns, not
   this column and §2.
2. The deployed gain is smaller than the 36 % measured locally. The synthetic database is 9 MB
   and carries only training and readiness rows; the live one is 241 MB with app-tracked
   workouts, symptom rows and heart-rate samples, so the work this change does not touch is a
   larger share of the build. The local percentage was a ceiling, not a forecast.

### 11.6 Effect on the capabilities

Warm YAML parses per request, before → after `0cb8d7a`:

| Capability | Parses per request |
|---|---|
| `get_session_details` | 30 → 3 |
| `get_weekly_review` | 5 → 2 |
| `get_training_overview` | 3 → 1 |
| `get_longevity_assessment` | 39 → 14 |

The largest single parse removed was the exercise taxonomy at **67.7 ms per call**, now 0.01 ms.
End-to-end capability timings were not recorded at a quiet enough moment to publish; they are to
be taken with the ODROID run below. The remaining parses are small files and were left alone.

### 11.7 Reproduce

```text
python tools/resolver_benchmark.py --db /path/to/copied/coach.db --runs 5 --forecast-weeks 2
```

The tool copies the database to a temporary directory, enables the resolver on the copy, and
prints cold start, min/p50/p95/max, finalist evaluations, prescription builds, candidate count and
beam truncation plus the prescribed items. Report the machine with the result.

The same harness has a synthetic fixed-history mode, so the corrected WP6 path and the same
builds with the role-quality snapshot disabled can be compared on identical inputs:

```text
python tools/resolver_benchmark.py --synthetic --case secondary_complementarity --runs 10
python tools/resolver_benchmark.py --synthetic --case straight --runs 10
```

It writes JSON, including the environment, the fixture's candidate pools, cold start and
steady-state percentiles. Laptop seconds are not ODROID seconds; the ODROID-C4 measurement is
recorded in §11.9.

### 11.8 Rejected

1. **Rust / PyO3 rewrite.** Only 5 ms of a 2.47 s build is in C (`sqlite3`); the cost is
   redundant work (899 parses, 5 history loads, 16 whole-record scans) that a port would still
   perform. The measured 1.57× came from removing that work in Python, without a second
   implementation of the prescription authority.
2. **Caching the parsed rule document.** Already implemented in `rules/loader.load_document`
   (content-hash keyed); nothing to add.
3. **Multiprocessing.** §6 still stands: one CPU-heavy build at a time, no process backend.

### 11.9 WP6 role-quality closeout (2026-11-21)

The WP6 corrective closeout changed the role-quality class computation, not the beam, candidate
cap or evaluation budget. The reproducible comparison is the synthetic
`secondary_complementarity` case (a full main + secondary + accessory fixture with two
finalists): the corrected path and the same builds with `role_quality.snapshot` disabled report
the same finalist evaluations and prescription builds, so the delta is the snapshot cost rather
than a search-width change.

Measured 2026-11-21 on the MacBook (macOS-27.2.1 arm64, Python 3.15.2, 8 CPUs) and on the
ODROID-C4 (Linux 6.18.44 aarch64, Python 3.13.5, 4 CPUs), one cold build then the steady-state
runs shown, single process, no CPU pinning:

| Host | Case | Corrected p50 / p95 | Same builds, role-quality snapshot disabled | Finalists / builds |
|---|---|---|---|---|
| MacBook | `secondary_complementarity` | 0.218 / 0.224 s | 0.204 / 0.210 s | 2 / 2 |
| MacBook | `straight` (10 runs) | 0.072 / 0.075 s | 0.058 / 0.061 s | 2 / 2 |
| ODROID-C4 | `secondary_complementarity` | 3.183 / 3.194 s | 3.018 / 3.144 s | 2 / 2 |
| ODROID-C4 | `straight` (10 runs) | 1.128 / 1.214 s | 0.921 / 1.179 s | 2 / 2 |

Cold-start times were 0.263 s / 0.112 s on the MacBook and 3.775 s / 1.730 s on the ODROID-C4
for the full and straight cases. These are measurements on the named hosts, not deployment
guarantees. The historical two-finalist row of 1.21/1.24 s recorded during the original WP6 work
is not reproduced by a checked-in p95 benchmark and is not a current guarantee.
