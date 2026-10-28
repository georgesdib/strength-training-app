# PRIVACY AND PUBLIC DOCS

This repository is public. The app is local-first and uses a single local data store. The web
UI is exposed on the owner's home LAN with no authentication and no TLS for now; this is an
explicitly accepted temporary risk (`LIM-57`) and must not be exposed to the public internet.

## 1. Rule

Public docs must not contain:

- exact personal health history or symptom episodes;
- exact personal performance values or body measurements;
- exact single-athlete sample sizes or dates that identify a training history;
- raw exports, database rows or workout logs;
- real usernames, passwords, birth dates, gender values or other account/profile values.
  Design and roadmap examples must use placeholders; credentials and birth dates belong only in
  the private setup record or the local CLI, never in the public repository.

Use a general description, a synthetic example, or move the exact detail to `private/`.

## 2. Where private material lives

- `data/` — local database and raw exports (git-ignored).
- `private/docs/` — personal evidence, baselines, context and audit appendices (git-ignored).
- `private/docs/PRIVATE-CONTEXT.md` — the exact details intentionally omitted from public docs.

## 3. What is still public

- design decisions and their rationale without personal values;
- rule IDs, config assumptions and code paths;
- aggregate method descriptions;
- synthetic test fixtures;
- evidence citations.

## 4. Git history

Earlier commits already contain some personal details. Removing them from the current tree does
not remove them from Git history. Rewriting history is not part of this project. Do not add new
personal data to public docs or commits.

## 5. Adding docs

Before committing a doc, ask:

1. Is this a personal value, date, symptom or sample size? → private.
2. Is this a reproducible method or rule? → public.
3. Is this an example? → synthesise it.
4. Does a test need it? → synthesise it; never read `data/raw` in a public test.

## 6. Scope

This policy does not make the repository anonymous. It keeps new public documentation free of
personal health and performance detail. The app data stays on the owner's server, but the web
UI is temporarily reachable on the home LAN over unauthenticated HTTP (`LIM-57`). Do not expose
the server to the public internet or put it on an untrusted network.
