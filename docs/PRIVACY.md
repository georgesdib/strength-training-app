# PRIVACY AND PUBLIC DOCS

This repository is public. The app is local-only and has no authentication.

## 1. Rule

Public docs must not contain:

- exact personal health history or symptom episodes;
- exact personal performance values or body measurements;
- exact single-athlete sample sizes or dates that identify a training history;
- raw exports, database rows or workout logs.

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
personal health and performance detail. The app itself remains local-only: do not expose the
server beyond `127.0.0.1`.
