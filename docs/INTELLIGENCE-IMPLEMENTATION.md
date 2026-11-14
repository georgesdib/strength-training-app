# TRAINING INTELLIGENCE — IMPLEMENTATION (INT-1)

**Status:** INT-1 foundation implemented 2026-11-14; INT-1b MCP transport implemented 2026-11-14.
Read-only, provider-neutral, independently runnable.
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
| MCP server, tools, resources (INT-1b) | implemented |
| `get_session_details` (INT-1b) | implemented |
| Dedicated MCP client tokens and CLI (INT-1b) | implemented |
| Strict tool-argument checking at the MCP boundary (INT-1b) | implemented |
| Synthetic performance baseline for `get_training_overview` (INT-1b) | recorded |
| Baseline context package, evidence producers, INT-2 catalogue | **not implemented — INT-2** |
| REST route, iOS adapter, model providers | **not implemented — INT-3 onward** |

The plan's INT-1 originally bundled the MCP skeleton and two tools. The approved implementation
prompt narrowed INT-1 to the foundation and deferred the transport, so that scope moved to
**INT-1b**, delivered 2026-11-14 and recorded in the plan and roadmap. Everything marked INT-1b
below is implemented; model integration, the REST route, the iOS adapter and the rest of the
catalogue remain absent.

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
| `capabilities/session.py` | `get_session_details` (INT-1b) |
| `resources.py` | `strength://athlete/profile` envelope (INT-1b) |
| `tokens.py` | dedicated MCP client tokens: create, list, rotate, revoke, authenticate (INT-1b) |
| `mcp/db.py` | SQLite `mode=ro` connection for the transport (INT-1b) |
| `mcp/security.py` | principal context, bearer middleware, rate/concurrency limits (INT-1b) |
| `mcp/validation.py` | strict tool-argument middleware: unknown keys and type coercion rejected (INT-1b) |
| `mcp/tools.py`, `mcp/resources.py` | thin adapters over the capability service (INT-1b) |
| `mcp/app.py`, `mcp/run.py` | server/app factory and standalone runner (INT-1b) |

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
| `tests/test_intelligence_boundaries.py` | no `web`/`agents`/`mcp` imports in the capability package, only `mcp/` imports the SDK, read-only connection, no mutation-shaped names |
| `tests/test_intelligence_session.py` | session composition, imported/voided routing, projections, validation, read-only |
| `tests/test_intelligence_tokens.py` | token lifecycle, revocation, rotation, CLI, server refusals |
| `tests/test_intelligence_mcp_protocol.py` | tool discovery, schemas, annotations, invocation, parity, errors, resource, modern and legacy eras |
| `tests/test_intelligence_mcp_http.py` | 401/403, Host protection, body cap, rate limit, successful discover |
| `tests/test_intelligence_mcp_limits.py` | rate and concurrency middleware |
| `tests/intelligence_support.py` | synthetic builders only |
| `tools/intelligence_benchmark.py` | synthetic performance baseline (not a test) |

Commands:

    python -m pytest tests/test_intelligence_*.py -q -n 0
    python -m ruff check strength_coach/intelligence tests/test_intelligence_*.py tests/intelligence_support.py

## 11. Known limitations

- **The switch is off by default.** The server refuses to start until `enabled: true` is set and at
  least one active client token exists.
- **The catalogue is two tools and one resource.** Progression, adherence, VBT, prescription,
  comparison, programme block and weekly review are INT-2/INT-3.
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
## 13. MCP server architecture (INT-1b)

    MCP client (Claude, another host, the Python client)
        |
        |  POST /mcp   Authorization: Bearer <client token>
        v
    BearerAuthMiddleware      -> 401 / 403, sets the request Principal
        v
    LimitMiddleware           -> 429 on the per-client rate or concurrency bound
        v
    MCP SDK (Streamable HTTP, revision 2026-07-28, legacy clients included)
        v
    StrictToolArgumentsMiddleware -> rejects unknown keys and coerced types
        v
    tool handler -> IntelligenceService -> read-only SQLite -> envelope
        v
    structuredContent (the same envelope INT-1 defines)

- The transport is a separate package: `strength_coach/intelligence/mcp/`. The capability package
  imports neither the SDK nor HTTP, and a test asserts that only `mcp/` imports `mcp`.
- The MCP dependency is an optional extra (`strength-coach[intelligence]`). The coaching runtime,
  the web UI, the CLI and every existing test work without it; only the transport imports it.
- Tools call `IntelligenceService.execute` against a fresh `mode=ro` connection per call. No
  analytics are duplicated in a handler, and no handler reads a table directly.
- Modern requests are stateless (no protocol session, no sticky routing). A legacy client on
  2025-11-25 is served by the same app; a test exercises both eras.
- Tools and resources only. No prompts, sampling, roots, subscriptions, logging or tasks.

## 14. Install, run and operate

    pip install "strength-coach[intelligence]"

    # provision one token per client; the plaintext is printed once and never stored
    strength-coach intelligence token create --label "Claude Desktop"
    strength-coach intelligence token list

    # enable the feature, then run the server as its own process
    #   config/intelligence.v1.yaml: enabled: true
    strength-coach intelligence serve --db data/coach.db
    # equivalent: strength-intelligence-mcp --db data/coach.db

The endpoint is `http://127.0.0.1:8765/mcp` by default. The server refuses to start (exit 2) when
the switch is off, the database is missing, or no active client token exists. Every run prints the
endpoint and a reminder that a bearer token is required; it never prints a token.

Transport keys in `config/intelligence.v1.yaml`:

| Key | Default | Meaning |
|---|---|---|
| `bind_host` | `127.0.0.1` | loopback by default; set explicitly for a private network |
| `bind_port` | `8765` | |
| `endpoint_path` | `/mcp` | must start with `/` |
| `allowed_hosts` | `127.0.0.1:*`, `localhost:*` | Host allowlist; `:*` accepts any port |
| `max_request_body_bytes` | 262144 | 1 KiB-1 MiB |
| `rate_limit_per_minute` | 60 | per client; 0 disables |
| `max_concurrent_calls` | 4 | in-flight calls per process |

Private-network deployment: set `bind_host` to the tailnet address **and** add the exact Host
header clients will use to `allowed_hosts`. Tailscale is reachability, not authentication; the
bearer token remains mandatory. Never set `bind_host: 0.0.0.0` on an untrusted network.

## 15. Authentication and token lifecycle

- MCP clients have their own tokens; they are never iOS device credentials. `Principal.kind` is
  `mcp`, and no tool accepts a principal, user or database argument.
- Only the SHA-256 digest is stored, in the git-ignored `config/intelligence.local.yaml`, mode 0600.
  The plaintext token is returned once by `create` or `rotate` and is never written or logged.
- `revoke` sets `revoked_at`; the token immediately returns 403. `rotate` replaces the digest
  and the previous token returns 401. A revoked client cannot be rotated.
- Verification reuses `utils.ios_credentials.verify_secret` (constant-time digest comparison).
- Authentication runs before the MCP layer parses anything: a missing, malformed, over-long or
  unknown token is 401 with `WWW-Authenticate: Bearer realm="strength-intelligence"`; a revoked
  client is 403. No OAuth discovery document is published (ADR-INT-004).
- Tokens, Authorization headers and payloads are never logged. Tests assert tokens are absent from
  logs and that authentication performs no database write.
- The CLI is the provisioning boundary: local shell access is the admin boundary. Tokens are not
  mintable over HTTP.

## 16. Network exposure and security controls

| Control | Implementation |
|---|---|
| Loopback default | `bind_host: 127.0.0.1` |
| DNS rebinding | SDK `TransportSecuritySettings` with an explicit Host allowlist; a foreign Host is 421 |
| Cross-origin | `allowed_origins: []`; browsers are not a supported client |
| Request size | SDK body cap from `max_request_body_bytes`; 413 before parsing |
| Authentication order | bearer middleware outermost: an unauthenticated oversized request is 401, not 413 |
| Rate and concurrency | per-client sliding window and a semaphore; 429 with `Retry-After` |
| Database | SQLite `mode=ro` plus `PRAGMA query_only`; the service also rolls back its read snapshot |
| Errors | tool errors carry `code: message` only; unexpected failures return a fixed message and log the traceback |
| Tool surface | explicit argument allowlist, strict types, read-only annotations, no SQL/table tools |
| Data minimisation | the profile resource excludes injuries, symptoms, measurements and notes; session detail excludes notes, symptoms and form ratings |

Limits are per process. Run one worker; the SDK multiplexes concurrent requests. If more workers
are ever needed, the per-client limits become approximate and would need a shared counter.

## 17. Tool and resource schemas

| Tool | Arguments | Output |
|---|---|---|
| `get_training_overview` | `as_of` (date, optional), `window_weeks` (1-52, default 4) | envelope with `attendance`, `feedback_coverage`, `strength_trend`, `volume`, `readiness_coverage`, `deload` |
| `get_session_details` | exactly one of `workout_id` / `session_id`, `include_ratios` (bool, default false) | envelope with `session`, `strength`, `dose`, `adherence`, `vbt`, `feedback`, `quality`; imported sessions use `sets` and report analysis as unavailable |

Both declare `read_only_hint`, `destructive_hint: false`, `idempotent_hint` and
`open_world_hint: false`, and advertise the envelope as their `outputSchema`.

Resource `strength://athlete/profile` (`application/json`) returns an envelope with:

- `profile`: `effective_from`, `sessions_per_week_target`, `max_session_minutes`,
  `block_start_date`, `volume_budget_enabled`, `main_lift_policy`;
- `constraints`: non-injury structured constraints (`kind`, `region`, `severity`, forbidden
  patterns/exercises);
- `coverage`: included constraints and the number of injury constraints withheld;
- `privacy`: what was excluded and why.

Goal, goal-rank and focus-lift columns are retired (`DEC-STATE-02`) and are not returned; the
canonical contract has been corrected to match. Injury constraints are withheld by policy and
only counted, so a reader knows something exists without it being exposed.

## 18. Performance baseline (2026-11-14, development machine)

**Deployment-target caveat.** These numbers were measured on the development Mac (Apple silicon).
The MCP server is intended to run on a slower Linux host, so they are **not** a service level
objective and not evidence that the endpoint is fast enough there. What they establish is the
shape — cost grows with the length of training history, not with the requested window — and the
command to repeat the measurement on the real host.

Command: `python tools/intelligence_benchmark.py --sessions N --runs R` (synthetic data only).

Environment (measurement machine only): macOS 27.2.1 arm64, 8 cores, Python 3.15.2, SQLite
read-only connection, single process, no concurrent load.

| Dataset | Sets | DB | Runs | p50 | p95 | max |
|---|---|---|---|---|---|---|
| 200 sessions / 100 readiness days | 3,600 | 3.87 MB | 40 | 220.5 ms | 299.4 ms | 382.9 ms |
| 600 sessions / 300 readiness days | 10,800 | 10.22 MB | 20 | 573.1 ms | 596.3 ms | 620.0 ms |

All executions returned `status: ok`. The cost grows roughly linearly with history because the
dashboard's performance ratio rebuilds session e1RM across the whole history on every read; that
is the dominant term, not the window size. The work is single-threaded Python, so a slower core
moves these numbers roughly in proportion to single-core speed.

**Repeat before enabling on the deployment host:**

    python tools/intelligence_benchmark.py --sessions <stored sessions> --runs 20 --json

Record the result beside the deployment unit. If p95 is at or above one second, do not enable the
transport silently: update ADR-INT-010 first and choose, in this order, a bounded lookback for the
performance ratio (a metric decision, not a transport one) or an opt-in cache keyed on the database
stamp. Caching stays deferred until that measurement exists.

**Platform notes for the Linux host**

- Set the host timezone. The authoritative training date is the server-local calendar date; an
  unset TZ on a headless machine makes it UTC and can shift the window by a day. A stored IANA
  profile timezone remains ROADMAP §4.19 work; the envelope reports the platform zone name.
- The service user must be able to read the database. The transport opens it `mode=ro` and never
  runs migrations; point `--db` at the existing database rather than copying it into a second
  writable store.
- If clients reach the server by hostname, add the exact `Host` values to `allowed_hosts`.
- On a single-board host set `max_concurrent_calls` to 1 or 2 so a slow overview cannot occupy
  every slot, and keep `include_ratios` false (the default).
- The SDK and uvicorn are pure Python or shipped as aarch64 wheels; Python 3.11+ is required and
  the optional extra installs without a compiler.

Caveats: synthetic distribution, a warm OS page cache, one machine, one process; the numbers are a
shape, not a service level objective.
