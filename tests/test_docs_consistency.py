"""Documentation consistency checks.

These are cross-document contracts that the UI documentation audit does not cover: it
checks the panel-to-document footer links and anchors, not links inside documents, and it
does not check that a cited decision or limitation exists, that a status or cap claim
matches the live config, or that a superseded decision is recorded.

Each check encodes a failure that actually occurred in the October 2026 documentation
audit, so a recurrence fails the fast lane instead of waiting for the next manual review.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", ".pytest_cache", "private", "node_modules", "__pycache__"}

LINK_RE = re.compile(r"\]\(([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)")
DECISION_RE = re.compile(r"DEC-[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d{2}")
LIMITATION_RE = re.compile(r"LIM-\d{2}")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "#")
TICK = chr(96)

# The public/private boundary (docs/PRIVACY.md) forbids exact single-athlete sample sizes.
# This catches the specific form the audit found; extend it when a new count is generalised.
PRIVATE_COUNT_PATTERNS = (
    re.compile(r"\b\d+\s+observed\s+returns\b", re.IGNORECASE),
    re.compile(r"\bexact\s+count\s+of\s+\d+\s+returns\b", re.IGNORECASE),
)


def _markdown_files() -> list[Path]:
    paths: list[Path] = []
    for directory, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            if name.endswith(".md"):
                paths.append(Path(directory) / name)
    return paths


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def broken_links() -> list[str]:
    problems: list[str] = []
    for path in _markdown_files():
        for match in LINK_RE.finditer(path.read_text(encoding="utf-8")):
            target = match.group(1)
            if target.startswith(EXTERNAL_PREFIXES):
                continue
            target = target.split("#", 1)[0]
            if not target:
                continue
            if target.startswith(("private/", "../private/")):
                problems.append(f"{_relative(path)} -> {target} (public doc links private data)")
                continue
            if not (path.parent / target).resolve().exists():
                problems.append(f"{_relative(path)} -> {target}")
    return problems


def dangling_ids(pattern: re.Pattern[str], known: set[str]) -> list[str]:
    problems: list[str] = []
    for path in _markdown_files():
        for token in sorted(set(pattern.findall(path.read_text(encoding="utf-8")))):
            if token not in known:
                problems.append(f"{_relative(path)}: {token}")
    return problems


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _superseded_rows(text: str) -> set[tuple[str, str]]:
    rows: set[tuple[str, str]] = set()
    for line in text.splitlines():
        if not line.startswith(f"| {TICK}DEC-"):
            continue
        cells = _table_cells(line)
        if len(cells) < 2:
            continue
        old = DECISION_RE.search(cells[0])
        new = DECISION_RE.search(cells[1])
        if old and new:
            rows.add((old.group(0), new.group(0)))
    return rows


def _decision_row_supersessions(text: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in text.splitlines():
        if not line.startswith(f"| {TICK}DEC-"):
            continue
        cells = _table_cells(line)
        if len(cells) < 2:
            continue
        old = DECISION_RE.search(cells[0])
        new = re.search(r"superseded by\s+\W*(DEC-[A-Z0-9-]+)", " | ".join(cells[1:]))
        if old and new:
            rows.append((old.group(0), new.group(1)))
    return rows


def test_relative_links_resolve() -> None:
    assert broken_links() == []


def test_decision_ids_exist() -> None:
    known = set(DECISION_RE.findall(_read("docs", "DECISIONS.md")))
    assert dangling_ids(DECISION_RE, known) == []


def test_limitation_ids_exist() -> None:
    known = set(LIMITATION_RE.findall(_read("docs", "LIMITATIONS-REGISTER.md")))
    assert dangling_ids(LIMITATION_RE, known) == []


def test_agents_map_lists_every_doc() -> None:
    mapped: set[str] = set()
    for line in _read("AGENTS.md").splitlines():
        if not line.startswith(f"| {TICK}docs/"):
            continue
        name = line.split(TICK, 2)[1]
        if name.startswith("docs/") and name.endswith(".md"):
            mapped.add(name[len("docs/"):])
    present = {path.name for path in (ROOT / "docs").glob("*.md")}
    assert sorted(present - mapped) == []


def test_status_matches_roadmap() -> None:
    roadmap = _read("ROADMAP.md")
    current = set(re.findall(r"(v\d+\.\d+)\s+beta", roadmap))
    if not current:
        current = set(re.findall(r"(v\d+\.\d+)\s+in progress", roadmap))
    assert current, "ROADMAP has no current phase"
    for name in ("README.md", "AGENTS.md"):
        text = _read(name)
        for version in sorted(current):
            assert version in text, f"{name} does not mention the current phase {version}"
            assert not re.search(rf"{re.escape(version)}\s+(?:is\s+)?next\b", text), (
                f"{name} still calls {version} 'next' while ROADMAP has it current"
            )


def test_spinal_cap_matches_w9_current_state() -> None:
    document = yaml.safe_load(_read("config", "rules", "programme.v1.yaml"))
    rule = next(item for item in document["rules"] if item["id"] == "PRG-SPINE-001")
    cap = rule["params"]["cap"]
    w9 = _read("docs", "W9-SPINAL-CAP.md")
    assert "Superseded in part" in w9
    current = w9.split("## 8. Current state", 1)[1]
    assert f"params.cap: {cap}" in current
    assert f"The cap is **{cap}**" in current


def test_no_exact_public_sample_counts() -> None:
    for path in _markdown_files():
        text = path.read_text(encoding="utf-8")
        for pattern in PRIVATE_COUNT_PATTERNS:
            assert not pattern.search(text), f"{_relative(path)}: {pattern.pattern}"


def test_superseded_decisions_are_recorded() -> None:
    decisions = _read("docs", "DECISIONS.md")
    table = _superseded_rows(decisions)
    missing = [row for row in _decision_row_supersessions(decisions) if row not in table]
    assert missing == [], f"decision rows say superseded but the table does not: {missing}"

    for line in _read("ROADMAP.md").splitlines():
        if "later superseded by" not in line:
            continue
        before, after = line.split("later superseded by", 1)
        old = DECISION_RE.findall(before)
        new = DECISION_RE.findall(after)
        if old and new:
            assert (old[-1], new[0]) in table, (
                f"ROADMAP says {old[-1]} was superseded by {new[0]}, "
                "but the Superseded table does not record it"
            )


def test_audit_closeout_has_no_undated_register_count() -> None:
    text = _read("docs", "AUDIT-CLOSEOUT.md")
    assert not re.search(r"register has \*\*\d+ entries\*\*", text, re.IGNORECASE)
