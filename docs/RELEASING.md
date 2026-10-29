# RELEASING AND CI

**Status:** CI and release gates are implemented in the repository. No stable release tag has
been published by this work.

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
    .venv/bin/pytest -m "not integration"

The public suite includes unit and golden tests. Integration tests are marked
pytest.mark.integration and are not committed because they read the private data/raw export;
run them locally on the owner's checkout with:

    .venv/bin/pytest -m integration

No static type checker is configured in this repository; do not invent a mypy/pyright result.
There is no separate formatter or frontend build command.

## CI

.github/workflows/ci.yml runs on pull requests to main, pushes to main and manual dispatch. It:

1. installs requirements.lock and the project without resolving different versions;
2. runs pip check;
3. runs Ruff;
4. runs the public unit/golden suite on Python 3.11 and 3.12;
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

6. .github/workflows/release.yml re-runs the CI workflow against the tagged commit, verifies
   that the tag matches pyproject.toml, builds the source archive and wheel from that tag,
   runs the smoke test, writes SHA256SUMS and only then publishes the GitHub Release.

The release job refuses to replace an existing release. If a release run fails before a
release is created, fix the cause and move the tag deliberately; do not force-push a protected
branch. If a release already exists, do not silently overwrite its assets: publish a new
version or handle the existing release manually with an explicit decision.

## Branch protection

The default branch should require pull requests, the checks reported by the completed CI run,
branches to be up to date with main, and conversation resolution. Disable force pushes and
deletion. Do not require multiple independent reviewers for this solo-maintained repository.

The check names are the exact names reported by GitHub after the first successful CI run. On
the current workflow they are expected to be:

- CI / quality (3.11)
- CI / quality (3.12)
- CI / package and smoke

These names must be verified in the repository's Actions run before saving branch protection;
do not guess if GitHub reports a different display name.

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
