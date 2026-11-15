# TRAINING INTELLIGENCE — BACKEND IMPLEMENTATION

**Status:** INT-1 foundation, INT-1b MCP transport, the audit remediation, the INT-2 capability
catalogue and INT-3 (weekly review plus the iOS read surface) are implemented; **INT-3 closed
2026-11-15**. Read-only, provider-neutral, independently runnable. The baseline context package and
model path (INT-5), evidence producers for the aggregate capabilities and the INT-4 native model
surface are not implemented.
**Scope owner:** the canonical plan is the portfolio
[Training Intelligence plan](https://github.com/georgesdib/strength-app/blob/main/docs/plans/TRAINING-INTELLIGENCE.md);
the payload contract is the
[Training Intelligence contract](https://github.com/georgesdib/strength-app/blob/main/docs/contracts/TRAINING-INTELLIGENCE-CONTRACT.md).
This page records how the backend implements the delivered intelligence surface (INT-1, INT-1b,
remediation and INT-2) and what is deliberately absent. Phase boundaries stay as the plan states
them: delivered work is marked delivered, and later phases are not advanced by this page.

## 1. What is delivered

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
| Immediate token revocation/rotation without restart (remediation) | implemented |
| Structured audit record for every tool/resource invocation (remediation) | implemented |
| Tool timeout and serialized-result cap (remediation) | implemented |
| Dedicated systemd unit and deployment guide (remediation) | implemented (not deployed) |
| Live HTTP integration test with the official client (remediation) | implemented |
| INT-2 catalogue: seven further tools (INT-2) | implemented |
| INT-2 resources: `strength://programme/current`, `strength://overview/current` (INT-2) | implemented |
| `get_weekly_review` capability (INT-3) | implemented; INT-3 closed 2026-11-15 |
| `GET /api/ios/v1/intelligence/weekly-review` (INT-3) | implemented; INT-3 closed 2026-11-15 |
| iOS weekly-review screen and adapter (INT-3) | implemented 2026-11-15 |
| Baseline context package (shared compact context) | **not implemented — INT-5** |
| Evidence producers for the aggregate capabilities | **deferred** — owners do not emit evidence items for these aggregates; `get_session_details` returns the real evidence |
| Native model surface (five capabilities, `Tool` adapters) | **not implemented — INT-4** |
| Model providers and narration | **not implemented — INT-4/INT-5** |

The plan's INT-1 originally bundled the MCP skeleton and two tools. The approved implementation
prompt narrowed INT-1 to the foundation and deferred the transport, so that scope moved to
**INT-1b**, delivered 2026-11-14 and recorded in the plan and roadmap. **INT-2** then delivered the
remaining read-only catalogue and its two resources on 2026-11-14, and **INT-3** delivered the
weekly review, its REST route and the iOS read surface on 2026-11-15. Everything marked INT-1,
INT-1b, INT-2 and INT-3 above is implemented. What remains is the baseline context package and
model path (INT-5), evidence producers for the aggregate capabilities, and the INT-4 native model
surface; none of those is claimed here.

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
| `capabilities/_common.py` | INT-2 envelope/window helpers (no analytics) |
| `capabilities/progression.py` | `get_exercise_progression` (INT-2) |
| `capabilities/readiness.py` | `get_readiness_history` (INT-2) |
| `capabilities/adherence.py` | `get_adherence_analysis` (INT-2) |
| `capabilities/prescription.py` | `get_prescription` (INT-2) |
| `capabilities/vbt.py` | `get_vbt_analysis` (INT-2) |
| `capabilities/programme.py` | `get_programme_block_summary` (INT-2) |
| `capabilities/compare.py` | `compare_training_periods` (INT-2) |
| `store/queries.py` | `prescription_detail()` read helper (INT-2) |
| `resources.py` | `strength://athlete/profile` envelope (INT-1b) |
| `tokens.py` | dedicated MCP client tokens: create, list, rotate, revoke, authenticate; reloaded per request (INT-1b, remediation) |
| `audit.py` | one structured metadata-only audit record per invocation (remediation) |
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
- **Response deadline:** the MCP adapter waits `tool_timeout_seconds` (default 20) for a tool or
  resource. On expiry it returns a sanitised `tool_timeout` error. The worker thread is not
  cancellable and finishes its bounded read; its result is discarded. The deadline bounds the
  response, not the work — see section 18 for the benchmark context.
- **Serialized-size cap:** an envelope larger than `max_tool_result_bytes` (default 1 MiB) is
  rejected with `result_too_large`. The envelope is never truncated, because a partial fact set
  would misrepresent coverage.
- No pagination yet: the overview returns bounded aggregates only.
- Logging is metadata only. The transport emits one structured audit record per invocation
  (section 19); the capability service keeps a DEBUG line for in-process callers. No token, no
  payload, no health value. Tested with `caplog`.

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
| `tests/test_intelligence_audit.py` | one complete audit record per tool/resource, no payload or token, logging failure tolerated |
| `tests/test_intelligence_token_reload.py` | revocation/rotation without restart, fail-closed file, concurrent readers |
| `tests/test_intelligence_runtime_limits.py` | response deadline, oversized result and resource, row-count extraction |
| `tests/test_intelligence_mcp_live.py` | real HTTP server: auth, tools, resources, no-data, errors, read-only database, clean shutdown |
| `tests/test_intelligence_int2.py` | the seven INT-2 capabilities: owner composition, validation, privacy, determinism, read-only |
| `tests/test_intelligence_mcp_int2.py` | INT-2 discovery, schemas, strict arguments, resource reads, MCP/service parity |
| `tests/test_intelligence_weekly.py` | weekly review golden fixture, week boundary, empty/imported weeks, read-only, REST route, MCP parity |
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
- **No cache.** Every call reads; caching is deferred until the target host measurement exists.
- **The timeout does not cancel work.** It bounds the response; a blocked SQLite read finishes in
  its worker thread and its result is discarded. Leftover work is a bounded read on a connection
  owned by that call.
- **Rate and concurrency limits are per process.** Run one worker; the SDK multiplexes requests.
- **The readiness score series is capped at the most recent 120 observed days.** Each day calls the
owning scorer; the cap keeps one request bounded and is reported in coverage.
- **Prescription and adherence payloads are capped** (40 items, 20 modifiers, 60 periods, 40
exercises, 20 workouts) and report truncation; nothing is silently omitted.
- **VBT per-set rows are summarised**, because the owner payload can be large; cohort and drift
  detail is preserved.
- **The systemd unit is installed and running on the ODROID as a host-specific variant.** The
  checked-in template has not been validated verbatim there; the live unit adds `ReadWritePaths`
  for the WAL files.

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
    strength-coach --db data/coach.db intelligence serve
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
| `tool_timeout_seconds` | 20 | per-call response deadline, 1-300 s |
| `max_tool_result_bytes` | 1048576 | serialized envelope cap, 1 KiB-10 MiB |

Private-network deployment: set `bind_host` to the tailnet address **and** add the exact Host
header clients will use to `allowed_hosts`. Tailscale is reachability, not authentication; the
bearer token remains mandatory. Never set `bind_host: 0.0.0.0` on an untrusted network.

## 15. Authentication and token lifecycle

- MCP clients have their own tokens; they are never iOS device credentials. `Principal.kind` is
  `mcp`, and no tool accepts a principal, user or database argument.
- The token file is **re-read on every request**, so the CLI `revoke`/`rotate` takes effect without
  restarting the server. Writes are atomic (`os.replace`), so a reader sees the old or the new file,
  never a partial one; an unreadable file denies every request (fail closed) instead of falling
  back to a stale in-memory list.
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
| Response deadline | `tool_timeout_seconds` (default 20 s); sanitised `tool_timeout` error, worker not cancellable |
| Result size | `max_tool_result_bytes` (default 1 MiB); typed `result_too_large`, never a truncated envelope |

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

**Deployment-target caveat.** The first two rows were measured on the development Mac (Apple
silicon). The MCP server runs on a slower Linux host, and that host was measured separately on
2026-11-14 (last row): it is **not** a service level objective, but it is the number that governs
whether the transport may be enabled. The shape — cost grows with the length of training history,
not with the requested window — holds on both.

Command: `python tools/intelligence_benchmark.py --sessions N --runs R` (synthetic data only).

Environment, development Mac (measurement machine only): macOS 27.2.1 arm64, 8 cores, Python
3.15.2, SQLite read-only connection, single process, no concurrent load.
Environment, deployment host (2026-11-14): Linux 6.18.44 aarch64, 4 cores, Python 3.13.5, same
read-only single-process conditions.

| Dataset | Sets | DB | Runs | p50 | p95 | max |
|---|---|---|---|---|---|---|
| 200 sessions / 100 readiness days (Mac) | 3,600 | 3.87 MB | 40 | 220.5 ms | 299.4 ms | 382.9 ms |
| 600 sessions / 300 readiness days (Mac) | 10,800 | 10.22 MB | 20 | 573.1 ms | 596.3 ms | 620.0 ms |
| 377 sessions / 189 readiness days (**deployment host**) | 6,786 | 6.5 MB | 20 | 3,101.9 ms | 3,169.4 ms | 3,284.2 ms |

All executions returned `status: ok`. The cost grows roughly linearly with history because the
dashboard's performance ratio rebuilds session e1RM across the whole history on every read; that
is the dominant term, not the window size. The work is single-threaded Python, so a slower core
moves these numbers roughly in proportion to single-core speed.

**Repeat before enabling on the deployment host:**

    python tools/intelligence_benchmark.py --sessions <stored sessions> --runs 20 --json

The tool now also benchmarks every registered capability in direct mode and over the real MCP
Streamable HTTP transport, with per-capability distributions, errors, envelope statuses, analytics
readiness and a labelled MCP-overhead difference (see
[`docs/INTELLIGENCE-DEPLOYMENT.md`](INTELLIGENCE-DEPLOYMENT.md) §13). The HTTP benchmark has not
been run against the ODROID deployment yet, so the transport objective is not closed.

Record the result beside the deployment unit. **Measured 2026-11-14: p95 3,169.4 ms at the real
history size (377 sessions), all `status: ok`.** That is above the one-second threshold, so the
transport must not be enabled on this host until the ADR-INT-010 addendum is decided.

### Profiling investigation — 2026-11-14

Method: the synthetic 377-session database from `tools/intelligence_benchmark.py`, one warm-up
call, then `IntelligenceService.execute` timed with `perf_counter`; components timed directly on
the same read-only connection (median of 3–5); one `cProfile` call for call counts; scaling on
100/200/377/600 sessions. No real training data. Environment: Linux 6.18.44 aarch64, 4 cores,
Python 3.13.5, local SQLite, no concurrent load.

Full request: cold 3,243 ms, warm median 3,110 ms (benchmark p50 3,101.9). The envelope and
provenance hash cost about 40 ms; JSON serialisation is outside the timed path.

| Component | ms | Share |
|---|---:|---:|
| `deload.decision` | 2,021 | 65% |
| — `RuleContext.from_store` (whole-history build) | 1,349 | 43% |
| — `policy.evaluate` (all five rules) | 689 | 22% |
| `progress.dashboard` | 1,050 | 34% |
| — `performance_points` (ratio, all-history e1RM) | 507 | 16% |
| — `_sets` (all clean sets into pandas) | 221 | 7% |
| — `volume.compute` | ~150 | 5% |
| — `attendance.summary` | 111 | 4% |
| `queries.readiness_series` | 1 | <1% |

All-rule evaluation takes 714 ms; `rule_ids=["PRG-SPINE-001"]` takes 381 ms and returns
**identical verdict details** on this dataset (verified). `deload.reactive_reason` evaluates the
whole document to read one verdict.

**Root cause.** The dominant cost is `deload.decision`: `reactive_reason` builds a
`RuleContext` with no `start`, so `History.load` reads every `clean_set` row, runs
`derived.enrich` over the full frame and re-derives ISO weeks, then the policy evaluates all
rules. The suspected ratio rebuild is real but secondary: `_session_lift_e1rms` rescans all sets
and re-estimates e1RM (281 ms scan, 507 ms including point history).

**Scaling (full call, p50).** 100 sessions 1,079 ms · 200 1,810 ms · 377 3,110 ms · 600
4,578 ms — approximately linear at ~8 ms/session over this range.

**Verified options (not implemented — profiling only).**

1. Evaluate only `PRG-SPINE-001` in `reactive_reason`: 714 → 381 ms, same verdict, no
   semantic change.
2. Bound the deload context (e.g. `start` = 12 weeks): context 1,349 → 209 ms on an 84-day
   bound, and the last-two-week costs and cap are unchanged. The verdict's full weekly-cost map
   shrinks (109 → 13 weeks), so the bound is a behaviour/documentation decision, not a free
   change.
3. Together, the deload path falls 1,976 → 258 ms, projecting the full request to about 1.4 s.
4. A ratio lookback remains a separate metric decision worth ~0.5 s; a cache is not justified
   until 1 and 2 are measured in place.

**Decision gates.** Option 1 is semantics-preserving; option 2 needs an explicit decision because
it changes the details payload and the history horizon; option 4 changes a metric definition.

Reproduce: `python tools/intelligence_benchmark.py --sessions 377 --runs 20 --json` gives the
end-to-end numbers; component timings came from `time.perf_counter` around `progress.dashboard`,
`deload.decision`, `RuleContext.from_store`, `policy.evaluate` (all rules and
`rule_ids=["PRG-SPINE-001"]`), `performance_points` and `_sets` on the same read-only connection,
and `cProfile -s cumulative` over one call supplied the call-count ranking.

### Implemented remediation — selective PRG-SPINE-001 evaluation (2026-11-14)

`deload.reactive_reason` now calls
`evaluate(document, context, rule_ids=("PRG-SPINE-001",))` instead of evaluating every rule to
read one verdict. Nothing else changed: the context build, the rule implementation, the
thresholds, the verdict details and the full-policy path for every other caller are untouched.

Correctness evidence (`tests/test_deload_reactive.py`):

- the reactive reason with the old full evaluation and with the selective path is identical on
  the same two-over-cap-weeks fixture;
- `reactive_reason` passes exactly `("PRG-SPINE-001",)` to `evaluate` (spy assertion);
- full and selective evaluation return the same verdict, details and evidence for
  `PRG-SPINE-001`, while the unfiltered path still returns a verdict for every rule.

Measured after the change (same host, dataset and 20-run methodology):

| Metric | Before | After | Change |
|---|---:|---:|---:|
| `get_training_overview` p50 | 3,101.9 ms | **2,729.7 ms** | −372.2 ms (−12.0%) |
| p95 | 3,169.4 ms | **2,873.7 ms** | −295.7 ms |
| max | 3,284.2 ms | 2,923.3 ms | −360.9 ms |
| `deload.decision` | 2,021.1 ms | **1,695.8 ms** | −325.3 ms |
| `RuleContext.from_store` | 1,348.6 ms | 1,342.9 ms | unchanged |
| `evaluate` (spine only) | 381.0 ms | 373.8 ms | unchanged |

Remaining cost is now the context build (1,343 ms, 49%) followed by the dashboard (998 ms, 37%,
of which the ratio is 516 ms). The request is still above the one-second threshold; ADR-INT-010
accepted the latency-aware budget and enabled the catalogue, so this remains the optimisation
target (T-3) rather than a deployment gate.

**Context investigation (not implemented).** `PRG-SPINE-001` consumes the whole
`context.sets`: its verdict details list the weighted cost of every ISO week with spinal work
(e.g. 109 weeks on this fixture) and its intensity factors read the enriched `e1rm_kg` column.
Truncating the window or skipping `derived.enrich` would change observable verdict details and
could change the intensity factor, so neither is safe without an explicit decision. A minimal
context was therefore left unimplemented.

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
### T-3 profiling (2026-11-14, copied production database)

First T-3 pass on a copied 377-session production database, core family ready, one profiled call per
capability with `cProfile` (profiler overhead included; compare the HTTP benchmark p95 values, not
these raw times):

| Capability | Profiled | Dominant cost |
|---|---:|---|
| get_session_details | 9,018 ms | `workout.summary` → `_summary_load_bases` 3.1 s plus two `RuleContext.from_store` builds 3.3 s |
| get_training_overview | 8,666 ms | `deload.decision` → `reactive_reason` → `training_day.group`; 383 `_records`/`DataFrame.to_dict` calls ~7.0 s |
| get_programme_block_summary | 8,508 ms | same `training_day.group` path inside deload ~7.0 s |
| get_readiness_history | 3,612 ms | `readiness_score.compute` 72×; each `readiness.load` re-parses YAML settings ~3.0 s |

Ranked hypotheses (not implemented):

1. **`training_day.group` in the deload flare check** materialises every session into Python dicts
   even though only the last two training days are needed. Bounding/batching that lookup or
   avoiding per-row `to_dict` should remove most of the overview/programme cost without changing
   the flare rule (must preserve the "last two training days" semantics).
2. **`workout.summary`** repeatedly builds a rule context and load-base map for a single session;
   reuse one context per summary or restrict to the session window.
3. **Readiness settings YAML is parsed per computed score**; cache/load it once per request.

These were hypotheses; the first remediation pass is now implemented.

**T-3 first pass (2026-11-14).**

1. The deload flare check reads only the last `reactive_flares` distinct training dates through a
   bounded query instead of materialising every training day.
2. `ReadinessConfig.load` is cached per path; the readiness score no longer re-parses YAML for every
   observed day.
3. `workout.summary` builds one `RuleContext` and reuses it for the load-base fallback and the
   spinal summary instead of building two.

Re-measured on a fresh copy of the production database (378 sessions, 8,003 sets), real MCP HTTP,
30 requests and 5 warm-ups per capability, core family ready:

| Capability | Before p95 | After p95 |
|---|---:|---:|
| get_training_overview | 4,058 ms | **672 ms** |
| get_programme_block_summary | 3,800 ms | **278 ms** |
| get_readiness_history | 1,663 ms | **377 ms** |
| get_session_details | 6,201 ms | **5,684 ms** |
| get_adherence_analysis | 130 ms | 145 ms |
| compare_training_periods | 194 ms | 189 ms |
| get_exercise_progression | 67 ms | 45 ms |
| get_prescription | 40 ms | 46 ms |
| get_vbt_analysis | 63 ms | 69 ms |

The three main targets fell below 500 ms p95. `get_session_details` remains very_slow (5.7 s p95,
within the accepted 7 s budget but not fast); its dominant remaining cost is `workout.summary`'s
load-base/rule work. This is a documented follow-up, not a blocker for the full catalogue.

**Status (2026-11-14): T-3 first pass closed.** The three targeted optimisations are implemented,
remeasured over real MCP HTTP and reflected in the latency metadata. Follow-up **T-3a** (optional,
not started): reduce session details below the slow band by profiling the remaining
`workout.summary` load-base path; it is not required for the accepted full-catalogue rollout and
must not be described as complete until remeasured.

## 19. Structured audit record (remediation)

Every MCP tool call and resource read emits exactly one JSON line on the
`strength_coach.intelligence.audit` logger:

| Field | Meaning |
|---|---|
| `schema` | `intelligence.audit.v1` |
| `request_id` | generated per invocation (`int-...`), unique |
| `kind` | `tool` or `resource` |
| `name` | tool name or resource URI |
| `client_id` | authenticated MCP client id, never the token |
| `arguments_hash` | canonical-JSON SHA-256 prefix; correlation only, not redaction |
| `duration_ms` | wall time from handler entry to result |
| `result_rows` | rows the capability considered, from its own coverage block, when available |
| `response_bytes` | serialized envelope size; 0 on failure |
| `outcome` | `ok` or the stable error code (`invalid_argument`, `not_found`, `tool_timeout`, `internal`, ...) |
| `status` | envelope status (`ok`/`no_data`/`insufficient`) when a payload exists |

Privacy is structural: the schema has no field for arguments, payloads, notes, health values,
tokens or authorization headers, so none can be logged by accident. The hash is not a substitute
for redaction and no argument value is ever emitted. Error messages are reduced to their code.
Emission is best-effort: a logging failure is swallowed after a debug line and never changes the
result (tested).

The capability service logs at DEBUG so a single INFO audit record exists per MCP invocation.
In-process callers keep the DEBUG line until INT-5 routes them through the same audit helper.

## 20. Deployment (remediation)

`deploy/strength-intelligence-mcp.service` runs the server as a dedicated non-root user
(`strength-intel`), with `ProtectSystem=strict`, `PrivateTmp`, `PrivateDevices`,
`ProtectHome=read-only`, kernel and control-group protection, a restricted address-family list and
no write access anywhere. It reads the database at `/var/lib/strength-coach/coach.db` (opened
`mode=ro`), the configuration at `/etc/strength-coach/intelligence.v1.yaml` and the hashed tokens
at `/etc/strength-coach/intelligence.local.yaml`; it contains no secrets. A read-only SQLite
connection to a WAL database still needs write access to the directory for `-shm`/`-wal`, so the
unit grants `ReadWritePaths` on the data directory while keeping the database itself `mode=ro`. The unit is independent
of `strength-coach-web.service` and binds to loopback by default.

Installation, service-user creation, token provisioning, start/stop, log inspection, revocation
semantics, tailnet exposure and troubleshooting are in
[INTELLIGENCE-DEPLOYMENT.md](INTELLIGENCE-DEPLOYMENT.md). The systemd unit is installed and active on the ODROID (2026-11-15) as a host-specific variant;
the checked-in template's `/opt` and `/var/lib` paths have not been validated verbatim there. The
live unit grants `ReadWritePaths` for the WAL files.

## 21. INT-2 catalogue (2026-11-14)

Nine read-only tools and three resources are registered. Every fact names its owning function in
the method allow-list; the only arithmetic added is the delta between two owner outputs in
`compare_training_periods`.

| Tool | Arguments (MCP spelling) | Owner(s) | Notes |
|---|---|---|---|
| `get_exercise_progression` | `exercise_id`, `as_of?`, `window_days` 28-365, `include_sessions`, `limit_sessions` 1-20 | `strength_trend`, `exercise_history` | Rolling median and breaks are the owner's; a calculated e1RM is not a tested maximum. |
| `get_readiness_history` | `start`, `end`, `fields?` | `queries.readiness_series`, `readiness_score.compute` | Default is the score only; raw health fields must be named. Score series capped at 120 observed days. |
| `get_adherence_analysis` | `weeks?` or `start`/`end`, `as_of?`, `group_by`, `exercise_id?`, `session_type?` | `adherence_analytics.analytics` | Completed app workouts only; no block dimension. Lists capped and truncation reported. |
| `get_prescription` | `prescription_id?`, `for_date?`, `include_provenance?` | `queries.prescription_detail` | Persisted artifact only; an unstarted issued plan is a preview. Items/modifiers capped. |
| `get_vbt_analysis` | `start`/`end` or `window_days`, `exercise_id?` | `vbt_performance.analyse` | Per-set rows summarised; every abstention reason returned. Sparse by nature. |
| `get_programme_block_summary` | `as_of?`, `block_weeks` 4/6/8 | `settings_profile`, `deload`, `regime_change`, `breaks`, `attendance` | Derived window; no stored block (DEC-PROGRAMME-01) or calendar (DEC-W7-01). |
| `compare_training_periods` | `period_a`, `period_b`, `metric`, `exercise_id?` | attendance / adherence / volume / strength trend | Metric decides the owner; delta is arithmetic between the two outputs. |

Resources: `strength://athlete/profile` (taken), `strength://programme/current` (settings,
budget, deload, regime count, active breaks) and `strength://overview/current` (the four-week
overview fact set projected as a resource envelope). All three validate against the same envelope
and go through the same audit, timeout and size guards as a tool.

**Argument spelling.** MCP schemas use `start`/`end` for date bounds because `from` is a
Python keyword and the SDK cannot map an alias back to a parameter. The capability API keeps
`from`/`to`. The strict argument middleware rejects the other spelling, so a caller is never
silently ignored.

**Privacy.** Readiness is an explicit `health` class and returns only the fields named by the
caller. Session notes, symptoms, form ratings, injury constraints and body measurements are excluded
from every capability; where a count of withheld items is reported (profile constraints), it is
deliberate and visible.

**Evidence.** No INT-2 owner emits evidence items for these aggregates, so `evidence` is empty and
`coverage`, `n`, `gate` and `limitations` carry the caveats. `get_session_details` remains
the path that returns real evidence, from the completed-workout report.

**Development-machine timings** (synthetic 131 sessions / 781 sets / 260 readiness days, macOS
arm64, read-only connection, median of 3): progression 120 ms, readiness score series over 108
observed days 169 ms, programme block 91 ms, attendance comparison 36 ms. Adherence and VBT were
`no_data` in that dataset and are not quoted. These are a shape, not an SLO: the deployment host
measured roughly 14x the Mac on the overview benchmark, so the readiness score series is the
capability to watch there. No cache was added (ADR-INT-010) and the transport remains gated on that
host until the addendum is decided.

## 22. INT-3 — weekly review and the iOS read surface (closed 2026-11-15)

`get_weekly_review` is the tenth read-only capability. It composes the Monday-Sunday sections in
the plan §8.2 from their owners and adds no calculation beyond presentation labels:

| Section | Owner |
|---|---|
| activity | `attendance.summary` |
| adherence | `adherence_analytics.analytics` |
| sessions | `history.list_sessions` |
| progression | `strength_trend.observations` + `summarize` over 84 days for main lifts, ordered by recency then evidence; at most eight, with omissions counted |
| volume | `volume.compute` over the configured rolling window, with declared-break weeks excluded and reported in coverage |
| readiness | `queries.readiness_series` + `readiness_score.compute` (coverage and direction only; the direction is the sign of the canonical composite change, never a category average or an invented threshold) |
| programme | `deload.decision`, `regime_change.detect`, `breaks.active_on`; the top two regime findings keep lift, drop and substitutes, and the deload label is the policy state on the Sunday |
| observations | `observations.analyse(..., persist=False)`, at most two |

An empty week is `no_data` with the expected inputs listed, never zeros. An imported-only week keeps
`status: ok` and reports `imported_sessions_only` and `adherence_unavailable` in `quality_flags`.

**Volume.** The section asks the engine for its configured window (four weeks), excluding declared
break weeks, so the landmarks and coverage are the engine's own. It is not a single-week frame
labelled as a window.

**REST.** `GET /api/ios/v1/intelligence/weekly-review?week_end=YYYY-MM-DD` returns the envelope
unchanged, under the existing device bearer auth. The INT-4 read surface adds `overview`,
`exercises/{id}/progression`, `readiness` and `session-details` on the same pattern; the paired app
may name raw readiness fields, while the MCP dispatch keeps its separate gate. Validation failures are 400, an unknown resource
404, a disabled capability 503; the route never returns a partial or re-shaped payload.
`bootstrap.capabilities` gains `intelligence_read`.

**Tests.** `tests/test_intelligence_weekly.py`: golden fixture
(`tests/fixtures/intelligence/weekly_review.ok.json`), Monday/Sunday boundary, default week, empty
week, imported-only quality flags, observation opt-out, read-only counts, MCP/service parity, the
canonical-score direction (category mean diverging from the composite, no magnitude threshold), and
the live route (200, 401, 400, capability advertisement).

**iOS (2026-11-15).** `StrengthCore/Intelligence/IntelligenceEnvelope.swift` decodes the envelope
with unknown-field tolerance and fails on a missing required field;
`IOSAPIClient.weeklyReview(session:weekEnd:)` calls the route; `WeeklyReviewView` renders the
sections, coverage and limitations with no client-side calculation, and Progress links to it.
Tests decode the fixture, assert the missing-field failure and the date-only Week navigation.

**Performance (2026-11-15).** Real MCP Streamable HTTP on the ODROID against a copied production
database (378 sessions, 8,003 sets), core family verified ready, 30 measured requests and 5
warm-ups: **median 560.7 ms, p95 571.3 ms**. That replaces the provisional 113 ms Mac measurement
and classifies the capability as **slow** under the T-1 fast threshold (500 ms); it is well inside
the slow/very_slow 7 s budget. The single source is `strength_coach/intelligence/latency.py`;
the tool description is generated from it.

**Closed 2026-11-15.** Acceptance evidence: the completed week renders from the golden fixture;
an empty week is `no_data` with expected inputs; an imported-only week reports `imported_sessions_only`
and `adherence_unavailable`; the screen works with no model and no route beyond the existing REST
call; `DEC-AFC-03` holds (no client-side training arithmetic). Any narrative or model call remains
INT-4/INT-5, and the five-capability native provider surface is INT-4.

## 23. Read-only boundary, outbound data and partial weeks (2026-11-15)

**Read-only enforcement is at the database, not by convention.** MCP opens SQLite with
`mode=ro` plus `PRAGMA query_only`; the REST weekly-review entrypoint opens its own read-only
connection from the database path and cannot be handed a writable handle. The capability service's
deferred `BEGIN` and rollback remain defence in depth, not the guarantee. A test attempts `INSERT`
and `DELETE` on the read-only connection and asserts `OperationalError`, and the REST test
asserts the session count is unchanged after a call.

**Outbound data matrix.** What a capability may put in an envelope:

| Capability | Leaves the server | Never leaves |
|---|---|---|
| `get_training_overview` | training totals, ratios, volume, readiness *coverage* | readiness values, notes, symptoms |
| `get_session_details` | sets, adherence, VBT, effort, quality flags | notes, form ratings, symptoms |
| `get_exercise_progression` | e1RM observations and summary | — (training only) |
| `get_readiness_history` | readiness *score* series and coverage | raw readiness fields over MCP |
| `get_adherence_analysis` | aggregated set completion | free text |
| `get_prescription` | persisted plan, modifiers, rule refs | — (training only) |
| `get_vbt_analysis` | cohort and drift aggregates | per-rep raw data outside the summary |
| `get_programme_block_summary` | settings, budget, deload policy, findings | injury constraints, notes |
| `compare_training_periods` | two owner-produced sides and their delta | — (training only) |
| `get_weekly_review` | sections, readiness coverage and direction | readiness values, notes, symptoms |

The raw-readiness restriction is enforced in the MCP tool handler before the capability runs; the
config switch `allow_sensitive_readiness` (default false) is the only escape hatch, for a trusted
host. Local CLIs and the web UI keep the full field set. ADR-INT-012 proposes per-token scopes as
the cleaner long-term model.

**Partial weeks.** The weekly review reports `coverage.week_complete` / `week_partial`; a week
containing today is partial and adds a `missing` note saying the sections cover completed work so
far. The default request still selects the most recently completed Monday-Sunday week. Boundary
tests cover current partial, last completed, empty, and Monday/Sunday boundaries.

## 24. INT-4 — on-device narrative (first slice, 2026-11-15)

**Delivered.** A default-off Intelligence setting with the on-device consent copy; an availability
check with the three model-unavailable reasons; three narrative detail presets; a compact facts
projection built from the envelope (no evidence arrays or provenance); a Foundation Models
`@Generable` narrative with a fixed acceptance prompt; a grounding validator that rejects any
number (digit or common number word) not present in the facts and enforces the detail limits; a
deterministic fallback that leaves the review unchanged when the model is unavailable, refuses,
overflows the context or produces ungrounded text; and an explicit “Explain this week” / “Explain
the last four weeks” action on the weekly review and Progress.

**Boundary.** The model runs on the iPhone. No network call is made from the narrative path, no
transcript is persisted, and the readiness values the app already receives may be included in the
local projection. The MCP readiness gate is a separate deployment decision and is not changed here.
`DEC-AFC-03` still holds: the client formats server facts; it does not compute them.

**Tools and budget.** The five Foundation Models `Tool` adapters from contract §10 are implemented over
`IntelligenceCapabilityProviding` and tested, but they are **not registered in the session yet**: the
tool schemas consume most of the model's 8,192-token window and caused a real overflow on the device
at the Detailed preset. The session uses the facts already loaded for the screen. `NarrativeBudget`
estimates tokens at four characters per token and trims observations, missing entries and limitations
first, then trailing facts; the first attempt uses 1,200 tokens and a context overflow retries at 600
before falling back. Conditional tool registration with a measured budget is a follow-up.

**Tests.** `StrengthAppTests/IntelligenceNarrativeTests.swift`: projection contents (facts, gates,
no evidence ids), grounded acceptance, invented-number rejection (including number words), an
injection fixture where instruction-like text cannot smuggle an ungrounded number, overlong
rejection, detail presets, the overview projection, the five-tool surface, a tool call, the budget
trim/fallback, availability messages and the panel state transitions. The model itself is not
unit-tested.

**Device acceptance.** The owner confirmed the narrative rendered on 2026-11-15, then found two
issues on the Detailed preset: a context overflow caused by registering the five tool schemas, and an
over-strict grounding check that rejected percentages, thousands separators and the digit in
`e1RM`. Both are fixed (tools are not registered; the validator uses a structured allow-list with
percent/thousands variants and a digit-boundary regex, and the message names the offending number).
The device run passed. No UI test is required by owner decision; conditional tool registration
remains a tuning item.

## 25. INT-4b — on-device training chat (delivered 2026-11-15)

**Delivered.** A dedicated Chat screen from Progress, behind a separate default-off *Chat with your
training* consent toggle. Suggested prompts, non-streaming answers, a sources line naming the
tools used, and a session-only transcript cleared when the screen is left. The five capability
tools are registered for chat; a context overflow retries with three tools before failing.

**Grounding.** `ChatToolbox` records every envelope a tool returns; after each answer the digits
are checked against the structured allow-list built from those envelopes. An ungrounded digit
triggers one corrective retry; if it survives, the answer is shown with a visible "Unverified
numbers" warning rather than blocked. Number words are treated as prose, not claims. Conversation
history is capped at 2,400 characters and answers at 2,500. Session details resolve
the most recently completed session when the model has no workout id.

**Tests.** `StrengthAppTests/TrainingChatTests.swift`: send appends question and reply with sources,
an unavailable model does not send, failures are shown and reset clears, the prompt keeps only
recent turns, and the grounding guard rejects ungrounded numbers and overlong answers (6/6). No UI
test is required.

**Numeric facts.** The chat allow-list includes numbers from numeric-like string facts
(`"5.3 kg"`, `"80%"`) and accepts decimal variants such as `5.30` and signed progression values in
either direction (`-5.3` and `5.3`, including a typographic minus); instruction-like strings are
not parsed, so they cannot widen the set. A number the model computes itself triggers the retry and then the warning. A time window echoed from the question
("last 3 months") grounds only when the answer itself uses it as a time window, so it cannot
license "3 sessions".

**Tool errors.** A tool never throws a raw error into the conversation. Failures are classified as
not_found, invalid_identifier, unauthorized, unavailable, server or unknown, recorded in a
`ToolFailureLog`, and mapped to a short message: progression examples appear only for
not_found/invalid_identifier, while transport, server and auth failures say so plainly. The prompt
tells the model to ask for clarification rather than repeat a tool error.

**Session identity.** Session details resolve the most recently completed session only when no id is
supplied. An explicit id must resolve to that exact workout; a failed lookup is surfaced and is
never silently replaced by another session.

**Status.** Complete (2026-11-15). The manual device matrix passed: weekly review, overview,
progression, session details without an id, readiness, refusal of plan/medical prompts, and
transcript clearing. No UI test by owner decision. The single-shot explanation path is unchanged.

## 26. INT-4d — DeepSeek chat via API key (delivered 2026-11-15)

**Delivered.** A Chat-only model choice: On-device (default) or DeepSeek. When DeepSeek is selected,
the iPhone calls `https://api.deepseek.com` directly with `deepseek-chat` and the OpenAI-compatible
`/chat/completions` API. The adapter runs a tool loop over the same five read-only capabilities
(maximum four rounds), keeps the sources line and the soft number verification. Weekly and overview
explanations remain on-device.

**Key handling.** The key is entered in Settings, stored in the iOS Keychain with
`AfterFirstUnlockThisDeviceOnly`, and never written to UserDefaults, logs or the repository. Save,
Test (a `GET /models` validation) and Remove are available. A missing key makes the DeepSeek chat
unavailable with a clear message; there is no silent fallback.

**Errors.** 401/403 invalid key, 429 rate limit, 5xx server, transport failure and malformed JSON
have distinct short messages. Tool failures reuse the same classification and messages as the
on-device tools.

**Tests.** `DeepSeekChatTests`: bearer header and request path, tool-call parsing, tool round-trip
then grounded answer, ungrounded retry then warning, missing key, 401 and 429, malformed JSON. The
chat-related suite is 38 tests, all passing.

**Status.** Complete (2026-11-15). The owner confirmed DeepSeek chat on the iPhone with a real key.
A real 429 and a live four-round cap were not exercised; the cap and the error mappings are covered
by unit tests.

## 27. INT-4e prerequisite — plan-data REST routes (2026-11-15)

Three additive iOS intelligence routes expose the plan capabilities that were MCP-only:

- `GET /api/ios/v1/intelligence/prescription` — `prescription_id` or `for_date` (at most one),
  optional `include_provenance`; no identifier is the current persisted prescription.
- `GET /api/ios/v1/intelligence/programme-summary` — `as_of`, `block_weeks` (4, 6 or 8).
- `GET /api/ios/v1/intelligence/adherence` — `as_of`, `weeks`, or `from`/`to`; `group_by`,
  `exercise_id`, `session_type`.

The adapters open SQLite read-only and return the unchanged envelope; unknown query parameters
are 400. Tests cover all three routes and the unknown-query rejection (12 route tests).

## 28. INT-4e — plan-aware chat and suggestions (delivered 2026-11-15)

**Delivered.** A default-off plan-data toggle in Chat adds three read-only tools — prescription
(date, prescription id, or current), programme summary and adherence — to on-device and DeepSeek
chat. The backend exposes them through the three additive routes documented in section 27, now
deployed to the ODROID.

**Suggestions.** Both providers return a structured answer plus a separate suggestions list; the
UI renders “Suggestion — not applied. Not medical advice.” Suggestions may include numbers and
medical considerations, are exempt from data grounding, and are never applied. Factual answers keep
the existing soft verification.

**Dates.** The prescription tool resolves today and yesterday on the phone before calling the route,
and accepts an ISO date or a prescription id; this avoids treating a relative word as an id.

**Tool use.** A plan question on either provider does **not** call a plan tool: the app fetches the
matching compact facts first and, only on success or partial success, injects them into the prompt. This
avoids the context overflow, the endless required-tool loop and the model's own date arithmetic.
Prescription answers use a 900-token output budget and may exceed 150 words to list every item.
A context overflow retries with empty history. The prompt carries a "Today: YYYY-MM-DD" line so
"yesterday" is resolved against today, not against the latest prescription. The Chat header shows
whether plan data is on.

**Failure handling.** Plan retrieval returns a typed result: success, partial or failure. If every
requested capability fails, generation stops with a deterministic auth/transport/not-found message;
no raw error text is injected as facts. Partial results carry an explicit “unavailable sections”
label and the model is told not to make claims about them.

**Projections and unknowns.** Plan projections include the envelope status, missing reasons and
limitations. A no-data prescription says status=no_data and the missing reason instead of
date=unknown; absent adherence numbers and attendance percentages render as n/a, never zero; a
truncated prescription is labelled with the returned/total item count.

**Plan card and raw data.** A prescription answer carries a deterministic card built from the
fetched envelope: the exact date, session type and every item (exercise, sets × reps, load, RIR).
The card is not model output, so it cannot be abbreviated or dated wrongly. A “Show raw data”
disclosure still exposes the exact facts used.

**Projections.** Plan tools use compact, capability-specific projections instead of the generic
envelope projection. The generic 6,000-character projection truncated a 7.9 KB prescription to its
first item and a 42 KB adherence payload to a fragment; the compact forms keep every prescription
item (exercise, sets, reps, load, RIR, rest) and adherence totals, coverage, 12 periods and top
exercises, and a programme summary.

**Capacity.** The physical-device probe reported 8,192 tokens, tool calling and guided generation;
eight tools with four history messages and 60 fact lines passed.

**Tests.** 54 chat-related tests pass, including typed plan failures, no-data projections, natural-
language plan intent, plan-fact injection, the plan card, raw outputs and suggestion carrying. The three backend routes and unknown-query rejection are covered (12 tests).

**Status.** Complete (2026-11-15). The owner confirmed both providers on the iPhone. The deterministic prescription card now shows the full list and exact date, so model prose
abbreviation or a confused date no longer hides the prescription. Optional follow-up: shorten the
model prose when a card is present.
