# WP3 — REP-MOTION CAPTURE (IMPLEMENTATION PLAN)

**Status:** plan only, 2026-11-22. No code, no migration, nothing deployed. Approved upstream
contract: portfolio `docs/contracts/IOS-WATCH-CONTRACT.md`, amendment "2026-11-22 draft amendment —
per-rep motion capture (WP2)", owner-approved 2026-11-22.

**Companion plan:** portfolio `docs/plans/WATCH-MOTION-METRICS.md` §11 (WP3). Metric definitions are
that plan's §4; this document carries no metric change.

**Autonomy:** descriptive. Nothing here may feed a prescription, a load, a readiness input or a
training rule. The module boundary in §3.5 is the guarantee.

## 1. Scope

- Add `motion_axis` to the exercise taxonomy and pass it through the frozen plan as a watch hint.
- Accept optional per-rep motion fields on the existing add-set payload, with whole-set validation.
- Store them in a new append-only `clean_rep_phase` table, materialised from `workout_rep_event`.
- Add a descriptive `rep_tempo` report and expose the fields additively on session detail.
- Gate the whole feature behind one fail-closed config key.

Not in scope: any metric definition, any display, any client code, any raw sensor upload, any
deployment to the ODROID.

## 2. Existing behaviour that constrains the design

Verified in this repository on 2026-11-22.

| Thing | Where | Consequence |
|---|---|---|
| `_append_reps` normalises every rep to exactly `{rep_index, velocity_mps}` and drops unknown keys | `workout.py:1109` | The single ingest seam. New fields are lost here until it changes. |
| Three call sites | `workout.py:1415, 2102, 2140` | All must keep working unchanged for legacy payloads. |
| `clean_rep` insert | `workout.py:2352` | Materialisation point; `velocity_mps` is `NOT NULL` there. |
| `RepVelocityParser` rejects **more** velocities than reps, allows **fewer** | `StrengthCore/.../Phase2Models.swift` | Exact rep-count enforcement would reject payloads clients send today. Motion validation must not apply to legacy payloads (§4). |
| `validate_plan_items` only validates set groups | `prescribe/models.py:117` | Adding a plan-item key needs no validator change. |
| Every public markdown file must be classified in `docs/manifest.yaml` | `tests/test_docs_manifest.py` | This document needs a manifest entry in the same commit. |

## 3. Design

### 3.1 Taxonomy axis

`config/exercises/taxonomy.v1.yaml` gains an optional per-entity `motion_axis`, one of
`vertical`, `horizontal`. Absent means no capture. `utils/exercises` exposes it as
`ExerciseEntity.motion_axis -> str | None`; an unknown value fails at load, matching the existing
fail-closed taxonomy parsing.

The resolver attaches `motion_axis` to each plan item where items are built, so the frozen plan
carries it. This is additive: `validate_plan_items` ignores it, and Swift decoding ignores unknown
keys. **The server never acts on the axis** — it is a hint for the watch, and the server does not
validate payloads against it (a plan edited mid-session must not invalidate a captured set).

### 3.2 Migration `0076_rep_phase.sql`

Additive, no rewrite, exactly as the contract's §D:

```sql
CREATE TABLE clean_rep_phase (
    phase_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    clean_set_id   INTEGER NOT NULL REFERENCES clean_set(set_id),
    rep_index      INTEGER NOT NULL CHECK (rep_index > 0),
    lower_ms       INTEGER, lift_ms INTEGER, pause_ms INTEGER,
    rom_m          REAL, steadiness REAL, confidence REAL,
    method_version TEXT NOT NULL,
    started_at     TEXT,
    source         TEXT NOT NULL CHECK (source IN ('import','device','manual')),
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (clean_set_id, rep_index)
);
CREATE INDEX idx_clean_rep_phase_set ON clean_rep_phase(clean_set_id, rep_index);
```

Plus the same `no_update`/`no_delete` triggers used by every other clean table. No existing table,
column or index is touched.

### 3.3 Ingest normalisation and validation

`_append_reps` gains `expected_count: int | None = None`; the add-set route passes the body's
`reps`. A new `MotionPayloadError(reason)` carries one of the contract's closed reasons.

- **Legacy path is untouched.** If no item carries a motion key, normalisation and validation
  behave exactly as today: unknown keys dropped, any rep count allowed, no count or index checks.
- **Motion path** (any of `lower_ms`, `lift_ms`, `pause_ms`, `rom_m`, `steadiness`,
  `confidence` present) validates: contiguous `1..n` with no duplicates; `n == expected_count`;
  all-or-none velocity; `motion_version` present and matching `^[a-z][a-z0-9_]*/[0-9]+$`; numeric
  ranges from the contract's table.
- Validation runs **before** the `workout_rep_event` insert. A rejected set writes nothing and the
  client's outbox retries.
- The route maps `MotionPayloadError` to `400 invalid_motion_payload` with `reason`. With
  `watch_motion_enabled` false, motion fields are rejected with the same error and reason
  `feature_disabled`.

### 3.4 Materialisation

Extend the writer at `workout.py:2352`:

- `clean_rep` rows only when the set's reps all carry a velocity — the all-or-none rule makes this
  uniform, and `clean_rep.velocity_mps` stays `NOT NULL`.
- `clean_rep_phase` rows whenever motion fields are present, one per rep, `method_version` copied
  from the event.
- Replay must be a no-op, using the same idempotency mechanism the existing `clean_rep` write
  already relies on. Do not invent a second one.

### 3.5 Descriptive report — `features/rep_tempo.py`

Modelled on `rep_velocity.py`:

- `session_report(conn, session_id)` returns, per set: rep count, source, median phase durations,
  TUT, duration CV, median confidence, and either a summary or an abstention reason.
- Abstentions: `no_detail`, `incomplete_set`, `low_confidence` (median confidence below a module
  constant, documented with its reason), `feature_disabled`.
- Reads the clean layer, writes nothing, and imports no prescription, calibration or readiness
  module. A test asserts the import boundary.

### 3.6 Session detail

`history.detail`'s `device_reps` items gain the optional motion fields; `velocity_mps` becomes
nullable; the set gains `motion_version`. Response is additive in shape, and the null-velocity case
only appears for device sets that carried motion.

### 3.7 Config

`config/ios.v1.yaml` gains `watch_motion_enabled` (code default `false`, fail-closed parsing like
`watch_enabled`, documented with its domain reason). It gates acceptance of motion fields, nothing
else.

## 4. Failure matrix

| Condition | Response | Stored |
|---|---|---|
| Legacy payload, no motion keys | unchanged | unchanged |
| Motion payload, feature disabled | `400 feature_disabled` | nothing |
| `rep_index` gap or duplicate | `400 index_gap` / `index_duplicate` | nothing |
| `n != reps` on a motion payload | `400 count_mismatch` | nothing |
| Some reps with velocity, some without | `400 mixed_velocity` | nothing |
| Out-of-range number | `400 range` | nothing |
| Motion fields without `motion_version` | `400 version_missing` | nothing |
| `motion_version` malformed | `400 version_format` | nothing |
| Valid motion payload | `201`, receipt | `clean_rep_phase` (+ `clean_rep` if velocities present) |

## 5. Tests, narrowest first

```
.venv/bin/python -m pytest tests/test_watch_motion_capture.py -q      # new
.venv/bin/python -m pytest tests/test_ios_api.py tests/test_history.py -q
.venv/bin/python -m pytest tests/test_docs_manifest.py tests/test_docs_consistency.py -q
.venv/bin/ruff check strength_coach tests
./check.sh            # fast lane, before calling the work done
./check.sh full       # once, before any push
```

New test file covers: legacy payload regression (byte-identical event JSON), each rejection reason,
atomicity (no rows on failure), materialisation replay no-op, tempo report abstentions, and the
import-boundary assertion.

## 6. Data quality, privacy, documentation

- No real data is read or written by the tests; fixtures only.
- Derived motion values are personal training data: they live in `clean_rep_phase` only, are never
  logged, and are not exported anywhere new.
- `docs/DATA-MODEL.md` gains the table; `docs/API.md` gains the response fields;
  `docs/manifest.yaml` gains this document's entry. `ROADMAP.md` status is left to the owner.

## 7. Rollback

Drop `clean_rep_phase` and remove `watch_motion_enabled`. No existing row, column or index is
touched, so the migration is reversible without a data rewrite. Capture stops as soon as the config
key is false, regardless of client version.

## 8. Open decisions before implementation

| # | Decision | Recommendation |
|---|---|---|
| A | Axis source | Taxonomy property. Config-driven, auditable, and adding a lift is a YAML edit |
| B | First-cut coverage | Every `vbt_family` member with an unambiguous single axis: bench, squat, sumo, conventional deadlift, hinge, trap bar, rack pull, good morning, RDL, horizontal push, vertical push, horizontal pull (rows move horizontally). Leave `null` for hip thrust, cables, machines, carries and isolation work until a spike proves the axis |

Neither blocks the migration, the ingest work or the report; both block only the taxonomy commit.

## 9. Files deliberately not changed

`clean_rep` and its readers, migrations 0001–0075, `vbt_calibration`, `vbt_analysis`,
`vbt_performance`, `rep_velocity`, every prescription and readiness module, all Swift code, and the
portfolio contract and plan beyond their status lines.

## 10. Risks

| Risk | Mitigation |
|---|---|
| Ingest regression breaks live phone/watch logging | Legacy path provably untouched: byte-identical event JSON test |
| Exact rep-count enforcement rejects valid legacy payloads | Count/index checks apply to motion payloads only (§3.3) |
| Materialisation replay duplicates phase rows | Reuse the existing `clean_rep` idempotency mechanism; replay test |
| Report quietly becomes a prescription input | Import-boundary test, same pattern as `rep_velocity` |
| A mid-session plan change loses captured data | Server never validates against `motion_axis`; it stores what arrives |
