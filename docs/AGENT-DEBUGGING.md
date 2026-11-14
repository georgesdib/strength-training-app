# Agent debugging — strength-training-app

Diagnostics and log rules. Read ../AGENTS.md and AGENT-WORKFLOWS.md first.

## 1. Token discipline

- Do not read ROADMAP.md, CHANGELOG.md, large docs, logs, exports, lockfiles, build
  artefacts or databases unless essential to the task.
- Prefer targeted search and small excerpts.
- Never paste full test/build/log output into context.
- On failure, return only failing test names, assertion messages and relevant tracebacks.
- Run the narrowest relevant test first.

## 2. Failure triage order

1. Reproduce with the smallest focused command.
2. Read the assertion and the code path it covers.
3. Check whether the test or the contract is wrong; fix the contract only when the
   intended behaviour is confirmed.
4. Add/adjust a regression test that fails without the fix.
5. Re-run the focused file/marker, then the narrow dependent tests.
6. Run the full default suite only at handoff or when the change crosses broad boundaries.

Do not repeatedly re-run a full suite to watch it. Start a managed background job, wait once
near the expected duration, then inspect once.

## 3. Server/web diagnostics

- Unexpected web exceptions return a generic 500 and are logged with method, path and
  traceback; never return exception classes, filesystem paths or DB details.
- Expected 400/404/409 messages stay useful and are safe to expose.
- Request bodies respect MAX_BODY_BYTES; never read an unbounded Content-Length.
- The web UI is home-network only and unauthenticated. Do not expose it publicly.
- Use the local server log tail and targeted curl requests for diagnosis; redact tokens,
  pairing codes, real server addresses and personal data.
- GET log lines include elapsed seconds, and an iOS workout-summary request logs a start line
  before authentication/dispatch. A missing completion line with a start line means the handler
  is still running or failed without a response; look for the traceback and the generic 500.
- If a code change makes the running web process stale, restart it the same way it was
  started (same DB/bind/port, detached). Verify GET /, POST /api/programme and that removed
  pages are gone. Config-only edits do not need a restart.

## 4. Data incidents

- Do not silently "fix" implausible rows. Flag, quarantine or report with a reason
  (REPS_TYPO/POSSIBLE_DOUBLE_SESSION and the DATA-QUALITY ledger are examples).
- Never delete or rewrite training history to make a test pass.
- A missing value stays missing; propagate unknown rather than substituting a plausible number.
- For a suspected import/identity problem, preserve the raw payload and record the decision.
- Never inspect or copy data/ or private/ into tracked files, logs or agent context.

## 5. Async/replay debugging

- Distinguish original occurrence time from server receipt time.
- Check idempotency receipt and per-event identity before assuming a duplicate write.
- Reproduce offline replay with a temporary database; verify ordering, conflict handling and
  acknowledgement state.
- Do not acknowledge work before it is persisted; do not mark server-accepted before ack.
- For execution telemetry, pair start/end events; never infer a duration from one timestamp.

## 6. iOS integration

The iOS build/test environment and live UI setup live in the client repository:
StrengthApp/docs/AGENT-WORKFLOWS.md and AGENT-LIVE-TESTS.md. Use the documented
DEVELOPER_DIR and pseudo-terminal workarounds there; do not change the system-wide Xcode
selection.

## 7. Reporting

Report only:
- task and changed files;
- decisions/assumptions;
- test status (focused/full);
- open risks/limitations;
- next action.
