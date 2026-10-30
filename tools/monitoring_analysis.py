#!/usr/bin/env python
"""CLI wrapper for the reusable monitoring analysis service.

The core computation lives in strength_coach.features.monitoring_analysis; this file only
handles arguments, a read-only connection and private output.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strength_coach.features import monitoring_analysis as analysis  # noqa: E402
from strength_coach.utils import paths  # noqa: E402

DEFAULT_OUT = "private/docs/MONITORING-ANALYSIS.md"


def connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"database does not exist: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(paths.data_dir("coach.db")))
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args(argv)
    as_of = args.as_of or datetime.date.today().isoformat()
    try:
        conn = connect_readonly(args.db)
        try:
            report = analysis.build_analysis(conn, as_of=as_of, db_path=args.db)
        finally:
            conn.close()
    except (FileNotFoundError, sqlite3.DatabaseError) as exc:
        print(f"analysis error: {exc}", file=sys.stderr)
        return 2
    text = (
        json.dumps(report, indent=2, sort_keys=True)
        if args.format == "json" else analysis.render_markdown(report)
    ) + "\n"
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
