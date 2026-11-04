# PRESCRIPTION PERFORMANCE PROFILE

**Status:** implemented and measured on the deployment target 2026-11-04 on `development`.
No prescription behaviour changed.
**Workload:** deterministic resolver build for 2026-11-04, squat, minimum session 30 minutes,
resolver enabled, against the owner's local database (552 sessions). Seven prescribed items.

**Hardware:** Hardkernel ODROID-C4, 4× ARM Cortex-A55, 3.7 GB visible RAM, Linux aarch64,
Python 3.13.5. All benchmark and test results below were produced on this machine.

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

The optimized path returned the same item list:

```text
box_jump, ssb_squat, bench_press_narrow, back_extension,
dumbbell_row, lying_leg_curls, ab_wheel
```

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

## 7. ODROID-C4 deployment guidance

These numbers were measured on the target hardware: **Hardkernel ODROID-C4**, 4× Cortex-A55,
3.7 GB visible RAM, Linux aarch64, Python 3.13.5. The observed **21 MB peak** is well within
4 GB, and the workload is CPU-bound rather than memory-heavy. The optimized build is 42.13 s on
this machine, down from 133.15 s.

Use the existing polled Workflow/Settings job path. Do not add workers by default. If the
remaining 42 s is still unacceptable, the next candidates are reducing resolver beam
full-evaluation count or adding a shared immutable generation context, not adding processes or
persistence complexity.

## 8. Remaining limitations

- Four full evaluator builds remain; they are the largest residual cost.
- `queries.clean_sets` is still called repeatedly across evaluator builds.
- The profiling report uses one representative date and the owner's database; other dates with
  large deltas, drops or resolver constraints may differ.
- No process-based parallel backend was implemented.
- Benchmarks were run on the target ODROID-C4 with Python 3.13.5; re-run after OS or Python
  upgrades if absolute latency matters.
