# RELEASING AND CI

**Status:** CI and release gates are implemented in the repository. **v1.3.0** was published
as a stable GitHub Release on 2026-11-06; **v1.4.0** is the current stable release (2026-11-13).
The process below remains the release contract.

The app is a local-first Python 3.11+ web application. There is no PWA, service worker, Node
build or compiled frontend. The deployable production artifact is a source archive containing
the Python package, config, docs and static assets; a wheel is also built as a package
artifact.

## Local checks

Install the same pinned dependencies CI uses:

    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.lock
    .venv/bin/python -m pip install --no-deps -e .
    .venv/bin/python -m pip check

Run the mandatory public checks:

    .venv/bin/ruff check .
    .venv/bin/pytest

The default suite includes unit and golden tests. Three optional layers are excluded by
default: integration tests (`pytest.mark.integration`) that read the private `data/raw` export,
non-obvious regression tests (`pytest.mark.regression`) that preserve bugs already caught, and
slow tests (`pytest.mark.slow`) covering expensive forecast/web paths. Run them on request, or
on the owner's checkout before a release:

    .venv/bin/pytest -m "integration or regression or slow" --dist loadfile
    .venv/bin/pytest -m integration --dist loadfile   # private data only
    .venv/bin/pytest -m regression                    # bug-history invariants only
    .venv/bin/pytest -m slow                          # expensive core paths

The release workflow runs all optional layers before publishing.

No static type checker is configured in this repository; do not invent a mypy/pyright result.
There is no separate formatter or frontend build command.

## CI

.github/workflows/ci.yml runs on pull requests to main, pushes to main and manual dispatch. It:

1. installs requirements.lock and the project without resolving different versions;
2. runs pip check;
3. runs Ruff;
4. runs the full default unit/golden suite on Python 3.12 and a smaller smoke subset on
   Python 3.11 (optional integration, regression and slow layers excluded);
5. builds a source archive and wheel from the checked-out commit;
6. extracts the source archive and runs tools/smoke_release.py against a disposable database.

The smoke test starts the real HTTP server, checks the page and static assets, opens the
WORKOUT-GENERATION document, reads the active-workout API, saves synthetic readiness, reads it
back and builds a prescription. It does not execute JavaScript or replace a browser test.

## Versioning

The project uses semantic versioning in pyproject.toml. A release tag must be exactly
v followed by that version, for example version 1.0.0b1 -> tag v1.0.0b1. A stable release
requires bumping pyproject.toml to the stable version before tagging; the release workflow
fails if the tag and project version disagree.

## Prepare and publish a release

1. Update pyproject.toml to the release version.
2. Update CHANGELOG.md and any status text that names the current release.
3. Run the local checks above, including the private integration tests where available.
4. Commit the release preparation.
5. Create and push the matching tag:

       git tag v1.0.0b1
       git push origin v1.0.0b1

6. .github/workflows/release.yml re-runs the CI workflow against the tagged commit, runs the
   optional integration/regression layer, verifies that the tag matches pyproject.toml, builds
   the source archive and wheel from that tag, runs the smoke test, writes SHA256SUMS and only
   then publishes the GitHub Release.

Tags containing a, b or rc are published as GitHub prereleases and are not marked latest.
A stable tag such as v1.0.0 is published normally. The release job refuses to replace an
existing release. If a release run fails before a release is created, fix the cause and move
the tag deliberately; do not force-push a protected branch. If a release already exists, do
not silently overwrite its assets: publish a new version or handle the existing release
manually with an explicit decision.

## Branch protection

The default branch is protected with pull requests, the checks reported by the completed CI
run, branches up to date with main, and conversation resolution. Force pushes and deletion are
disabled. No multiple independent reviewers are required for this solo-maintained repository.

A successful CI run on commit 05f79fe (run 40881926929) reported these check-run names:

- quality (3.11)
- quality (3.12)
- package and smoke

GitHub displays them under the workflow as CI / quality (3.11), CI / quality (3.12) and
CI / package and smoke.

**Current status: enabled and verified 2026-10-29.** The main branch now requires:

- a pull request before merging;
- those three status checks, with strict up-to-date enforcement;
- conversation resolution;
- no required reviewer count, appropriate for a solo maintainer;
- no force pushes and no branch deletion;
- admin enforcement.

Release tags matching v* are also protected by an active tag ruleset: deletion and
non-fast-forward updates are blocked. Do not delete or re-point an existing release tag.

## Limitations

- Private integration tests are not available on a clean public runner.
- No type checker is configured.
- The smoke test is HTTP-level; it does not execute JavaScript or cover browser layout.
- The release workflow publishes only after checks; it does not deploy the web service.
- A stable version bump is a separate release decision.

## Related

- **Methodology:** [METHODOLOGY.md](METHODOLOGY.md)
- **Web UI:** [WEB-UI.md](WEB-UI.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
