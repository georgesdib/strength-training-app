"""Repository metadata for knowledge citations."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceState:
    commit: str
    dirty: bool


def git_state(root: Path) -> SourceState:
    """Return HEAD and dirty state without a shell; absent Git is not an error."""
    try:
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return SourceState("unknown", True)
    return SourceState(commit or "unknown", bool(status))
