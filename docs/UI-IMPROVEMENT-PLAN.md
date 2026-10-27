# UI AND FUNCTIONALITY IMPROVEMENT PLAN — UI-04, UI-08 AND FINAL AUDIT

**Status:** proposed 2026-10-27. Phase 0 (the documentation audit and this plan) is committed.
No implementation workstream has started. Browser verification is gated by the tooling decision
in Workstream D.
**Scope:** the local web UI, the HTTP request boundary, date handling, backend error responses,
data integrity, browser verification and frontend modularisation. No training calculations,
prescription rules, readiness interpretation, database schema or historical data changes
unless a reproduced correctness defect requires it.
**Sources:** the UI-04/UI-08 brief and the final functionality/code audit, both reviewed
2026-10-27. This document is the single plan for both; the two briefs are no longer maintained
separately.

---

## 1. Why this plan

The two briefs overlap at UI-04 (request-body limits) and UI-08 (frontend modularisation). They
add five areas that the earlier plan did not cover: unsafe inline handlers, deterministic dates,
safe 500 responses, data-integrity/transaction boundaries, and browser-level coverage. This
plan folds them into one sequence so the same code is not touched twice and every confirmed
finding gets a regression test and a permanent guard.

The ordering principle is: **security and request correctness first, determinism second, data
integrity third, browser evidence fourth, modularisation last.** Modularisation is the only
workstream that is purely structural; it must not hide or complicate the correctness fixes.

Every final-audit finding is assigned to Workstreams A–F or explicitly marked no-change in the
findings ledger. The O1–O10 items in §14 are deferred improvements, not omitted: they stay in
this plan with a trigger, but they are not part of commits 0–8.

---

## 2. Findings ledger

Status labels:
- **Confirmed** — the code shows the defect directly.
- **Confirmed risk** — the code shows a realistic failure path; reproduce before changing.
- **Latent** — the pattern is unsafe, but current value domains constrain exploitability.
- **Optional** — an improvement, not a demonstrated defect.
- **No change** — inspected and not reproduced.

| ID | Finding | Status | Evidence | Fix |
|---|---|---|---|---|
| F1 | Five dynamic inline handlers interpolate values into executable JavaScript. `esc()` is HTML escaping, not JS-string escaping. | Confirmed; latent exploitability | `app.js` 343, 344, 398, 860, 1207; `esc` at 5 | A1 |
| F2 | Dates are not deterministic: `today()` uses a locale-formatted string and two paths use UTC `toISOString().slice(0, 10)`. | Confirmed | `app.js` 3, 780, 1595 | B |
| F3 | Unexpected 500 responses return the exception class and message; no server-side traceback logging. | Confirmed | `server.py` 476, 611 | A3 |
| F4 | Request bodies are read with an unbounded `Content-Length`; missing/negative length is silent; no 413; chunked is not handled. | Confirmed | `server.py` 247–255, 766 | A2 |
| F5 | A double-submit or timeout-retry can append a duplicate workout set; the server computes the next index and the UI has no in-flight guard. | Confirmed risk | `workout.js` 597; `workout.py` 338 | C |
| F6 | `workout.end` writes the session, clean sets and workout update without one transaction; a partial session can survive and a retry skips it. | Confirmed risk | `workout.py` 1148, 1017 | C |
| F7 | A failed import leaves raw rows and partial artifacts; the run is marked error but data is not rolled back. | Confirmed risk | `store/importer.py` 113–180 | C |
| F8 | `add_set` writes the set and its event in two statements without a transaction. | Confirmed risk | `workout.py` 338–387 | C |
| F9 | Ruff is configured but not in the dev dependencies and not installed, so the configured lint check cannot run. | Confirmed | `pyproject.toml` 41; no `ruff` in dev extras | F |
| F10 | No browser, Playwright or Selenium is installed; node/npm exist. No browser workflow test currently exists. | Confirmed | environment; `tests/test_web.py` is HTTP-level | D |
| F11 | A successful history response can include a raw exception message in `warnings`. | Confirmed | `history.py` 430 | A3 |
| F12 | Markdown escapes text and hrefs and does not pass raw HTML, but does not reject a `javascript:` link target. Docs are trusted, so this is low risk. | Optional | `web/markdown.py` | O9 |
| F13 | `app.js` is 3,047 lines with a global namespace; `setView` reaches into later-loaded files; `#history`/`#workout` deep links already reach undefined loaders at boot. | Confirmed; structural | `app.js` 49, 126, 3041; `index.html` 1003 | E |
| F14 | `_workout_start` records readiness before the plan/workout transaction; a failed start can leave a readiness row. | Reproduce / decide | `server.py` 809–821 | C |
| F15 | `workout.start` and `history.edit` already use transactions. | No change | `server.py` 821; `history.py` 442 | — |
| F16 | Read-only endpoints and LLM boundaries were inspected; no demonstrated override or write path was found. | No change without reproduction | `agents/`, web GET paths | — |

---

## 3. Principles

1. **Reproduce before fixing a data-integrity claim.** Static inspection identifies the path; a
   test proves the failure before a transaction or schema change.
2. **One workstream per commit.** Do not combine security, dates, transactions and
   modularisation in one diff.
3. **No framework, bundler or build step.** Vanilla JavaScript and the current no-build
   architecture stay.
4. **No schema change unless required.** A request id for set idempotency is possible without
   schema changes if the client sends `set_index`; otherwise justify a column/table.
5. **No training, prescription or readiness semantics changes.** A reproducible correctness
   defect is the only exception, and it gets its own decision note.
6. **No personal data in tests, logs or docs.** Use synthetic fixtures.
7. **Be explicit about evidence.** Label claims as static inspection, automated test or real
   browser verification. Never claim a browser check that was not run.
8. **Every confirmed finding gets a permanent guard**, not just a one-off fix: a regression test,
   a static check, a documented rule, or all three (Workstream F).

---

## 4. Workstream A — security and the request boundary

### A1. Replace dynamic inline handlers

The five dynamic handlers at [app.js:343](../strength_coach/web/static/app.js#L343),
[344](../strength_coach/web/static/app.js#L344), [398](../strength_coach/web/static/app.js#L398),
[860](../strength_coach/web/static/app.js#L860) and
[1207](../strength_coach/web/static/app.js#L1207) must stop embedding values in `onclick`.

Use one of:

- **event delegation** on a stable container, with the identifier in a `data-*` attribute;
- **a listener attached after rendering**, closing over the value;
- **a small dispatch table** keyed by `data-action`, with the value read from `dataset`.

Do not replace `esc()` with a new generic JavaScript-string escaper and keep inline handlers.
The correct fix is to remove the executable-string context.

Keep the two static handlers (`applySuggestedDeload()`, `openWorkoutStart()`) only if they
remain literal and non-interpolated; otherwise convert them for consistency. The static
`saveReadinessContext()` at [index.html:567](../strength_coach/web/static/index.html#L567) can
stay until the same conversion is applied to that panel.

Checks:

- regression tests with identifiers and labels containing `'`, `"`, `<`, `>`, `&`,
  backticks and `</script>`; assert the generated DOM structure and that no code runs;
- a static test that the client JS contains no interpolated event-handler attributes (the
  generated files must contain no `on..="` pattern; a literal static handler in
  `index.html` may be allowlisted);
- a manual/browser check that the affected actions still fire.

Current value domains are constrained: exercise ids must match
`^[a-z][a-z0-9_]*$` at [exercise_admin.py:20](../strength_coach/store/exercise_admin.py#L20),
review task keys are a fixed pair, and session ids are dates/UUIDs. The finding is therefore a
latent unsafe construction, not a demonstrated live exploit. Fix it anyway.

### A2. Enforce request-body limits

This is the existing UI-04 requirement, with the evidence from the final audit.

Constants, documented in `WEB-UI.md`:

```python
MAX_BODY_BYTES = 64 * 1024 * 1024
MAX_IMPORT_FILE_BYTES = 20 * 1024 * 1024
```

Rationale: two 20 MiB decoded CSVs are 40 MiB; JSON escaping and keys need headroom; 64 MiB is
the smallest sensible cap. A pathological escape-heavy file can expand about 2x; document that
a near-limit file can receive 413, or choose 96 MiB for a hard guarantee. Do not go below
44 MiB. Replace the hard-coded `20 * 1024 * 1024` in [server.py:766](../strength_coach/web/server.py#L766).

Body contract:

| Input | Result |
|---|---|
| one valid `Content-Length`, 0 < length <= limit | read exactly length, parse, return object |
| malformed JSON, invalid UTF-8, non-object | 400 JSON error |
| length > limit | 413, close, do not read |
| missing length, no chunked | 411, close |
| invalid/negative/duplicate length | 400, close |
| `Transfer-Encoding` | 400/501, close; stdlib does not decode chunked |
| length 0 | empty object |

Implement a small `RequestError(status, message, close=True)` and catch it before the generic
`ValueError` catch. Set `close_connection = True` on every framing rejection. The handler is
HTTP/1.0 today; if it ever becomes HTTP/1.1, close/drain is mandatory.

Tests, with patched limits and no 40 MiB allocations:

- normal JSON;
- boundary at a patched 1 KiB limit;
- headers-only oversized request returns 413 without reading (raw socket, timeout);
- a fake `rfile` whose `read()` raises proves the limit check runs first;
- invalid, missing, negative, duplicate and oversized length;
- chunked rejection;
- malformed JSON and non-object;
- a legitimate import near a patched limit;
- existing import regression;
- constant relationship `MAX_BODY_BYTES >= 2 * MAX_IMPORT_FILE_BYTES + 4 MiB`.

### A3. Safe backend errors

At [server.py:476](../strength_coach/web/server.py#L476) and
[server.py:611](../strength_coach/web/server.py#L611), replace
`f"{type(exc).__name__}: {exc}"` with a generic JSON 500, for example
`{"error": "internal server error"}`.

- log the unexpected exception server-side with method, path and traceback;
- never log request bodies, API keys or personal training data;
- keep the useful 400/404/409 messages;
- keep the JSON shape consistent;
- sanitize [history.py:430](../strength_coach/history.py#L430): log the detail and return a
  generic warning, or omit the raw exception from the response.

Tests: monkeypatch a handler to raise, assert 500 and generic body, assert the traceback is
logged; assert a normal 400 still carries its message; assert a successful history edit does not
echo an internal exception.

---

## 5. Workstream B — deterministic dates

Policy: **the local calendar date in `YYYY-MM-DD` is authoritative** for UI defaults and daily
records. The browser and server are expected to share the machine timezone in this local-only
app. Document that in `WEB-UI.md`.

Implement one helper, used everywhere:

- `formatLocalDate(date)` using `getFullYear`, `getMonth() + 1`, `getDate()`;
- `today()` = `formatLocalDate(new Date())`;
- no `toLocaleDateString` for a machine-readable date;
- no `toISOString().slice(0, 10)` for a local date.

Replace [app.js:3](../strength_coach/web/static/app.js#L3),
[app.js:780](../strength_coach/web/static/app.js#L780) and
[app.js:1595](../strength_coach/web/static/app.js#L1595). Check date inputs, history filters,
prescription/readiness defaults and workout start dates for the same pattern.

Tests:

- Node or browser tests with fixed timezones for a UTC date boundary and a DST transition;
- a local-midnight case proving the date does not roll over;
- invalid-date handling;
- backend API defaults use `datetime.date.today()` local; add a test where practical;
- a static check that client JS contains no `toISOString().slice(0, 10)` or
  `toLocaleDateString` date conversion outside the helper.

---

## 6. Workstream C — data integrity and concurrency

Reproduce each item before changing code.

| Invariant | Current state | Action |
|---|---|---|
| duplicate start | start is guarded and wrapped in `BEGIN IMMEDIATE` | keep; test concurrent start |
| duplicate set | no in-flight guard; server computes next index | client in-flight guard; decide server idempotency |
| duplicate end | second end raises "not in progress"; materialise is retry-aware | make retry return the completed workout or a defined 409; test |
| partial end | multi-statement write is not transactional | wrap `end` in `db.transaction`; test injected failure |
| partial import | writes are not transactional; failed run is marked but rows remain | transaction around data writes; decide where a failed run is recorded |
| add_set atomicity | set + event are separate statements | wrap in `db.transaction` |
| start readiness | readiness is recorded before the start transaction | decide whether that is intended; if not, move inside |

For duplicate sets, the robust options are:

1. **Client-side in-flight guard** (disable the submit button while the request is open) — closes
   the double-click, not a retry after timeout.
2. **Client-supplied `set_index`** plus the existing unique key — a duplicate retry gets a
   constraint error; return the current workout and a clear message instead of a silent append.
3. **A request-id idempotency key** — the strongest option; likely needs a new column/table, so
   justify it before adding.

Do not deduplicate sets by content: identical sets are real sets. Do not add global locks. Use
`db.transaction` at [db.py:145](../strength_coach/store/db.py#L145), which already handles
savepoints.

Import failure design needs a decision: a transaction that rolls back the data also rolls back
the run row. Either record the failed run in a separate short transaction after the rollback, or
accept the existing `error` run as the record and document it. Choose one and test it.

Concurrency tests only where realistic: two simultaneous starts, two ends, two imports, and a
double set submission. Do not redesign persistence.

---

## 7. Workstream D — browser verification

No browser, Playwright or Selenium is installed; node and npm exist. The default suite is
HTTP-level. The brief requires an honest decision.

Preferred: add **Playwright for Python** as an optional `browser` extra, not a runtime
dependency:

- `playwright` in `[project.optional-dependencies].browser`;
- a `browser` pytest marker, skipped with a clear reason if Playwright or the browser binary is
  absent;
- reuse the temp-DB server fixture at [test_web.py:30](../tests/test_web.py#L30), or add a
  browser fixture that starts the same server;
- start with a small smoke suite, not the full ten-step journey.

Smoke suite:

1. load, navigate the primary views, assert no `pageerror` and no failed static requests;
2. docs deep link;
3. readiness save and reload;
4. generate and inspect a prescription;
5. start a workout, add a set, end it, open History/Review and verify the persisted session;
6. one recoverable failure path (route abort or duplicate submit).

Assert state transitions and persisted results, not just element existence. Add import
preview/apply and broader failure paths after the smoke suite is stable.

Fallback if a browser is not accepted: a manual checklist plus the static script-order,
inline-handler and `node --check` tests; state explicitly that browser behaviour was not
verified. Do not claim otherwise.

---

## 8. Workstream E — frontend modularisation

This is UI-08, last and separate. It depends on the boot fix and the handler work.

### E1. Core helpers and deferred boot

- add `core.js` first with `$`, `today`, `esc`, `sessionLabel`, `fmt`, `api`, `notify`;
- load order: core, app, history, workout;
- move the boot block at [app.js:3041](../strength_coach/web/static/app.js#L3041) into a
  `DOMContentLoaded` listener (or a final `boot.js`);
- this also fixes the existing `#history`/`#workout` deep-link failure, because `setView`
  will no longer run before those files load.

### E2. Extract Exercises

Move the exercise catalogue block from `app.js` (around
[app.js:2049](../strength_coach/web/static/app.js#L2049) through `loadExerciseCatalog`) and its
listeners to `exercises.js`. Keep `loadExercises()` (the picker) in `app.js` unless the move
is clearly cheaper. The module uses core helpers and exposes `loadExerciseCatalog`,
`openExerciseEditor`, `openExerciseDetails`, `saveExerciseDetails` and `openExerciseE1rm`.

Settings is the next candidate, not part of this pass.

### E3. Test coupling

`tests/test_web.py` pins strings to `app.js` at lines 1006, 1015, 1025 and 1063. Replace those
with an all-JS helper so the contract is “the client contains this”, not “this file contains
this”. Update the docs-link scan at line 131 to scan every script.

### E4. Checks

- script existence and order;
- inline-handler resolution;
- `node --check` on every static JS file;
- all-JS docs-link resolution;
- manual browser smoke (or Workstream D).

---

## 9. Workstream F — permanent guardrails

The fixes are only permanent if the next change cannot silently reintroduce them.

### F.1 Regression matrix

| Finding | Permanent test | Static guard | Documented rule |
|---|---|---|---|
| F1 inline handlers | hostile identifiers/labels; DOM structure; no execution | no interpolated `on..="` in client JS | `WEB-UI.md`: HTML escaping is not JS escaping |
| F2 dates | UTC boundary, local midnight, DST, invalid date | no `toISOString().slice(0, 10)` or date `toLocaleDateString` | `WEB-UI.md`: local calendar-date policy |
| F3 500 leak | injected exception returns generic body; traceback logged | no `_error(500, f"{type...` pattern | `WEB-UI.md`/AGENTS: generic 500 + server log |
| F4 body limits | boundary, fake read, 413/411/400, chunked | constants and relationship assertion | `WEB-UI.md`: request limits |
| F5 duplicate set | double-submit and retry test | client busy-state assertion where practical | `WEB-UI.md`: idempotency note |
| F6/F7/F8 transactions | injected failure leaves no partial state | code review; no static substitute | AGENTS: multi-statement writes use `db.transaction` |
| F9 lint | `ruff check` in the verification lane | ruff in dev extras | AGENTS/README: lint command |
| F10 browser | browser suite or explicit skip | `browser` marker | docs: what was and was not run |
| F11 warnings | history warning is generic | no raw exception interpolation in warnings | `WEB-UI.md` |
| F13 modularisation | script order, handlers, node check | all-JS scan | `WEB-UI.md`: module map |

### F.2 Static checks to add

Keep these small and explicit; do not build a general parser.

- no interpolated event-handler attributes in the client JS;
- every inline handler in `index.html` resolves to a function in a loaded script;
- every `<script src>` exists and follows the documented order;
- no `toISOString().slice(0, 10)` or date `toLocaleDateString` outside the date helper;
- no `_error(500, f"{type` pattern;
- request-limit constants satisfy the documented relationship;
- `node --check` on every static JS file (skip if node is absent);
- existing docs consistency tests remain green.

### F.3 Toolchain

- Add `ruff>=0.6` to `[project.optional-dependencies].dev`; run `ruff check .` with the
  existing configuration at `pyproject.toml` 41.
- Add a `browser` marker; keep it out of the default lane unless the browser is installed.
- Update `docs/WEB-UI.md` with request limits, date policy, error behaviour and the module map.
- Update `AGENTS.md` with the multi-statement transaction and no-inline-handler rules when the
  fixes land, not before.
- Keep the existing `tests/test_docs_consistency.py` in every docs change.

---

## 10. Commit sequence and dependencies

| # | Commit | Contents | Depends on |
|---|---|---|---|
| 0 | Documentation audit + plan | done | — |
| 1 | Inline handlers | A1 + tests + static guard | — |
| 2 | Request-body limits | A2 + tests + `WEB-UI.md` | — |
| 3 | Safe 500s | A3 + logging + tests | — |
| 4 | Deterministic dates | B + helper + tests | — |
| 5 | Data integrity | C: reproduce, transactions, duplicate-set decision | 1, 4 for browser/state tests |
| 6 | Browser smoke | D: Playwright optional, smoke suite | 1–4; 5 for duplicate test |
| 7 | Core and boot | E1 + script/handler checks | 1, 4 |
| 8 | Exercises extraction | E2/E3 + docs | 6, 7 |

Do not combine 1–5. Commit 6 may be skipped if the browser decision is “manual only”; record
that decision explicitly.

---

## 11. Acceptance criteria

A1:

- no dynamic value is inserted into an executable inline context;
- hostile values cannot change the DOM structure or execute;
- affected actions still work.

A2:

- oversized bodies get 413 before `rfile.read`;
- legitimate imports inside the policy succeed;
- invalid framing gets 400/411, never 500;
- tests cover normal, boundary, oversized, invalid and chunked inputs;
- `WEB-UI.md` states the policy and the HTTP version.

A3:

- unexpected failures return generic 500 JSON;
- tracebacks are logged server-side without body/personal data;
- expected 400/404/409 messages remain useful;
- history warnings do not echo raw exceptions.

B:

- one local `YYYY-MM-DD` helper is used for defaults;
- no UTC slice or locale date contract remains;
- midnight/UTC/DST/invalid-date tests pass;
- the policy is documented.

C:

- duplicate set, partial end and partial import are reproduced or explicitly accepted;
- the chosen fixes are covered by failure-injection tests;
- start and history edit remain transactional;
- no broad locking or schema change without justification.

D:

- a browser suite runs, or the lack of one is explicitly documented;
- tests assert state/persistence, not just element presence;
- no claim of browser verification without an actual run.

E:

- `#history` and `#workout` load on first open;
- script order and inline handlers are checked;
- Exercises behaves as before; no duplicated core helpers;
- tests and docs are updated.

F:

- every confirmed finding has a regression test or a documented reason it cannot have one;
- lint runs; static guards are in the suite;
- the full suite passes; the exact count is reported;
- the final diff for each commit contains only that workstream.

---

## 12. Verification

```bash
.venv/bin/python -m pytest tests/test_web.py tests/test_docs_consistency.py tests/test_ui_docs.py -q
.venv/bin/python -m pytest -q
.venv/bin/ruff check .            # after adding ruff to the dev extra
node --check strength_coach/web/static/*.js
.venv/bin/python tools/check_ui_docs.py
.venv/bin/python -m pytest -m browser -q   # only when the browser extra is installed
```

On a tight SD card:

```bash
TMPDIR=/dev/shm .venv/bin/python -m pytest -q --basetemp=/dev/shm/pytest-ui
```

Report static inspection, automated results and browser results separately. A skipped browser
test is not a passed browser test.

---

## 13. Risks and rollback

- **Inline-handler conversion** can silently break actions if a listener is missed. The static
  handler check and browser smoke are the guards; rollback is the single workstream commit.
- **413 while uploading** can surface as a reset; close and test headers-only.
- **Missing-length policy** can surprise a non-browser client; verify before merging.
- **Date helper** changes defaults at midnight; test both sides of the boundary.
- **Transactions** can turn a partial write into an error where a retry previously succeeded;
  test the user-visible behaviour, not only the database.
- **Browser tests** are environment-sensitive; mark and skip rather than failing the default
  lane, but do not let the skip hide a regression in CI.
- **Modularisation** is the easiest place to lose a global; keep it last and separate.

---

## 14. Deferred follow-ups (in the plan, not in the current sequence)

These are part of the plan, not a separate backlog. They are deferred because they are
improvements rather than confirmed defects, depend on an earlier workstream, or need a decision
or evidence. Each has a trigger; promote it to a numbered commit when the trigger is met. They
are not part of commits 0–8.

- **O1 — Settings extraction** after Exercises.
- **O2 — view registry** for `setView`; defer until at least two features have moved.
- **O3 — migrate `history.js`/`workout.js` to core**; leave stable until a third feature
  needs the same helpers.
- **O4 — streaming/multipart imports** if 40 MiB parse memory becomes a problem.
- **O5 — read timeouts** for slow bodies (slowloris); local-only, lower priority.
- **O6 — HTTP/1.1 and keep-alive**; only with close/drain and tests.
- **O7 — limit tuning** (64 vs 96 MiB) based on a rejected legitimate import.
- **O8 — error copy** mapping 411/413 to friendly UI text.
- **O9 — markdown scheme allowlist** for `javascript:` targets.
- **O10 — expand browser coverage** to import preview/apply and more failure paths.

---

## Related

- **Evidence:** [WEB-UI.md](WEB-UI.md), [UI-MAP.md](UI-MAP.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
