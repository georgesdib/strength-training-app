#!/usr/bin/env python
"""Narrow test lanes: the default way to check a change.

    python tools/check.py                 # fast: tests mapped from the files changed vs HEAD
    python tools/check.py --files tests/test_exercises.py
    python tools/check.py fast --files strength_coach/features/demands.py
    python tools/check.py lint            # ruff on changed files
    python tools/check.py docs            # regenerate generated doc blocks, then check them
    python tools/check.py full            # exactly what CI runs (markers + ios-workflow ignore)
    python tools/check.py install-hook    # optional pre-push hook running the fast lane

Why this exists: the default pytest selection is ~2,500 tests and takes ~11 minutes, so running
it for every edit is both slow and unnecessary. The fast lane maps a changed path to the tests
that actually cover it. Run `full` once before a push (or let CI do it); never run it in a loop.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKERS = "not integration and not slow"
CI_IGNORE = ("tests/test_ios_workflow.py",)  # CI excludes it: xdist makes its servers flaky

# A changed path matches every test file listed for the area it falls in. Per-file mapping
# (`strength_coach/features/x.py` -> `tests/test_x.py`, `tests/test_y.py` -> itself) is applied
# first, so this table only needs the cross-cutting areas.
AREA_TESTS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("config/exercises/", "config/selection-tax", "config/resolver-role-quality",
         "config/variants.", "config/template-resolver"),
        ("tests/test_exercises.py", "tests/test_demands.py", "tests/test_selection.py",
         "tests/test_role_quality.py", "tests/test_resolver_role_quality_config.py",
         "tests/test_fatigue_selection.py", "tests/test_exercise_catalogue.py"),
    ),
    (
        ("config/templates/", "config/rules/"),
        ("tests/test_generator.py", "tests/test_prescribe.py", "tests/test_resolver_policy.py",
         "tests/test_rules_policy.py", "tests/test_programme_summary.py",
         "tests/test_workout_generation_doc.py"),
    ),
    (("docs/",), ("tests/test_docs_consistency.py", "tests/test_ui_docs.py",
                  "tests/test_docs_manifest.py")),
    (("strength_coach/store/",), ("tests/test_store.py",)),
    (("strength_coach/web/",), ("tests/test_web.py", "tests/test_reviews_api.py")),
    (("strength_coach/prescribe/",), ("tests/test_prescribe.py", "tests/test_generator.py",
                                      "tests/test_resolver_policy.py")),
    (("strength_coach/features/",), ("tests/test_demands.py", "tests/test_volume.py",
                                     "tests/test_fatigue_selection.py")),
)

# Nothing changed (or no mapping applied): a small cross-cutting smoke set, not the full suite.
DEFAULT_TESTS = (
    "tests/test_exercises.py",
    "tests/test_demands.py",
    "tests/test_docs_consistency.py",
    "tests/test_programme_summary.py",
)


def _run(args: list[str], *, what: str) -> int:
    print(f"$ {' '.join(args)}", flush=True)
    completed = subprocess.run(args, cwd=ROOT)
    if completed.returncode != 0:
        print(f"FAILED: {what}", file=sys.stderr)
    return completed.returncode


def _python() -> str:
    return sys.executable


def _changed_paths() -> list[str]:
    """Tracked modifications plus untracked files, relative to HEAD."""
    out: list[str] = []
    for args in (["git", "diff", "--name-only", "HEAD"],
                 ["git", "ls-files", "--others", "--exclude-standard"]):
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True)
        out.extend(line.strip() for line in result.stdout.splitlines() if line.strip())
    return sorted(set(out))


def _exists(relative: str) -> bool:
    return (ROOT / relative).is_file()


def tests_for(paths: list[str]) -> list[str]:
    """Test files covering the changed paths, in a stable order."""
    chosen: list[str] = []

    def add(name: str) -> None:
        if _exists(name) and name not in chosen:
            chosen.append(name)

    for path in paths:
        if path.startswith("tests/") and path.endswith(".py"):
            add(path)
            continue
        stem = Path(path).stem
        add(f"tests/test_{stem}.py")
        for prefixes, names in AREA_TESTS:
            if path.startswith(prefixes):
                for name in names:
                    add(name)
    if not chosen:
        for name in DEFAULT_TESTS:
            add(name)
    return chosen


def _py_files(paths: list[str]) -> list[str]:
    return [p for p in paths if p.endswith(".py") and _exists(p)]


def lane_fast(files: list[str]) -> int:
    paths = files or _changed_paths()
    if not paths:
        print("No changed files; running the default smoke set.")
    lint = _py_files(paths)
    if lint:
        code = _run([_python(), "-m", "ruff", "check", *lint], what="ruff")
        if code != 0:
            return code
    tests = tests_for(paths)
    if not tests:
        print("No tests mapped; nothing to run.", file=sys.stderr)
        return 1
    print(f"fast lane: {len(tests)} test file(s) for {len(paths)} changed path(s)")
    return _run([_python(), "-m", "pytest", *tests, "-q"], what="fast lane")


def lane_full() -> int:
    code = _run([_python(), "-m", "ruff", "check", "."], what="ruff")
    if code != 0:
        return code
    args = [_python(), "-m", "pytest", "-m", MARKERS, "--ignore=" + CI_IGNORE[0]]
    return _run(args, what="CI selection")


def lane_lint(files: list[str]) -> int:
    paths = files or _changed_paths()
    lint = _py_files(paths) or ["."]
    return _run([_python(), "-m", "ruff", "check", *lint], what="ruff")


def lane_docs() -> int:
    generators = (
        ["tools/programme_summary.py", "--write"],
        ["tools/workout_generation_example.py", "--write"],
        ["tools/catalogue.py", "--write-docs"],
    )
    for generator in generators:
        if not _exists(generator[0]):
            continue
        code = _run([_python(), *generator], what=generator[0])
        if code != 0:
            return code
    return _run([_python(), "-m", "pytest", "tests/test_docs_consistency.py",
                 "tests/test_ui_docs.py", "tests/test_docs_manifest.py",
                 "tests/test_programme_summary.py", "tests/test_workout_generation_doc.py", "-q"],
                what="docs tests")


HOOK = """#!/bin/sh
# Installed by `make hook`. Fast lane only: a push should not cost eleven minutes.
set -e
cd "$(git rev-parse --show-toplevel)"
exec python tools/check.py
"""


def install_hook() -> int:
    hook = ROOT / ".git" / "hooks" / "pre-push"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(HOOK, encoding="utf-8")
    hook.chmod(0o755)
    print(f"installed {hook.relative_to(ROOT)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("lane", nargs="?", choices=("fast", "lint", "docs", "full", "install-hook"),
                        default="fast")
    parser.add_argument("--files", nargs="*", default=[], help="paths to treat as changed")
    args = parser.parse_args(argv)
    if args.lane == "full":
        return lane_full()
    if args.lane == "docs":
        return lane_docs()
    if args.lane == "lint":
        return lane_lint(args.files)
    if args.lane == "install-hook":
        return install_hook()
    return lane_fast(args.files)


if __name__ == "__main__":
    raise SystemExit(main())
