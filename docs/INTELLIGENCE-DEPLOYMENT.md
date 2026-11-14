# TRAINING INTELLIGENCE — MCP DEPLOYMENT GUIDE

**Status:** written 2026-11-14 for the INT-1b service. The unit and this procedure have **not** been
deployed or validated on the target ODROID host. Treat them as an installation plan until the
acceptance steps at the end have actually been run there.

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

The default bind is loopback. To serve the owner's tailnet:

1. set `bind_host` to the tailnet address (never `0.0.0.0` on an untrusted network);
2. add the exact Host header clients use to `allowed_hosts`, for example `odroid.tailnet.ts.net:*`;
3. keep the bearer token mandatory — Tailscale is reachability, not authentication;
4. do not port-forward; the web UI and this endpoint are not public services.

Verify with a client on the tailnet, not from the open internet.

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

## 13. Remaining limitations

- Per-process rate and concurrency limits: run one worker. The SDK multiplexes requests, so this is
  sufficient for one athlete.
- The timeout cannot cancel CPU-bound work; it bounds the response only.
- No metrics endpoint; use the journal audit lines.
- No package for a distribution's package manager; install from the virtual environment.
- A stored IANA profile timezone is still ROADMAP §4.19 work; set `TZ` on the host.
- The service has not been deployed on the target host. Its synthetic baseline there measured
  **p50 3,101.9 ms / p95 3,169.4 ms at 377 sessions** (2026-11-14), above the ADR-INT-010
  one-second threshold, so **do not enable the transport on that host until the ADR addendum is
  decided**. The web UI and CLI are unaffected.
