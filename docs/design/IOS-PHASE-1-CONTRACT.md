# iOS Phase 1 — Native Foundation and Read-Only Views: implementation contract

**Status:** approved 2026-11-07; **implemented and accepted 2026-11-07** (iPhone 18 Pro
simulator plus owner-confirmed physical iPhone). This document remains the authoritative Phase 1
interface; the completion record is in §13. Phase 2 is not started.

**Scope:** fixes the exact server surface, client surface, tests and acceptance for Phase 1 of
[`IOS-CLIENT-PLAN.md`](../IOS-CLIENT-PLAN.md). The plan remains the authority for the phase
boundary; this document exists so the server repository and the separate `StrengthApp` repository
can be built against one written interface.

## 1. Phase 1 in one paragraph

A paired iPhone can fetch a small, authenticated, read-only view of the owner's server: today's
local date, the existing readiness payload and score, the active workout (or none), recent history
and the existing progress summaries. Pairing is a one-time, short-lived code printed by the local
CLI and exchanged for a per-device bearer token. There are no writes, no prescription requests, no
HealthKit and no offline queue in this phase.

## 2. Repositories and build order

- Server (this repository): migration, CLI, routes, tests. Commit to `iOS-app`; no CI runs there
  (CI triggers only on `main` push/pull request), so the local default suite and docs tests are
  the gate. Merge to `main` is separate.
- Client (`StrengthApp` repository): pairing and read screens. Work on `main`.
- Order: server contract and tests first, then the client against the running local server. A
  change that crosses the boundary lands server-first; there is no atomic cross-repository commit.

## 3. Network and credential model

- Plain HTTP on the owner's trusted home LAN. No TLS, no proxy, no certificate work. LAN traffic,
  including the bearer token and readiness data, is unencrypted; the deployment assumes a trusted
  network with no public exposure.
- The API is private to the LAN: no port-forwarding, no remote access. The server may bind a LAN
  address for the phone; the local development server binds `127.0.0.1` and the iOS Simulator
  reaches it there.
- One credential per device, exchanged once from a one-time pairing code, stored in the iOS
  Keychain, stored server-side only as a hash, and revocable from the CLI. No accounts, no
  passwords, no sessions, no cookies.
- The client talks only to the configured base URL. No analytics, telemetry, crash reporting or
  third-party endpoints.

## 4. Server data model — migration `0052_ios_device.sql`

Two additive tables. Existing tables, routes and append-only records are untouched.

```text
ios_device
  device_id    TEXT PRIMARY KEY          -- uuid4 hex
  label        TEXT NOT NULL
  token_hash   TEXT NOT NULL UNIQUE      -- hex SHA-256 of the bearer token
  created_at   TEXT NOT NULL             -- UTC ISO-8601
  last_seen_at TEXT                      -- UTC ISO-8601, nullable
  revoked_at   TEXT                      -- UTC ISO-8601, nullable

ios_pairing_code
  code_hash    TEXT PRIMARY KEY          -- hex SHA-256 of the 8-digit code
  created_at   TEXT NOT NULL             -- UTC ISO-8601
  expires_at   TEXT NOT NULL             -- UTC ISO-8601
  attempts     INTEGER NOT NULL DEFAULT 0
  used_at      TEXT                      -- UTC ISO-8601, nullable
```

- The plaintext code and token are never stored. The code is printed once by the CLI; the token is
  returned once by the pairing exchange.
- Accepted risk: an 8-digit code hash is brute-forceable if the local database leaks. The
  mitigation is the 5-minute TTL, the five-attempt limit, single use, and the database being
  local-only. Do not store the plaintext code.
- Expired and used code rows may be pruned opportunistically; no retention promise is made.

## 5. Server endpoints

Namespace: `/api/ios/v1/`. Only the endpoints below exist in Phase 1. Existing unversioned routes
keep their current behaviour and remain unauthenticated.

### 5.1 `POST /api/ios/v1/pair` — no authentication

Request (JSON, as the existing body reader requires):

```json
{"code": "12345678", "label": "iPhone"}
```

- `code`: 8 digits; spaces and hyphens are ignored before validation.
- `label`: optional; defaults to `iPhone`; trimmed, 1–40 characters.

Validation: the code row exists, `used_at` is null, `expires_at` is in the future, and
`attempts < 5`. A failed attempt increments `attempts`. Success marks `used_at`, creates the
device and returns the token. Codes are minted only by the CLI; there is no HTTP issuance.

Response `200`:

```json
{
  "api_version": "1",
  "device": {"device_id": "…", "label": "iPhone"},
  "token": "…",
  "server_date": "2026-11-07",
  "server_time": "2026-11-07T16:00:00+00:00",
  "utc_offset_minutes": 0,
  "server_timezone": "GMT"
}
```

- `token` is shown once; the client must store it in Keychain immediately.
- `server_date`/`server_time` come from the server's local clock (Europe/London in the owner's
  deployment); the client must not infer the training date from a UTC slice.
- Error codes: `400` malformed body/code format, `401` wrong code, `410` expired or already
  used, `429` attempts exhausted. All use the existing envelope `{"error": "…"}` with
  `"fields": {…}` where a field is at fault.

### 5.2 Authentication for every other iOS route

- `Authorization: Bearer <token>`.
- Missing, malformed or unknown token → `401 {"error": "authentication required"}`.
- Known but revoked device → `403 {"error": "device revoked"}`.
- The token is hashed and looked up; it is never compared or logged in plaintext.
- On success, update `last_seen_at` at most once per 60 seconds to keep the local database quiet.
- Authentication runs before dispatch, so an unknown path under `/api/ios/v1/` also returns
  `401` when unauthenticated (no route oracle) and `404` when authenticated.

### 5.3 Read endpoints

All are `GET`, authenticated, and return existing service payloads unchanged. No new calculation
exists in the facade; Python services remain authoritative.

| Route | Payload |
|---|---|
| `GET /api/ios/v1/bootstrap` | `{api_version, server_date, server_time, utc_offset_minutes, server_timezone, capabilities}`; capabilities are `{readiness: true, prescription: false, workout_write: false, healthkit: false, offline: false}` for Phase 1 |
| `GET /api/ios/v1/today` | `{date, readiness, readiness_score, active_workout}` — `readiness` is the existing readiness payload, `readiness_score` its score object, `active_workout` the active workout or `null` |
| `GET /api/ios/v1/history?limit=&offset=&start=&end=` | Exactly `history.list_sessions`: `{total, limit, offset, sessions}`; default `limit=50`, `offset=0`; limit 1–100 |
| `GET /api/ios/v1/progress?weeks=&date=` | Exactly `progress_feature.dashboard`; `weeks` 1–52, default 8 |

- No write routes in Phase 1. No prescription request, no readiness write, no set logging.
- `today` reuses the existing readiness payload (which includes settings and presets); the client
  decodes the subset it shows. Reusing the payload avoids a second contract to maintain.
- Invalid `limit`, `offset`, `weeks` or `date` → `400` with `fields`.
- `GET /progress` is **server-only in Phase 1**. It is part of the facade and is covered by the
  server contract tests, but the Phase 1 client deliberately has no Progress screen; a Progress
  UI is Phase 2 work and must not be added under this contract.

### 5.4 Error envelope

The existing shape is kept: `{"error": "<message>"}` plus optional `"fields": {"<field>": "<why>"}`.

| Status | Use |
|---|---|
| 400 | validation, bad query parameter, bad JSON fields |
| 401 | missing/unknown token, wrong pairing code |
| 403 | revoked device |
| 404 | unknown authenticated iOS route |
| 410 | expired or used pairing code |
| 411/413/415 | body handling, unchanged from the existing server |
| 429 | pairing attempts exhausted |
| 500 | unexpected; generic body only, details to the server log |

### 5.5 Logging

- The server logs the request line and status only; headers and bodies are not logged.
- The pairing code and bearer token must never appear in the application log, the in-memory Logs
  page, exceptions or error bodies. Add a test that asserts this.
- Do not put the token or code in a query string; it would be logged with the request line.

## 6. CLI (server repository)

Add an `ios` command group; the global `--db` selects the database, as everywhere else. The CLI
is local, so it needs no HTTP authentication.

- `strength-coach ios pair [--label LABEL] [--ttl 300]` — mint one code, print the code and
  expiry; only the hash is written. Refuse `--ttl` outside 60–3600 seconds.
- `strength-coach ios devices` — list device id, label, created, last seen, revoked.
- `strength-coach ios revoke <device_id>` — set `revoked_at`; idempotent; unknown id exits 2.

Output is plain text; no secrets beyond the freshly printed code.

## 7. Swift client (`StrengthApp` repository, `main`)

### 7.1 Screens

- **Pairing:** server base URL, pairing code (spaces ignored), optional device label, Pair button,
  inline error, progress state. Prefill `http://127.0.0.1:8000` in DEBUG only; Release starts
  empty with a placeholder so no wrong default reaches the device.
- **Today:** server date, readiness status and score, readiness basis/overrides as returned, active
  workout summary or "no active workout"; pull to refresh.
- **History:** paginated sessions from `/history`, load more, empty and error states.
- **Settings:** server URL, device id and label, "Forget this device" (deletes the local token and
  returns to pairing; it does not revoke server-side in Phase 1), app version, re-pair instructions.

No **Progress** screen in Phase 1: `GET /progress` is server-only and tested server-side. A
Progress UI is deferred to Phase 2 and must not be added under this contract.

No prescription, workout, readiness entry, review, HealthKit or offline UI in Phase 1.

### 7.2 Storage

- Keychain: `kSecClassGenericPassword`, service `com.georgesdibpersonalteam.StrengthApp`,
  account `api-token`, `kSecAttrAccessibleWhenUnlockedThisDeviceOnly`. Delete on Forget and on
  re-pair.
- Server URL in UserDefaults (not secret). The token never goes to UserDefaults, files, logs or
  crash reports.
- Uninstall/reinstall may keep the Keychain item; pairing again replaces it.

### 7.3 Networking

- One `IOSAPIClient`: base URL validation (http/https, host required), `Authorization: Bearer`,
  `Content-Type: application/json` on POST, 10-second request timeout, strict decoding.
- `401`/`403` clear the paired state and show pairing; other 4xx show the server message; 5xx
  show a generic failure.
- GET retries only for transient network errors, bounded; no mutation retries (there are none).
- No cookie storage, no redirects outside the paired origin (scheme, host and port), no background
  transfers. The redirect guard compares scheme, host and effective port, so a cross-port or
  scheme-changing redirect cannot receive the bearer token.

### 7.4 Info.plist and platform behaviour

- `NSLocalNetworkUsageDescription` explaining that the app talks to the owner's local server.
- ATS: plain HTTP to a user-entered LAN host. Prefer `NSAllowsLocalNetworking`; confirm at
  implementation whether the chosen host form (127.0.0.1, `.local` or a LAN IP) needs a narrower
  exception. Do not use `NSAllowsArbitraryLoads` unless nothing narrower works, and record it if
  it is ever needed.
- Local-network permission is requested on first connection; the app must explain it and handle
  denial without crashing.

### 7.5 Build and test targets

- Simulator: iPhone 18 Pro on iOS 27.2. The iPhone 16 Pro device type exists in Xcode 27.2, but no
  simulator is created for it; do not create one.
- Device acceptance: the owner's iPhone 16 Pro (iOS 27.2), personal team, 7-day expiry.
- Builds from this workspace use `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer`;
  simulator builds pass `CODE_SIGNING_ALLOWED=NO`.

## 8. Tests

### 8.1 Python — new `tests/test_ios_api.py`, using the existing live-server fixture

- Pairing: valid code returns a token and creates exactly one device; the token authenticates.
- Pairing rejection: wrong code, malformed code, expired code, already-used code, attempts
  exhausted; each returns the documented status; no device is created.
- Attempts increment on failure; a successful pair marks the code used and it cannot be reused.
- Auth: missing header → 401; unknown token → 401; revoked device → 403; authenticated unknown
  iOS path → 404.
- `bootstrap`: API version, server-local date, UTC offset and capabilities.
- `today`: date matches the server-local date; readiness/score match the existing service; active
  workout is null without a session.
- `history`: default 50/0, paging bounds, invalid limit/offset → 400, payload identical to
  `history.list_sessions`.
- `progress`: weeks 1–52, invalid weeks → 400, payload identical to
  `progress_feature.dashboard`.
- Secrets: neither the pairing code nor the token appears in captured logs or error bodies.
- Regression: existing `/api/*` routes behave exactly as before; existing tests unchanged.
- CLI: `ios pair` prints one code and stores no plaintext; `ios devices`; `ios revoke` sets
  the timestamp and is idempotent.

### 8.2 Swift

- Keychain wrapper save/load/delete unit test.
- API client decoding from fixture JSON, including the 401 → unpaired mapping.
- One optional UI smoke test; not a release gate.

### 8.3 Existing gates

The default `pytest` suite, `tests/test_docs_manifest.py`, `tests/test_docs_consistency.py` and
`ruff check .` must pass before handoff; CI runs only when this branch merges to `main`.

## 9. Acceptance criteria

1. `strength-coach ios pair` prints a code; `POST /api/ios/v1/pair` exchanges it once for a
   token.
2. The token authorises `bootstrap`, `today`, `history` and `progress`; no token is required
   by any existing route and none breaks.
3. An unpaired or revoked device is rejected (401/403) and the app returns to pairing.
4. Expired, used and over-attempted codes are rejected; a used code cannot create a second device.
5. On the iPhone 18 Pro simulator, the app pairs against the locally-run server on `127.0.0.1`,
   shows today's date/readiness and a history page, and keeps the token across relaunch.
6. "Forget this device" clears the Keychain token; re-pairing works.
7. No token or code appears in logs, error bodies or the Logs page.
8. The full default suite, docs tests and `ruff` pass; existing web/CLI behaviour is unchanged.

## 10. Rollback

Drop `ios_device` and `ios_pairing_code`, remove the `/api/ios/v1/` routes and the `ios` CLI
group. No existing table, route, prescription, workout or readiness record is changed. The client
side is a separate repository and can be discarded or its pairing screen disabled independently.

## 11. Decisions

Taken (owner-approved): 8-digit code, 300-second TTL, five attempts, single use; 32-byte token,
hashed at rest, valid until revoked; token returned once; plain HTTP on the trusted LAN; read
payloads reused verbatim; CLI-only revocation; no TLS, no remote access.

Settled at approval (2026-11-07):

1. Error mapping stays as in §5.1/§5.4: `401` wrong code, `410` expired/used, `429` attempts
   exhausted.
2. `bootstrap` field names stay as drafted; no IANA zone name in Phase 1.
3. History defaults to 50 per page; `today` returns the full readiness payload rather than a
   trimmed subset.
4. Device label defaults to `iPhone`; 1–40 characters.
5. "Forget this device" is local-only in Phase 1; server revocation stays CLI-only.
6. `last_seen_at` updates at most once per 60 seconds.

## 12. References

- [`IOS-CLIENT-PLAN.md`](../IOS-CLIENT-PLAN.md) — phase boundary, invariants, rollback gates.
- [`API.md`](../API.md) — existing routes, body limits, error behaviour, date semantics.
- [`READINESS.md`](../READINESS.md), [`READINESS-SCORE.md`](../READINESS-SCORE.md) — readiness
  payload, score status and override rules.
- [`DATA-MODEL.md`](../DATA-MODEL.md) — append-only records and schema conventions.
- [`PRIVACY.md`](../PRIVACY.md) — no personal data in the public repository.

## 13. Completion record (2026-11-07)

Phase 1 is complete. All §9 acceptance criteria were exercised; the live UI test passed on the
iPhone 18 Pro simulator against a temporary SQLite database, and the owner then confirmed the device
checklist on the physical iPhone (the record is `StrengthApp/DEVICE-ACCEPTANCE.md`).

- **Server:** migration `0052_ios_device`, the `strength-coach ios pair/devices/revoke` CLI,
  the authenticated read facade and `tests/test_ios_api.py`. The default suite is 1604 tests and
  `ruff` passes. Existing unversioned routes and stored training data are unchanged.
- **Client:** pairing, Today, History and Settings/Forget in the separate `StrengthApp`
  repository, Keychain token storage, 29 unit tests and the optional live UI smoke test.
- **Secrets:** neither the code nor the token is stored in plaintext, logged, or returned in an
  error body; the token is Keychain-only.
- **Rollback:** remains as §10 — additive tables, routes and CLI only; the client can be forgotten
  or discarded independently.
- **Progress:** `GET /api/ios/v1/progress` is server-only in Phase 1 and covered by the server
  tests; the client has no Progress screen. A Progress screen is deferred to Phase 2.
- **Post-acceptance remediation (2026-11-07):** the redirect guard now rejects any redirect whose
  scheme, host or effective port differs from the paired origin. `RedirectPolicyTests` covers
  same-origin, cross-port, scheme-changing, different-host, userinfo and delegate-rejection cases.
  The device pass preceded this transport-internal hardening; the normal LAN path is unchanged.
- **Residual limits:** plain HTTP on the trusted home LAN only; no writes, HealthKit, offline
  capture, review or prescription UI in Phase 1; personal-team signing expires after 7 days.
- **Next:** Phase 2 is specified by the draft [`IOS-PHASE-2-CONTRACT.md`](IOS-PHASE-2-CONTRACT.md);
  it is not approved or started.
