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
import subprocess
import sys
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


PROFILE_BIRTH_DATE_RE = re.compile(
    r"birth date[^\n]{0,60}\b(?:19|20)\d{2}-\d{2}-\d{2}\b", re.IGNORECASE
)
TEMP_PASSWORD_RE = re.compile(r"temporary password\s+`[^`]+`", re.IGNORECASE)


def test_public_docs_do_not_expose_profile_values() -> None:
    # A real birth date and starting password leaked into the roadmap once. Public design
    # documents must use placeholders; the exact values live only in private/ or the CLI.
    for path in ("ROADMAP.md", "AGENTS.md", "USER-GUIDE.md", "docs/WEB-UI.md", "docs/PRIVACY.md"):
        text = _read(path)
        assert not PROFILE_BIRTH_DATE_RE.search(text), path
        assert not TEMP_PASSWORD_RE.search(text), path


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


# --- documentation/source-of-truth contracts ---------------------------------

CLI_EXAMPLE_RE = re.compile(r"(?:^|\s)(?:\.venv/bin/)?strength-coach ([a-z][a-z-]*)")


def _cli_help(*args: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "strength_coach.cli", *args, "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _help_commands(text: str) -> set[str]:
    match = re.search(r"\{([a-z0-9_,-]+)\}", text)
    assert match, "CLI help has no subcommand set"
    return set(match.group(1).split(","))


def _guide_commands(text: str) -> set[str]:
    return set(CLI_EXAMPLE_RE.findall(text))


def test_documented_cli_commands_and_options_still_exist() -> None:
    help_text = _cli_help()
    available = _help_commands(help_text)
    documented = _guide_commands(_read("USER-GUIDE.md"))
    assert documented, "USER-GUIDE has no strength-coach examples"
    assert documented <= available, f"documented commands missing from the parser: {documented - available}"

    for command, options in {
        "run": ("--date", "--session-type", "--llm", "--propose"),
        "review": ("--session", "--pending"),
        "programme": ("--weeks", "--remaining"),
        "readiness": ("set", "calibrate", "shadow"),
        "block": ("--date",),
    }.items():
        command_help = _cli_help(command)
        missing = [option for option in options if option not in command_help]
        assert not missing, f"documented options missing from {command}: {missing}"


def test_cli_contract_detects_a_removed_documented_command() -> None:
    documented = _guide_commands("Run: strength-coach run\nAnd: strength-coach removed-command")
    assert documented == {"run", "removed-command"}
    assert documented - {"run"} == {"removed-command"}


def test_documented_rir_and_readiness_valve_match_config() -> None:
    rules = yaml.safe_load(_read("config", "rules", "programme.v1.yaml"))
    rule = next(item for item in rules["rules"] if item["id"] == "PRG-RIR-001")
    rir = rule["params"]["default_rir"]
    review = _read("docs", "STRENGTH-PROGRAM-REVIEW.md")
    assert f"RIR {rir['min']}–{rir['max']}" in review
    assert "RIR 2 target" in review

    readiness = yaml.safe_load(_read("config", "readiness.v1.yaml"))
    assert readiness["set_reduction"]["include_essential"] is False
    readiness_doc = _read("docs", "READINESS.md")
    assert "`include_essential` is **false**" in readiness_doc


def test_documented_exposure_default_matches_schema() -> None:
    from strength_coach.store import db

    store = db.Store(":memory:")
    try:
        columns = {
            row["name"]: row
            for row in store.connection.execute("PRAGMA table_info(athlete_profile)")
        }
    finally:
        store.close()
    assert columns["exposure_trim_enabled"]["dflt_value"] == "0"
    assert "default **off**" in _read("docs", "FATIGUE-SIGNALS.md")


def test_documented_llm_default_matches_settings() -> None:
    from strength_coach.agents.client import NullLLM
    from strength_coach.agents.config import LLMSettings, build_client

    assert LLMSettings().provider == "null"
    assert isinstance(build_client(LLMSettings()), NullLLM)
    assert "NullLLM" in _read("README.md")
