#!/usr/bin/env python
"""Score the segmentation against a labelled fixture set.

The detector was being tuned one file at a time, which is how you get a rule that works on the
last file you looked at. This turns "does it work" into a repeatable check: a manifest names each
recording and the rep count it must produce.

    python tools/motion_fixture_check.py --manifest ~/Desktop/motion/expected.json

Manifest format (keep it outside the repository — it names personal recordings):

    {"fixtures": [
      {"file": "motion-...-squat-set13.json", "reps": 3},
      {"file": "motion-...-Bench-pause-set14.json", "reps": 3, "axis": "vertical"}
    ]}

Exit code is 1 when any fixture disagrees, so it can gate a change.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.motion_segmentation import analyse, load_recording  # noqa: E402


def check(manifest_path: Path) -> list[dict]:
    manifest = json.loads(manifest_path.read_text())
    results = []
    for fixture in manifest.get("fixtures") or []:
        path = (manifest_path.parent / fixture["file"]).resolve()
        recording = load_recording(path)
        if fixture.get("axis"):
            recording = {
                **recording,
                "context": {**(recording.get("context") or {}), "axis": fixture["axis"]},
            }
        analysis = analyse(recording)
        found = len(analysis.reps)
        expected = int(fixture["reps"])
        results.append(
            {
                "file": fixture["file"],
                "expected": expected,
                "found": found,
                "abstention": analysis.abstention,
                "salvaged": analysis.salvaged,
                "ok": analysis.abstention is None and found == expected,
            }
        )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)

    results = check(args.manifest)
    if not results:
        print("manifest has no fixtures")
        return 2
    width = max(len(result["file"]) for result in results)
    for result in results:
        verdict = "ok  " if result["ok"] else "FAIL"
        detail = result["abstention"] or f"{result['found']} reps"
        salvaged = " (salvaged)" if result["salvaged"] else ""
        print(
            f"{verdict} {result['file']:<{width}}  expected {result['expected']}, "
            f"found {detail}{salvaged}"
        )
    failed = sum(1 for result in results if not result["ok"])
    print(f"\n{len(results) - failed}/{len(results)} fixtures agree")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
