-- Per-device iOS credentials and one-use pairing codes (Phase 1).
--
-- The iOS facade authenticates every request with a per-device bearer token. Only the
-- SHA-256 hex digest is stored, never the token or the pairing code: the code is printed
-- once by `strength-coach ios pair` and the token is returned once by POST /api/ios/v1/pair.
-- Both tables are additive; no existing training, readiness or prescription row changes.
--
-- Accepted risk: an 8-digit code digest is brute-forceable if this local database leaks.
-- The mitigation is the 5-minute TTL, the five-attempt limit, single use and the database
-- being local-only (StrengthApp/docs/IOS-CLIENT-PLAN.md §7). Do not store the plaintext code.

CREATE TABLE ios_device (
    device_id    TEXT PRIMARY KEY,          -- uuid4 hex
    label        TEXT NOT NULL,
    token_hash   TEXT NOT NULL UNIQUE,      -- hex SHA-256 of the bearer token
    created_at   TEXT NOT NULL,             -- UTC ISO-8601
    last_seen_at TEXT,                      -- UTC ISO-8601, nullable
    revoked_at   TEXT                       -- UTC ISO-8601, nullable
);

CREATE TABLE ios_pairing_code (
    code_hash  TEXT PRIMARY KEY,            -- hex SHA-256 of the 8-digit code
    created_at TEXT NOT NULL,               -- UTC ISO-8601
    expires_at TEXT NOT NULL,               -- UTC ISO-8601
    attempts   INTEGER NOT NULL DEFAULT 0,
    used_at    TEXT                         -- UTC ISO-8601, nullable
);
