# TRAINING INTELLIGENCE — BACKEND IMPLEMENTATION

**Status:** INT-1 foundation, INT-1b MCP transport, the audit remediation and the INT-2 capability
catalogue implemented 2026-11-14. Read-only, provider-neutral, independently runnable. The
baseline context package, evidence producers for the new aggregates, the weekly review (INT-3) and
the REST/iOS surface are not implemented.
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
| Baseline context package (shared compact context) | **not implemented — INT-3** |
| Evidence producers for the INT-2 aggregates | **deferred** — owners do not emit evidence items for these aggregates; `get_session_details` returns the real evidence |
| Weekly review package (INT-3) | **not implemented — INT-3** |
| REST route, iOS adapter, model providers | **not implemented — INT-3 onward** |

The plan's INT-1 originally bundled the MCP skeleton and two tools. The approved implementation
prompt narrowed INT-1 to the foundation and deferred the transport, so that scope moved to
**INT-1b**, delivered 2026-11-14 and recorded in the plan and roadmap. **INT-2** then delivered the
remaining read-only catalogue and its two resources on 2026-11-14. Everything marked INT-1b and
INT-2 above is implemented. What remains is the baseline context package, evidence producers for
the aggregate capabilities, the INT-3 weekly review and REST surface, and model integration; none
of those is implied by INT-2 and none is claimed here.

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
- **The systemd unit has not been deployed or validated on the target host.** The deployment guide
  is an installation plan until the acceptance steps are run there.

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
of which the ratio is 516 ms). **The request is still above the one-second transport gate, so the
MCP transport stays disabled on this host.**

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

These are hypotheses from profiling; no optimization or semantic change has been made. T-3 remains
in progress and requires parity tests and a fresh HTTP benchmark after any change.

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
at `/etc/strength-coach/intelligence.local.yaml`; it contains no secrets. The unit is independent
of `strength-coach-web.service` and binds to loopback by default.

Installation, service-user creation, token provisioning, start/stop, log inspection, revocation
semantics, tailnet exposure and troubleshooting are in
[INTELLIGENCE-DEPLOYMENT.md](INTELLIGENCE-DEPLOYMENT.md). The unit has **not** been deployed or
validated on the target host.

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
