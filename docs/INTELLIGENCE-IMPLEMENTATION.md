# TRAINING INTELLIGENCE — IMPLEMENTATION (INT-1)

**Status:** INT-1 foundation implemented 2026-11-14. Read-only, provider-neutral, no transport.
**Scope owner:** the canonical plan is the portfolio
[Training Intelligence plan](https://github.com/georgesdib/strength-app/blob/main/docs/plans/TRAINING-INTELLIGENCE.md);
the payload contract is the
[Training Intelligence contract](https://github.com/georgesdib/strength-app/blob/main/docs/contracts/TRAINING-INTELLIGENCE-CONTRACT.md).
This page records how the backend implements the foundation and what is deliberately absent.

## 1. What INT-1 delivered

| Element | State |
|---|---|
| Provider-neutral capability layer (`strength_coach/intelligence/`) | implemented |
| Canonical response envelope and evidence references | implemented |
| Typed requests, validation and capability versioning | implemented |
| Execution service with a typed success/failure result | implemented |
| Read-only execution (deferred transaction, rolled back) | implemented |
| Bearer authentication and principal model | implemented |
| Configuration switch and bounds (`config/intelligence.v1.yaml`) | implemented |
| One reference capability, `get_training_overview` | implemented |
| Automated tests (envelope, registry, config, auth, execution, boundaries) | implemented |
| MCP server, tools, resources | **not implemented — INT-1b** |
| `get_session_details` | **not implemented — INT-1b** |
| Baseline context package, evidence producers, INT-2 catalogue | **not implemented — INT-2** |
| REST route, iOS adapter, model providers | **not implemented — INT-3 onward** |

The plan's INT-1 originally bundled the MCP skeleton and two tools. The approved implementation
prompt narrowed INT-1 to the foundation and deferred the transport, so that scope moved to
**INT-1b** and is recorded as such in the plan and roadmap. Nothing in the deferred scope exists in
code.

## 2. Package layout

| Module | Responsibility |
|---|---|
| `envelope.py` | frozen `Envelope`, `FactBlock`, `Period`, `Provenance`, `Privacy`; contract validation |
| `errors.py` | `IntelligenceError` (caller-facing codes) and `EnvelopeError` (programming error) |
| `methods.py` | the allow-list of owning functions a fact may name |
| `context.py` | request-context identity: builder version, database stamp, config revision, context hash |
| `config.py` | switch and bounds, validated from `config/intelligence.v1.yaml` |
| `auth.py` | bearer verification against `ios_device`, `Principal`, internal principal |
| `registry.py` | capability specs, name/version rules, request parsing helpers |
| `service.py` | execution, read snapshot, failure mapping, structured logging |
| `capabilities/overview.py` | the reference capability |
| `capabilities/__init__.py` | import-time registration (no discovery) |

Layering: this package may import `features`, `store`, `utils` and `domain`; it must not
import `strength_coach.web`, `strength_coach.agents` or `mcp`. A test asserts that with an AST
scan, so a transport or a model client cannot be pulled in by accident.

## 3. The envelope, as implemented

The implemented shape matches contract §3 with two additive details:

- `capability_version` is a top-level field so a response is self-describing without a lookup;
- the Python `Privacy.classification` is serialised as `class`, the contract's key.

Validation enforces: the fixed subject (`{"athlete": "self"}`), a known status, a non-reversed
period, a registered `method` on every fact, evidence references that resolve, unique evidence ids,
the gate/comparability vocabularies from `features/evidence.py`, at most two observations, a UTC
`generated_at`, a fixed privacy vocabulary and strict JSON serialisability. A response that breaks
any rule is a programming error: the execution service logs it and returns a fixed internal failure,
never the broken payload.

Evidence items are the untouched `features.evidence.EvidenceItem.as_dict()` output. The envelope
does not define a second evidence schema.

## 4. Deterministic authority

`get_training_overview` computes nothing. It calls:

| Fact | Owning function |
|---|---|
| `attendance` | `features.attendance.summary` (through the dashboard) |
| `feedback_coverage` | `features.progress.dashboard` |
| `strength_trend` | `features.progress.dashboard` (performance points) |
| `volume` | `features.volume.compute` (through the dashboard) |
| `readiness_coverage` | `store.queries.readiness_series` (count only) |
| `deload` | `features.deload.decision` |

The window convention (`7 * weeks - 1` days ending on `as_of`) is the dashboard's, not a second
one. Symptom-derived fields (`injury_free_weeks`, `symptom_weeks_logged`, the back level) are
projected out; readiness contributes an observed-day count, never values. The privacy block records
both.

## 5. Execution and failure policy

`IntelligenceService.execute(principal, name, payload)`:

1. refuses to run without a `Principal` (TypeError — a programming error, not a request error);
2. returns `unavailable` when the configuration switch is off;
3. looks up the capability (`not_found`), parses the request (`invalid_argument` with a field);
4. opens a deferred read transaction, stamps the context, calls the handler, validates the envelope;
5. returns a `CapabilityResult` — never raises for an expected failure;
6. logs one line: capability, outcome, duration, principal kind, and a **hash** of the arguments.

Unexpected exceptions and invalid envelopes become `internal` with the fixed message
"intelligence capability failed"; the traceback goes to the log only.

## 6. Authentication and authorization

- Reuses the existing per-device bearer token (`ios_device.token_hash`, SHA-256 digest,
  constant-time verification via `utils.ios_credentials`). No second credential store, no OAuth
  server, no user or tenant model.
- Missing, malformed, over-long or unknown tokens → `401`; a revoked device → `403`.
- Authentication **does not write** `last_seen_at`. The iOS facade keeps that bookkeeping; this
  boundary must work on a read-only connection, so it verifies without the update. A test asserts
  `total_changes` and `last_seen_at` are unchanged.
- `Principal` carries the device id and kind (`phone`/`watch`). In-process callers use
  `INTERNAL_PRINCIPAL`. Nothing in a capability request can set either.
- What this does not add: per-client intelligence tokens, scopes, MCP OAuth metadata or a token
  issuance command. Those are ADR-INT-004 and belong to the transport phase.

## 7. Configuration

`config/intelligence.v1.yaml` (no secrets, no model settings):

| Key | Default | Range | Meaning |
|---|---|---|---|
| `version` | 1 | must be 1 | file schema |
| `enabled` | false | boolean | execution switch; disabled by default |
| `max_window_days` | 400 | 28–400 | hard bound on any capability window |
| `max_sessions_per_page` | 20 | 1–100 | page bound for paginated capabilities |

Unknown keys, wrong types, out-of-range values and a missing file are errors that name the file.
`enabled` gates execution, not import: tests and in-process callers construct an enabled
configuration explicitly.

## 8. Read-only guarantees

Three layers, each tested:

1. **Transaction**: execution runs inside `BEGIN` (deferred, never `IMMEDIATE`) and is always
   **rolled back**, so an accidental write inside a capability is inert and the read lock is
   released.
2. **Database mode**: the overview test opens `file:…?mode=ro` and asserts both that the capability
   works and that an `INSERT` raises `attempt to write a readonly database`.
3. **Registry**: every spec is `read_only=True`; names must start with `get_` or `compare_`; a
   duplicate or a mutated name is rejected at import.

Row counts and `total_changes` are captured before and after execution in a test.

## 9. Limits and observability

- Input bounds: 1–52 weeks and the configured day ceiling; `as_of` may not be in the future.
- No hard in-process timeout. A cancellable timeout belongs to the transport that can abandon a
  request; INT-1 records duration instead.
- No pagination yet: the overview returns bounded aggregates only.
- Logging is metadata only (capability, outcome, duration, principal kind, argument hash). No token,
  no payload, no health value. Tested with `caplog`.

## 10. Tests

| File | Covers |
|---|---|
| `tests/test_intelligence_envelope.py` | shape, vocabularies, evidence references, JSON safety, determinism |
| `tests/test_intelligence_registry.py` | registration rules, unknown capability, request helpers |
| `tests/test_intelligence_config.py` | defaults, bounds, unknown keys, missing file |
| `tests/test_intelligence_auth.py` | success, 401 variants, revocation, no writes, no token in logs |
| `tests/test_intelligence_overview.py` | composition vs owning services, projections, no-data, validation, determinism, read-only, failure mapping |
| `tests/test_intelligence_boundaries.py` | no `web`/`agents`/`mcp` imports, read-only connection, no mutation-shaped names |
| `tests/intelligence_support.py` | synthetic builders only |

Commands:

    python -m pytest tests/test_intelligence_*.py -q -n 0
    python -m ruff check strength_coach/intelligence tests/test_intelligence_*.py tests/intelligence_support.py

## 11. Known limitations

- **No transport.** Nothing is exposed over HTTP or MCP; the switch is off and no route exists.
- **No second capability.** Imported-session detail and the rest of the catalogue are INT-1b/INT-2.
- **No evidence items are emitted** by `get_training_overview`: the owning services do not produce
  them for these aggregates. The envelope supports and validates them; INT-2 adds the producers.
- **No baseline context package.** `provenance.context_hash` covers the request context (capability,
  arguments, database and config revisions) under builder version `context.v1`. INT-2 replaces the
  argument component with the baseline package without changing the field.
- **Timezone** is the platform's local zone name, not an IANA profile timezone (that is
  ROADMAP §4.19). The authoritative date remains the server's local calendar date.
- **No cache.** Every call reads; caching is deferred until latency is measured.
- **No hard timeout**; no result-size truncation (both transport concerns).

## 12. Adding an INT-2 capability

1. Call the owning function; do not compute.
2. Register the owner in `methods.py` in the same change.
3. Add a `CapabilityRequest` subclass with strict parsing and a `CapabilitySpec` with a version.
4. Build `FactBlock`s (`basis`, `method`, `n`, `gate` where the owner provides one) and the
   envelope.
5. Add tests: composition vs the owner, invalid input, missing data, read-only, determinism.
6. Update this page's capability table and the plan's phase status; never mark INT-2 complete here.
