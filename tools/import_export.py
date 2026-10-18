#!/usr/bin/env python
"""Import data/raw CSVs into the SQLite store.

Idempotent: importing the same file twice writes no duplicate rows (the identity key is the
source line, not the content). Use --db to point somewhere other than data/coach.db.

    python tools/import_export.py
    python tools/import_export.py --db /tmp/scratch.db
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strength_coach.store import db, importer  # noqa: E402
from strength_coach.utils import io_utils, paths  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None, help="database path (default: data/coach.db)")
    parser.add_argument("--training", default=None)
    parser.add_argument("--readiness", default=None)
    args = parser.parse_args(argv)

    training_path = Path(args.training) if args.training else paths.training_log_csv()
    readiness_path = Path(args.readiness) if args.readiness else paths.readiness_csv()
    for path in (training_path, readiness_path):
        if not path.exists():
            print(f"missing input: {path}")
            return 2

    training = io_utils.read_raw_csv(training_path)
    readiness = io_utils.read_raw_csv(readiness_path)

    store = db.Store(args.db)
    try:
        report = importer.import_export(
            store.connection,
            training,
            readiness,
            training_sha256=importer.sha256_file(training_path),
            readiness_sha256=importer.sha256_file(readiness_path),
        )
    finally:
        store.close()

    print(f"run {report.run_id}")
    print(f"  raw rows inserted:   {report.raw_rows_inserted}")
    print(f"  clean sets inserted: {report.clean_sets_inserted} "
          f"(already present: {report.clean_sets_existing})")
    print(f"  sessions:            {report.sessions_written}")
    print(f"  readiness days:      {report.readiness_days}")
    print(f"  quarantined rows:    {report.quarantined}")
    if report.window_start:
        print(f"  window:              {report.window_start} .. {report.window_end}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
