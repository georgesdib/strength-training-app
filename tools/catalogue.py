#!/usr/bin/env python
"""Semantic checks across the exercise-catalogue fan-out.

    python tools/catalogue.py            # check; names the file and key for every gap
    python tools/catalogue.py --write    # regenerate the generated parts (see build_catalogue)

Generated files are owned by tools/build_catalogue.py; this tool checks what cannot be
generated: log-name uniqueness, ids named by hand-authored lists, demand claims outside the
reachable set, the generated files themselves, and the recorded exceptions.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import build_catalogue  # noqa: E402

from strength_coach.features import demands as demands_feature  # noqa: E402
from strength_coach.prescribe.demand_scope import reachable_ids  # noqa: E402
from strength_coach.utils import exercises  # noqa: E402

SOURCE = build_catalogue.SOURCE
ROLE = build_catalogue.ROLE
EXCEPTIONS = "config/catalogue-exceptions.yaml"


def _load(relative: str) -> dict:
    return yaml.safe_load((ROOT / relative).read_text(encoding="utf-8")) or {}


def _shipped_demands() -> demands_feature.DemandCatalogue:
    return demands_feature.load(overlay=ROOT / "config" / "exercises" / ".no-overlay.yaml")


def _exceptions() -> tuple[dict[str, str], dict[str, str]]:
    raw = _load(EXCEPTIONS)

    def as_map(key: str) -> dict[str, str]:
        return {str(k): str(v) for k, v in (raw.get(key) or {}).items()}

    return as_map("unreachable_rated"), as_map("missing_tax")


def _referenced_ids() -> list[tuple[str, str, str]]:
    """(file, key, id) for every id a hand-authored list names."""
    out: list[tuple[str, str, str]] = []
    for session_type, slots in (_load("config/variants.v1.yaml").get("slots") or {}).items():
        for slot, candidates in (slots or {}).items():
            for exercise_id in candidates or ():
                out.append(("config/variants.v1.yaml", f"slots.{session_type}.{slot}",
                            str(exercise_id)))
    for key, values in _load("config/templates/inference.v1.yaml").items():
        if isinstance(values, list):
            for exercise_id in values:
                out.append(("config/templates/inference.v1.yaml", key, str(exercise_id)))
    for basis, values in (_load("config/selection-comparability.v1.yaml").get("load_basis") or {}).items():
        for exercise_id in values or ():
            out.append(("config/selection-comparability.v1.yaml", f"load_basis.{basis}",
                        str(exercise_id)))
    return out


def problems() -> list[str]:
    """Human-readable drift, each naming the file and the exact key to add or fix."""
    found: list[str] = []
    entities = exercises.taxonomy().entities
    unreachable_ok, missing_tax_ok = _exceptions()

    # 1. A log name must resolve to exactly one entity; a split that forgets to remove the old
    #    name is invisible until a raw log file arrives.
    seen: dict[str, str] = {}
    for exercise_id, entity in entities.items():
        for name in entity.get("log_names") or ():
            key = str(name).strip().lower()
            if key in seen and seen[key] != exercise_id:
                found.append(
                    f"config/exercises/taxonomy.v1.yaml: log name {name!r} is claimed by both "
                    f"{seen[key]} and {exercise_id}"
                )
            seen.setdefault(key, exercise_id)

    # 2. Every id a generated list names must exist (catches a rename that missed the source).
    for relative, key, exercise_id in _referenced_ids():
        if exercise_id not in entities:
            found.append(f"{relative}: {key} names unknown exercise {exercise_id!r}")

    # 3. Every reachable id needs a tax entry in the source; the axes are judgment, so the tool
    #    names the key instead of inventing values.
    tax = (build_catalogue.source().get("tax") or {})
    for exercise_id in reachable_ids():
        entry = tax.get(exercise_id)
        if not entry:
            if exercise_id not in missing_tax_ok:
                found.append(
                    f"{SOURCE}: add tax.{exercise_id} with axial/systemic/skill/rom (1-3), or "
                    f"record the gap in {EXCEPTIONS}"
                )
            continue
        missing = [axis for axis in ("axial", "systemic", "skill", "rom") if axis not in entry]
        if missing:
            found.append(f"{SOURCE}: tax.{exercise_id} is missing {', '.join(missing)}")
    for exercise_id, reason in sorted(missing_tax_ok.items()):
        if tax.get(exercise_id):
            found.append(
                f"{EXCEPTIONS}: missing_tax.{exercise_id} is stale, the source rates it now "
                f"({reason})"
            )

    # 4. The generated ratings must follow the rubric for every reachable id.
    reachable = set(reachable_ids())
    expected = build_catalogue.derived_ratings()
    actual = ((_load(ROLE).get("stimulus") or {}).get("ratings") or {})
    actual = {str(k): int(v) for k, v in actual.items() if isinstance(v, int)}
    for exercise_id in sorted(set(expected) | (set(actual) & reachable)):
        want, have = expected.get(exercise_id), actual.get(exercise_id)
        if want != have:
            found.append(f"{ROLE}: stimulus.ratings.{exercise_id} is {have!r}, rubric says {want!r}")
    for exercise_id in sorted(set(actual) - reachable - set(unreachable_ok)):
        found.append(
            f"{ROLE}: stimulus.ratings.{exercise_id} belongs to an id the programme cannot "
            f"select; remove it or record it in {EXCEPTIONS}"
        )

    # 5. Rated demand claims must stay inside the reachable set.
    catalogue = _shipped_demands()
    for exercise_id in sorted(catalogue.claims):
        if exercise_id not in reachable and exercise_id not in unreachable_ok:
            found.append(
                f"config/exercises/demands.v1.yaml: {exercise_id} is rated but not reachable "
                f"(add it to a template slot or a pool, record it in {EXCEPTIONS}, or drop the "
                "rating)"
            )
    for exercise_id, reason in sorted(unreachable_ok.items()):
        if exercise_id in reachable:
            found.append(
                f"{EXCEPTIONS}: unreachable_rated.{exercise_id} is stale, the id is reachable "
                f"now ({reason})"
            )

    # 6. Generated files must match the source.
    found.extend(build_catalogue.check())
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="regenerate the generated parts")
    args = parser.parse_args(argv)
    if args.write:
        build_catalogue.write()
    found = problems()
    for line in found:
        print(line)
    if found:
        print(f"\n{len(found)} catalogue problem(s); --write fixes generated drift only.")
        return 1
    print("catalogue consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
