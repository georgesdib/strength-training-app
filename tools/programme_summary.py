#!/usr/bin/env python
"""Check or refresh the generated programme tables in the strength-programme review.

    python tools/programme_summary.py            # print the block
    python tools/programme_summary.py --check    # exit 1 when the document is stale
    python tools/programme_summary.py --write    # replace the marked block

The renderer lives in `strength_coach.prescribe.summary`; this file is only the command-line
wrapper, so the test and the tool cannot disagree about what "current" means.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strength_coach.prescribe import summary  # noqa: E402

DOC = Path(__file__).resolve().parents[1] / "docs" / "STRENGTH-PROGRAM-REVIEW.md"
STALE_HINT = "run: python tools/programme_summary.py --write"


def check(doc: Path = DOC) -> int:
    text = doc.read_text(encoding="utf-8")
    current = summary.extract(text)
    rendered = summary.render()
    if current == rendered:
        print("programme summary is current")
        return 0
    print(
        "\n".join(
            difflib.unified_diff(
                current.splitlines(),
                rendered.splitlines(),
                fromfile=str(doc),
                tofile="generated",
                lineterm="",
            )
        )
    )
    print(STALE_HINT)
    return 1


def write(doc: Path = DOC) -> int:
    text = doc.read_text(encoding="utf-8")
    rendered = summary.render()
    if summary.extract(text) == rendered:
        print("programme summary is already current")
        return 0
    doc.write_text(summary.replace(text, rendered), encoding="utf-8")
    print(f"updated {doc}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="fail when the document is stale")
    group.add_argument("--write", action="store_true", help="replace the marked block")
    args = parser.parse_args(argv)
    if args.check:
        return check()
    if args.write:
        return write()
    print(summary.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
