# TRAINING INTELLIGENCE — MCP DEPLOYMENT GUIDE

**Status:** written 2026-11-14 for the INT-1b service; validated manually on the home host on
2026-11-15 (all ten tools over Streamable HTTP, `get_weekly_review` included). The **systemd unit
is not installed**: it targets `/opt/strength-training-app` and user `strength-intel`, while this
host runs from `/home/dsh/strength-training-app` as `dsh`. The service therefore runs as a manual
process and does not survive a reboot until §6 is completed with host-adapted paths.

Architecture, tool schemas and the performance baseline are in
[INTELLIGENCE-IMPLEMENTATION.md](INTELLIGENCE-IMPLEMENTATION.md). The canonical contract is the
portfolio [Training Intelligence contract](https://github.com/georgesdib/strength-app/blob/main/docs/contracts/TRAINING-INTELLIGENCE-CONTRACT.md).

## 1. What runs

One process, `strength-intelligence-mcp` (or `strength-coach intelligence serve`), serving the
MCP endpoint over Streamable HTTP. It reads the existing SQLite database through a @mode=ro@
connection, holds no writable state, serves no UI, and is independent of
`strength-coach-web.service`.

## 2. Prerequisites

- Python 3.11 or newer on the host.
- The backend checkout and virtual environment at `/opt/strength-training-app` with the optional
  extra installed:

      /opt/strength-training-app/.venv/bin/pip install ".[intelligence]"

- The trained database readable by the service user, for example
  `/var/lib/strength-coach/coach.db`. Do not copy it into a second writable location: point
  `--db` at the file the backend actually maintains (a consistent SQLite read is safe while the
  web UI and CLI write).
- A timezone set for the service. The authoritative training date is the **server-local calendar
  date**; an unset zone on a headless host is UTC and can shift a window by a day.

## 3. Service user and directories

    sudo useradd --system --home-dir /var/lib/strength-intel --shell /usr/sbin/nologin strength-intel
    sudo install -d -o strength-intel -g strength-intel -m 0700 /var/lib/strength-intel
    sudo install -d -o root -g strength-intel -m 0750 /etc/strength-coach

The service user needs:

| Path | Access | Why |
|---|---|---|
| `/opt/strength-training-app` | read/execute | code and virtual environment |
| `/etc/strength-coach/intelligence.v1.yaml` | read | switch, bounds, exposure |
| `/etc/strength-coach/intelligence.local.yaml` | read | hashed client tokens |
| database file | read | SQLite @mode=ro` |

It needs **no** write access anywhere. `ProtectSystem=strict` enforces that at the unit level, and
`PYTHONDONTWRITEBYTECODE=1` stops Python from trying to write `__pycache__` under `/opt`.

## 4. Configuration

Install `config/intelligence.v1.yaml` as `/etc/strength-coach/intelligence.v1.yaml` and edit:

- `enabled: true` (the server refuses to start otherwise);
- `bind_host`: keep `127.0.0.1` unless a private network is intended;
- `allowed_hosts`: the exact Host headers clients will send (a hostname or `address:*`);
- `tool_timeout_seconds` and `max_tool_result_bytes` for the runtime limits;
- `rate_limit_per_minute` and `max_concurrent_calls` (1-2 on a single-board host).

Do not put tokens in this file.

## 5. Token provisioning

Run as the service user's administrator from the repository environment, writing the token file
where the unit expects it:

    sudo -u strength-intel /opt/strength-training-app/.venv/bin/strength-coach \
      intelligence token create --label "Claude Desktop" \
      --tokens /etc/strength-coach/intelligence.local.yaml

The plaintext token is printed **once**. Store it in the client; it cannot be recovered. The file
holds SHA-256 digests only and is written mode 0600. List and manage clients with:

    ... intelligence token list   --tokens /etc/strength-coach/intelligence.local.yaml
    ... intelligence token rotate <client_id> --tokens ...
    ... intelligence token revoke <client_id> --tokens ...

## 6. Install, start, stop

    sudo install -m 0644 deploy/strength-intelligence-mcp.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now strength-intelligence-mcp.service
    systemctl status strength-intelligence-mcp.service
    sudo systemctl restart strength-intelligence-mcp.service
    sudo systemctl stop strength-intelligence-mcp.service

The process refuses to start (exit 2, visible in the journal) when the feature is disabled, the
database is missing, or no active client token exists.

## 7. Logs

    journalctl -u strength-intelligence-mcp.service -f
    journalctl -u strength-intelligence-mcp.service --since "1 hour ago"

Each invocation writes exactly one JSON audit line on the
`strength_coach.intelligence.audit` logger (schema in the implementation page). It contains
identity, timing, sizes and outcome only. Arguments, payloads, notes, health values and tokens are
never logged. The service's own capability line is at DEBUG and is not shown by the default
journal level.

## 8. Revocation and rotation semantics

- Tokens are re-read from the file on **every request**, so `revoke` takes effect on the next call
  with no restart: the old token returns 403.
- `rotate` replaces the digest in place; the previous token returns 401 immediately and the new
  token works without a restart.
- Writes are atomic (`os.replace`), so a reader sees either the old or the new complete file.
- If the file is malformed, every request is denied (401) and a warning is logged; the service does
  not fall back to stale credentials.
- A revoked client cannot be rotated; create a new client instead.

## 9. Private-network exposure

The default bind is loopback. To serve the owner's tailnet or LAN:

1. set `bind_host` to the specific tailnet or LAN address (never `0.0.0.0` on an untrusted
   network);
2. add the exact Host header clients use to `allowed_hosts`, for example
   `odroid.tailnet.ts.net:*` or `10.0.0.44:*`;
3. keep the bearer token mandatory — reachability is not authentication;
4. do not port-forward; the web UI and this endpoint are not public services.

The home host binds its LAN address this way (`bind_host: 10.0.0.44`,
`allowed_hosts` includes `10.0.0.44:*`). A request whose Host does not match is rejected with
**421** even when it carries a valid token, so DNS rebinding stays closed.

Verify with a client on the tailnet or LAN, not from the open internet.

## 10. Database read-only guarantee

The transport opens `file:...?mode=ro` and sets `PRAGMA query_only`. The capability service also
runs each call inside a deferred transaction that is rolled back. A write attempt fails at the
SQLite layer, and the HTTP integration test asserts the row counts are unchanged after tools and
resource reads. Point the unit at the live database; a separate copy would drift.

## 11. Hardening and limits

The unit sets `NoNewPrivileges`, `PrivateTmp`, `PrivateDevices`, `ProtectSystem=strict`,
`ProtectHome=read-only`, kernel/control-group protection, `LockPersonality`, `RestrictSUIDSGID`,
a restricted address-family list and `SystemCallArchitectures=native`. It runs as a dedicated
non-root user and contains no secrets.

Runtime limits: a 20-second per-call response deadline (configurable 1-300 s), a 1 MiB serialized
result cap (configurable 1 KiB-10 MiB), a per-client rate limit and a concurrency ceiling.

**Timeout caveat:** the deadline bounds the *response*, not the work. Python cannot cancel a
blocking SQLite read; the worker thread finishes its bounded query and its result is discarded.
The database is opened only for that call, so the leftover work is a read that ends.

## 12. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| exit 2, `intelligence is disabled` | set `enabled: true` |
| exit 2, `no active MCP client tokens` | create a token with the path the unit passes |
| 401 on every request | wrong token, wrong file path, or malformed token file (check the journal warning) |
| 403 | client revoked; create a new one |
| 421 `Invalid Host header` | add the client's Host value to `allowed_hosts` |
| 413 | request body over `max_request_body_bytes` |
| 429 | per-client rate or concurrency limit; wait for `Retry-After` or raise the limit |
| @tool_timeout` in a tool result | host is slower than the deadline; raise `tool_timeout_seconds` or reduce history pressure (see the baseline section) |
| @result_too_large` | raise `max_tool_result_bytes` or narrow the request |
| service stops after start | read the journal; most failures are the disabled switch, a missing database or permissions |

## 13. Benchmarking all capabilities and the HTTP transport

The original tool measured only `get_training_overview` through `IntelligenceService`. The
extended `tools/intelligence_benchmark.py` discovers every registered capability, builds valid
arguments from the benchmark database, and reports per-capability p50/p95/max/mean, success/error
counts and envelope status distribution.

**Direct mode** (default, synthetic data, read-only service path):

    python tools/intelligence_benchmark.py --sessions 200 --runs 30

Synthetic mode creates a disposable database and may build the derived core family before the
read-only run; the source tables are never mutated. `--no-analytics-build` measures the on-demand
path instead.

**HTTP mode** (actual MCP Streamable HTTP, official SDK client, bearer token from the environment):

    export STRENGTH_MCP_TOKEN=...
    python tools/intelligence_benchmark.py --mode both --url http://127.0.0.1:8765/mcp         --sessions 200 --runs 30 --output report.json

The script calls `tools/list`, then `tools/call` for each capability. Tokens are read only from
the named environment variable (`--token-env`, default `STRENGTH_MCP_TOKEN`) and never printed.
The report distinguishes direct execution, full client-observed HTTP execution, and
`mcp_overhead_p50_ms = http p50 - direct p50`. That difference contains network, protocol,
authentication and server middleware costs, not pure network latency; a non-positive value is
reported as no measurable overhead, not as a meaningful negative result.

**Existing database (read-only):**

    python tools/intelligence_benchmark.py --db /path/to/copied/coach.db --runs 30

The database is opened read-only; migrations, analytics builds and source mutations are not run.
The report records whether the core derived family is verified current. If it is not, the consumer
path is on-demand and the report says so; do not compare that run with a materialised one.

The report contains capability names, timings, error classes and configuration only. Session,
workout and prescription identifiers in arguments are redacted. Raw training values are never
included.

**Status (2026-11-14).** The extended benchmark and its tests are implemented. The HTTP mode was
run on the ODROID against a copied production database (377 sessions, 7,978 clean sets, 1,018
readiness days, 18.37 MB) with the core family verified ready, 30 measured iterations and 5
warm-ups per capability. Every call succeeded; p95 values:

| Capability | Direct p50 | HTTP p50 | HTTP p95 |
|---|---:|---:|---:|
| get_session_details | 5,083 ms | 5,916 ms | 6,201 ms |
| get_training_overview | 3,725 ms | 3,698 ms | 4,058 ms |
| get_programme_block_summary | 3,229 ms | 3,362 ms | 3,800 ms |
| get_readiness_history | 1,519 ms | 1,560 ms | 1,663 ms |
| compare_training_periods | 148 ms | 183 ms | 194 ms |
| get_adherence_analysis | 38 ms | 106 ms | 130 ms |
| get_exercise_progression | 23 ms | 66 ms | 67 ms |
| get_prescription | 1.2 ms | 37 ms | 40 ms |
| get_vbt_analysis | 18 ms | 62 ms | 63 ms |

Direct and HTTP were separate runs on the same copied database, so the difference is indicative
of transport overhead (roughly 35-800 ms, with run-to-run noise on the slow calls). Four
capabilities exceed the one-second threshold in both modes: overview, session details, programme
summary and readiness. ADR-INT-010 accepted a latency-aware budget rather than keeping the transport
disabled, so these figures are guidance and the 20 s tool timeout is the hard bound; T-3 remains the
optimisation track. The benchmark also exposed and fixed a tooling defect:
readiness and VBT HTTP calls must use the MCP tools' start/end inputs, not the capability payload's
from/to fields; without translation they measured fast validation errors.

## 14. Maintenance worker (C-1)

Derived analytics maintenance is a **one-shot systemd service plus a timer**, not a long-running
daemon:

- `deploy/strength-analytics-maintenance.service` runs
  `python -m strength_coach.cli --db data/coach.db analytics build` from the same checkout and
  virtual environment as the web service.
- `deploy/strength-analytics-maintenance.timer` runs it on boot + 5 minutes and every 15 minutes
  afterwards.
- The web unit has `ExecStartPost=-/bin/systemctl --no-block start
  strength-analytics-maintenance.service`, so a backend deployment that restarts the web service
  also triggers one reconciliation with the new code (the leading `-` means a missing maintenance
  unit cannot break the web service). If the service account is not permitted to start system
  units, that call is a no-op; the 15-minute timer performs the same reconciliation and is the
  authoritative mechanism.

**Why this updates automatically.** There is no separate long-lived worker process to upgrade. The
timer invokes the checkout's current code and venv, so a `git pull` plus web restart is sufficient;
the next timer tick or the `ExecStartPost` run uses the new code and dependencies. The worker and
web service share the deployment root and user, so a dependency update applies to both.

**Install / verify:**

    sudo install -m 0644 deploy/strength-analytics-maintenance.service /etc/systemd/system/
    sudo install -m 0644 deploy/strength-analytics-maintenance.timer /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now strength-analytics-maintenance.timer
    systemctl list-timers strength-analytics-maintenance.timer
    sudo systemctl start strength-analytics-maintenance.service
    journalctl -u strength-analytics-maintenance.service -n 50

The run prints the family state as JSON and exits non-zero unless the family is ready; a failure is
visible in the journal and in `GET /api/analytics/status`. Consumers continue on the on-demand
path while the family is not ready, so a failed run degrades latency, not correctness.

**Failure, rollback and recovery.** A failed run leaves the previous published family intact; it
never serves a partial build. Retry with `systemctl start strength-analytics-maintenance.service`.
To roll back, `systemctl disable --now strength-analytics-maintenance.timer` and remove the web
unit's `ExecStartPost` line; no data migration is required. The worker needs write access to the
database and must run as the same user as the web service, not as the read-only MCP service user.
The units are documented and tested here but have **not been deployed or validated on the target
ODROID host**.

## 15. Remaining limitations

- Per-process rate and concurrency limits: run one worker. The SDK multiplexes requests, so this is
  sufficient for one athlete.
- The timeout cannot cancel CPU-bound work; it bounds the response only.
- No metrics endpoint; use the journal audit lines.
- No package for a distribution's package manager; install from the virtual environment.
- A stored IANA profile timezone is still ROADMAP §4.19 work; set `TZ` on the host.
- The systemd unit has not been installed on the target host. The synthetic baseline there
  measured **p50 3,101.9 ms / p95 3,169.4 ms at 377 sessions** (2026-11-14), above the one-second
  threshold; ADR-INT-010 accepted the latency-aware budget and enabled the catalogue, so treat those
  numbers as guidance and T-3 as the optimisation track. The web UI and CLI are unaffected.
