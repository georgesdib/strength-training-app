# UI IMPROVEMENT PLAN — UI-04 AND UI-08

**Status:** proposed 2026-10-27. UI-04, UI-08a and UI-08b are not started; optional items are
unscheduled.
**Scope:** the local web UI only. No training calculations, prescription logic, database
semantics or Python API changes, except the HTTP request boundary in UI-04.
**Source:** the targeted UI improvement brief reviewed 2026-10-27; the corrections and
sequencing below take precedence where they differ.

---

## 1. Context

Two independent improvements are proposed.

**UI-04 — request-body limits.** `_body()` at
[server.py:247](../strength_coach/web/server.py#L247) reads
`int(Content-Length or 0)` bytes with no upper bound. The 20 MB per-file check is at
[server.py:766](../strength_coach/web/server.py#L766), after the whole request has been read
and JSON-parsed in [server.py:752](../strength_coach/web/server.py#L752). There is no 413
path. Malformed JSON and a non-object body already return 400 through the
`(ValueError, KeyError)` catch at [server.py:608](../strength_coach/web/server.py#L608);
the problem is the unbounded read, the silent handling of a missing or negative length, and
the lack of a framing policy for chunked requests. The handler inherits the standard
library's HTTP/1.0 default: there is no `protocol_version = "HTTP/1.1"`, so keep-alive
is off.

**UI-08 — incremental frontend modularisation.** The client is
[app.js](../strength_coach/web/static/app.js) (3,047 lines),
[history.js](../strength_coach/web/static/history.js) (388) and
[workout.js](../strength_coach/web/static/workout.js) (697), loaded as classic scripts in
that order at [index.html:1003](../strength_coach/web/static/index.html#L1003). Everything
shares one global namespace. `app.js` boots synchronously at
[app.js:3041](../strength_coach/web/static/app.js#L3041), and `setView` calls feature
loaders defined in the later files. An initial `#history` or `#workout` deep link
therefore already reaches an undefined function. Any feature extracted after `app.js`
would inherit that problem; any feature loaded before it cannot use the helpers defined in
`app.js`. This is the constraint the plan resolves first.

---

## 2. Goals and non-goals

Goals:

- reject oversized request bodies before reading them;
- preserve legitimate CSV imports and the current API for valid requests;
- return 413/411/400 consistently for bad framing and malformed JSON;
- fix the existing deep-link boot bug while making one frontend boundary real;
- keep the vanilla JavaScript architecture and the current script-loading model, with one
  deliberate exception: boot is deferred until every script is loaded;
- keep the final diffs limited to the phase being executed.

Non-goals:

- no React, Vue, bundler, build step or ES-module migration;
- no rewrite of the frontend or of `history.js`/`workout.js`;
- no change to training calculations, prescriptions, database semantics or rule behaviour;
- no browser automation in the implementation phases (see optional item O2);
- no attempt to remove every global or every line from `app.js`.

---

## 3. Phase 0 — commit the prerequisite

Commit the completed documentation audit and this plan before starting UI code. The working
tree already contains the audit changes; mixing them with UI-04 or UI-08 makes the final diff
unreviewable.

Baseline before UI-04:

- `.venv/bin/python -m pytest tests/test_docs_consistency.py tests/test_ui_docs.py -q`
- `.venv/bin/python tools/check_ui_docs.py`
- the full suite at the current count (887 at the time of writing; update after any test
  additions).

If the SD card is tight, run the full suite with `TMPDIR=/dev/shm` and a
`--basetemp` under `/dev/shm`.

---

## 4. Phase 1 — UI-04 request-body limits

### 4.1 Files

- [strength_coach/web/server.py](../strength_coach/web/server.py)
- `tests/test_web.py`, or a new `tests/test_web_body.py` for the boundary tests
- [docs/WEB-UI.md](WEB-UI.md)
- [ROADMAP.md](../ROADMAP.md) for the test count, if the convention is kept

### 4.2 Constants

Add near the other server constants, with a comment stating the domain reason:

```python
MAX_BODY_BYTES = 64 * 1024 * 1024
MAX_IMPORT_FILE_BYTES = 20 * 1024 * 1024
```

Rationale: two 20 MB decoded CSVs are 40 MB; JSON escaping and keys need headroom; 64 MB is
the smallest sensible request cap. A pathological file made mostly of quotes or backslashes
can expand about 2x, so a 20 MB escape-heavy file can exceed 64 MB. Accept that and document
it, or choose 96 MB for a hard guarantee. Do not go below 44 MB.

Use `MAX_IMPORT_FILE_BYTES` in `_import` instead of the hard-coded
`20 * 1024 * 1024` at [server.py:766](../strength_coach/web/server.py#L766). The per-file
check stays in `_import`; the request limit stays at the HTTP boundary.

### 4.3 `_body()` contract

| input | result |
|---|---|
| exactly one valid `Content-Length`, 0 < length <= limit | read exactly that many bytes, parse, return dict |
| valid length, malformed JSON or non-object | 400 with a JSON error; body has been consumed |
| length > `MAX_BODY_BYTES` | 413, set `close_connection = True`, do not read |
| missing `Content-Length` and no `Transfer-Encoding` | 411, close |
| invalid `Content-Length` (non-digits, negative, float, huge digit string) | 400, close |
| more than one `Content-Length` | 400, close |
| `Transfer-Encoding` present | 400 or 501, close; the stdlib does not decode chunked |
| `Content-Length: 0` | return `{}` without reading |

Implementation notes:

- use `self.headers.get_all("Content-Length")`, not `.get()`;
- reject a header value longer than about 20 characters before `int()`;
- accept only `str.isdigit()` (this rejects `-1`, `+1`, `5.0` and
  ` 5 ` after stripping);
- add a small `RequestError(status, message, close=True)` exception and catch it in
  `do_POST` before `(ValueError, KeyError)`, so 413 and 411 are not converted to
  400;
- set `close_connection = True` for every framing rejection; optionally send
  `Connection: close`;
- keep the existing 400 for invalid JSON and non-object JSON, but use a stable message such
  as `JSON body must be an object` rather than a raw decoder string;
- `Expect: 100-continue` is optional: a custom `handle_expect_100` can return 413
  before the client sends the body, but do not make it a requirement.

If a real client needs the old missing-length behaviour, treat it as an empty body and close
the connection; do not leave the socket open.

### 4.4 Tests

Use patchable limits. Do not build a 40 MB body in a test.

- normal JSON POST;
- patched limit of about 1 KB: exactly at the limit accepted, limit + 1 gives 413;
- headers-only 413: raw socket, `Content-Length` above the limit, no body; read the
  response with a timeout, proving no read blocked;
- a fake `rfile` whose `read()` raises, passed to `_body()`, proving the
  limit is checked first;
- invalid lengths: `abc`, `-1`, `5.0`, a very long digit string;
- missing length gives 411; duplicate length gives 400;
- `Transfer-Encoding: chunked` gives 400/501;
- malformed JSON and non-object JSON give 400 with a JSON error;
- legitimate import near a patched limit: patch the request and per-file limits down, post
  two small CSVs just under the request limit, expect 200; one file just over the per-file
  limit gives 400;
- existing import regression at `test_web.py:281`;
- an assertion that `MAX_BODY_BYTES >= 2 * MAX_IMPORT_FILE_BYTES + 4 MB`.

### 4.5 Docs

Add a **Request limits** section to [docs/WEB-UI.md](WEB-UI.md): 64 MB request, 20 MB per
decoded CSV, 413/411/400 behaviour, chunked rejected, HTTP/1.0 (no keep-alive), local-only
threat model. State that the import is JSON text, not multipart, and that the per-file check
is on decoded UTF-8 bytes.

### 4.6 Risks

- A 413 while the client is still uploading can surface as a connection reset; close and test
  headers-only.
- A future `HTTP/1.1` switch makes close/drain mandatory; record that in the comment.
- 64 MB still allows roughly 100 MB of parse memory; acceptable for a local app, but note it
  if the host is memory-constrained.
- Changing missing-length behaviour to 411 can break an unusual client; check the actual
  clients before merging.

---

## 5. Phase 2 — UI-08a: core helpers and deferred boot

This phase is a prerequisite for UI-08b. It is also the correction for the existing
deep-link bug.

### 5.1 Why

At [app.js:3041](../strength_coach/web/static/app.js#L3041) the boot block runs immediately.
`applyHashRoute` calls `setView`, which calls `loadHistory` (in
`history.js`) and `updateWorkflowStep` (in `workout.js`), both loaded after
`app.js`. An initial `#history` or `#workout` link therefore reaches an
undefined function. Deferring boot until all scripts are loaded fixes that and allows a
feature module to load after `app.js`.

### 5.2 Changes

- add `core.js` loaded first, with `$`,
  `today`, `esc`, `sessionLabel`, `fmt`, `api` and
  `notify` moved from `app.js`; keep the same global names and do not rewrite
  call sites;
- load order in `index.html`: `core.js`, `app.js`, `history.js`,
  `workout.js`;
- move the boot block into a `DOMContentLoaded` listener in `app.js`, or into a
  final `boot.js` loaded last; all scripts are parser-blocking at the end of the body,
  so both work;
- leave `setView` in `app.js`; it is still the router;
- do not move feature code in this phase.

### 5.3 Tests

- parse `index.html`, assert every referenced script exists and the order is
  core -> app -> history -> workout;
- `node --check` every static `.js` file (skip if node is absent);
- every inline handler in `index.html` resolves to a function defined in one of the
  scripts; the current one is `saveReadinessContext()` at
  [index.html:567](../strength_coach/web/static/index.html#L567);
- a manual browser smoke test of `#history`, `#workout` and
  `#docs?doc=...`. No browser automation is installed, so record it as manual.

### 5.4 Acceptance

`#history` and `#workout` load their data on first open; no feature code has
moved; all existing tests pass.

---

## 6. Phase 3 — UI-08b: extract Exercises

Exercises first: it is cohesive, has a small API surface and is not entangled with the
training workflow. Settings is larger but carries theme, LLM, profile and boot concerns;
make it a later extraction (O1).

### 6.1 Changes

- move the exercise catalogue block from `app.js` (around
  [app.js:2049](../strength_coach/web/static/app.js#L2049) through
  `loadExerciseCatalog`) and its top-level listeners to
  `static/exercises.js`;
- keep `loadExercises()`, the small picker at
  [app.js:1868](../strength_coach/web/static/app.js#L1868), in `app.js` unless the move
  is clearly cheaper with it;
- `exercises.js` uses only the core globals and exposes `loadExerciseCatalog`,
  `openExerciseEditor`, `openExerciseDetails`, `saveExerciseDetails` and
  `openExerciseE1rm`;
- load `exercises.js` after `app.js` and before the deferred boot;
- do not copy `api` or `esc` into the module;
- update [docs/UI-MAP.md](UI-MAP.md) if any docs links move, and
  [docs/WEB-UI.md](WEB-UI.md) with the module list.

### 6.2 Correct the test coupling

`tests/test_web.py` pins strings to `app.js` at
[test_web.py:1006](../tests/test_web.py#L1006) (exercise e1RM),
[test_web.py:1015](../tests/test_web.py#L1015) (tests-needed table),
[test_web.py:1025](../tests/test_web.py#L1025) (symptom form) and
[test_web.py:1063](../tests/test_web.py#L1063) (declared breaks). Add a helper that
concatenates every client script and assert the contract across the client, not against
`app.js`. Update [test_web.py:131](../tests/test_web.py#L131), which currently scans only
`app.js` for `#docs?doc=` links, to scan every script.

### 6.3 Tests and smoke

- existing web tests with the all-JS helper;
- exercise catalogue, editor, details and e1RM endpoints still work;
- script order/existence and inline-handler checks from UI-08a;
- `node --check` on the new file;
- manual smoke: open Exercises, edit a row, open details, save, open the e1RM override, and
  navigate away and back.

### 6.4 Acceptance

Exercises behaves exactly as before; `app.js` no longer contains the catalogue code;
no duplicated `api`/`esc`; tests and docs updated.

---

## 7. Corrections to the original brief

| # | original claim or gap | correction |
|---|---|---|
| 1 | malformed JSON currently returns a 500 | it already returns 400 through the `ValueError` catch; standardise the message instead |
| 2 | missing `Content-Length` is a minor case | it is a framing decision: 411 and close, or treat as empty and close |
| 3 | `Transfer-Encoding` is not mentioned | reject chunked explicitly; the stdlib does not decode it |
| 4 | reject oversized bodies | also close the connection, and test with a headers-only request |
| 5 | per-file 20 MB limit | it is hard-coded at `server.py:766`; make it `MAX_IMPORT_FILE_BYTES` |
| 6 | frontend tests cover the refactor | `test_web.py` pins strings to `app.js`; use an all-JS helper |
| 7 | docs-link test covers the client | `test_web.py:131` scans only `app.js`; scan every script |
| 8 | script order is preserved | the current boot already breaks `#history`/`#workout`; defer boot first |
| 9 | no feature becomes inaccessible | add a static inline-handler check; a single `onclick` already depends on a global |
| 10 | browser behaviour is verified | no browser/Playwright is installed; state that smoke testing was manual |

---

## 8. Optional items (unscheduled)

These are deliberately outside UI-04 and the first UI-08 phases. Pick them up only after the
preceding phases are green.

**O1 — extract Settings.** The next feature extraction: theme, LLM settings, browser defaults,
modalities and profile diff (roughly `app.js` 2660-3040). It is larger but less related
to training logic. It needs the same core/boot prerequisites.

**O2 — browser automation.** No Playwright or Selenium is installed; node and npm exist but
there is no browser binary. A separate change can add Playwright or a jsdom smoke test for
navigation, deep links and the workout lifecycle. Do not mix it into the refactor.

**O3 — a view registry.** `setView` directly calls a long list of feature loaders. A
registry (`registerView(name, loader)`) would make the router extensible, but it changes
the boot and loading contract. Defer until at least two features have moved.

**O4 — migrate `history.js` and `workout.js` to core.** They still use app.js
globals. Leave them stable in this pass; migrate them only if a third feature needs the same
helpers.

**O5 — streaming or multipart imports.** The request cap bounds memory but a legitimate
40 MB import still parses as a Python object. If the local host is memory-constrained, a
streaming CSV import is the real fix. Out of scope here.

**O6 — read timeouts.** A client can declare a valid length and send it slowly, occupying a
thread in `ThreadingHTTPServer`. A per-connection read timeout would address slowloris;
the local-only threat model makes it lower priority.

**O7 — HTTP/1.1 and keep-alive.** The handler is HTTP/1.0. If it is ever switched to HTTP/1.1,
body rejection must close or drain, otherwise an unread body can be parsed as the next
request.

**O8 — limit tuning.** 64 MB is the default. Revisit 96 MB only if a legitimate escape-heavy
import is rejected; revisit a lower cap only if memory pressure appears. Record the change in
`WEB-UI.md`.

**O9 — error copy.** The UI currently shows the server's error string in a toast or a panel.
If the new 411/413 messages are too technical, add a small client-side mapping without
changing the API contract.

---

## 9. Acceptance criteria

UI-04:

- an oversized body is rejected with 413 before `rfile.read`;
- a legitimate import inside the patched or real limits succeeds;
- malformed framing returns 400/411, not 500;
- tests cover normal, boundary, oversized, invalid and chunked inputs;
- `WEB-UI.md` states the policy and the HTTP version;
- no training logic changes.

UI-08a:

- the client still works and `#history`/`#workout` load on first open;
- `core.js` is loaded first and duplicated helpers are removed from `app.js`;
- every script exists, is syntactically valid and is loaded in the documented order;
- every inline handler resolves.

UI-08b:

- Exercises behaves as before;
- `app.js` no longer contains the catalogue block;
- the new module uses the core helpers and does not duplicate them;
- tests and docs are updated.

Overall:

- the full suite passes; report the exact count;
- `tools/check_ui_docs.py` is green;
- no Python API, training calculation, database or prescription change is in the diff;
- the final diff contains only the phase being reviewed.

---

## 10. Verification commands

```bash
.venv/bin/python -m pytest tests/test_web.py tests/test_ui_docs.py -q
.venv/bin/python -m pytest tests/test_docs_consistency.py -q
.venv/bin/python tools/check_ui_docs.py
node --check strength_coach/web/static/*.js
.venv/bin/python -m pytest -q          # full suite, once per phase
```

For the full suite on a tight SD card:

```bash
TMPDIR=/dev/shm .venv/bin/python -m pytest -q --basetemp=/dev/shm/pytest-ui
```

---

## 11. Risks and rollback

- **413 while uploading:** close the connection; test with headers only.
- **Missing-length policy:** 411 is correct HTTP but could surprise a non-browser client;
  verify before merging.
- **Boot deferral:** it changes when initial data loads. Test `#history`,
  `#workout` and `#docs` manually; the change also fixes a pre-existing bug.
- **Feature extraction:** the main risk is a missing global or listener. The static handler
  check, `node --check` and the manual smoke test are the guards.
- **Test coupling:** update the tests to scan all JS rather than weakening the assertions.
- **Rollback:** UI-04 is independent. UI-08a can be reverted without touching UI-08b; UI-08b
  is a single file move and can be reverted alone.

---

## Related

- **Evidence:** [WEB-UI.md](WEB-UI.md), [UI-MAP.md](UI-MAP.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
