#!/usr/bin/env python
"""One-pass consistency check for the exercise catalogue fan-out.

    python tools/catalogue.py            # check; exit 1 with the exact file and key to add
    python tools/catalogue.py --write    # regenerate the mechanical parts, then check

An exercise id lives in a dozen places. Judgment stays hand-authored (identity, template
slots and set/rep scheme, selection-tax ordinals, candidate pools and their order, load-basis
groups, inference lists, demand claims and evidence). Only two artifacts are mechanical and
therefore generated here:

  * the stimulus ratings in config/resolver-role-quality.v1.yaml, which the rubric defines as a
    function of the demand's local-muscular level and the taxonomy's compound flag;
  * the coverage block in docs/EXERCISE-DEMANDS.md.

Everything else is still checked: a new id fails this tool with the file and the key it is
missing, instead of failing a golden test three steps later.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strength_coach.features import demands as demands_feature  # noqa: E402
from strength_coach.prescribe.demand_scope import reachable_ids  # noqa: E402
from strength_coach.utils import exercises  # noqa: E402

TAX = "config/selection-tax.v1.yaml"
ROLE = "config/resolver-role-quality.v1.yaml"
VARIANTS = "config/variants.v1.yaml"
INFERENCE = "config/templates/inference.v1.yaml"
COMPARABILITY = "config/selection-comparability.v1.yaml"
EXCEPTIONS = "config/catalogue-exceptions.yaml"
DEMANDS_DOC = "docs/EXERCISE-DEMANDS.md"
BEGIN = "<!-- BEGIN GENERATED DEMAND COVERAGE -->"
END = "<!-- END GENERATED DEMAND COVERAGE -->"
RATINGS_LINE = re.compile(r"^  ratings:\s*$")
RATING_ENTRY = re.compile(r"^    ([a-z0-9_]+):\s*(\d+)\s*$")


def _load(relative: str) -> dict:
    return yaml.safe_load((ROOT / relative).read_text(encoding="utf-8")) or {}


def _shipped_demands() -> demands_feature.DemandCatalogue:
    """The reviewed catalogue only: the git-ignored local overlay must not reach the docs."""
    return demands_feature.load(overlay=ROOT / "config" / "exercises" / ".no-overlay.yaml")


def _compound(entity: dict) -> bool:
    return bool(entity.get("primary_compound") or entity.get("main_lift"))


def derived_ratings() -> dict[str, int]:
    """Rubric: 3 = high local stimulus and compound; 2 = high and not compound, or moderate and
    compound; 1 = moderate and not compound, or low. Unknown demand means no rating at all."""
    catalogue = _shipped_demands()
    entities = exercises.taxonomy().entities
    out: dict[str, int] = {}
    for exercise_id in reachable_ids():
        level = catalogue.level(exercise_id, "local_muscular")
        compound = _compound(entities.get(exercise_id, {}))
        if level == "high":
            out[exercise_id] = 3 if compound else 2
        elif level == "moderate":
            out[exercise_id] = 2 if compound else 1
        elif level == "low":
            out[exercise_id] = 1
    return dict(sorted(out.items()))


def _referenced_ids() -> list[tuple[str, str, str]]:
    """(file, key, id) for every id a hand-authored list names."""
    out: list[tuple[str, str, str]] = []
    variants = _load(VARIANTS)
    for session_type, slots in (variants.get("slots") or {}).items():
        for slot, candidates in (slots or {}).items():
            for exercise_id in candidates or ():
                out.append((VARIANTS, f"slots.{session_type}.{slot}", str(exercise_id)))
    for key, values in _load(INFERENCE).items():
        if isinstance(values, list):
            for exercise_id in values:
                out.append((INFERENCE, key, str(exercise_id)))
    for basis, values in (_load(COMPARABILITY).get("load_basis") or {}).items():
        for exercise_id in values or ():
            out.append((COMPARABILITY, f"load_basis.{basis}", str(exercise_id)))
    return out


def _exceptions() -> tuple[dict[str, str], dict[str, str]]:
    raw = _load(EXCEPTIONS)
    def as_map(key: str) -> dict[str, str]:
        return {str(k): str(v) for k, v in (raw.get(key) or {}).items()}
    return as_map("unreachable_rated"), as_map("missing_tax")


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

    # 2. Every id a hand-authored list names must exist.
    for relative, key, exercise_id in _referenced_ids():
        if exercise_id not in entities:
            found.append(f"{relative}: {key} names unknown exercise {exercise_id!r}")

    # 3. Every reachable id needs selection-tax metadata; the axes are judgment, so the tool can
    #    only say which key is missing. A recorded exception is allowed and must stay truthful.
    tax = _load(TAX).get("exercises") or {}
    for exercise_id in reachable_ids():
        entry = tax.get(exercise_id)
        if not entry:
            if exercise_id not in missing_tax_ok:
                found.append(
                    f"{TAX}: add {exercise_id} with axial/systemic/skill/rom (1-3), or record the "
                    f"gap in {EXCEPTIONS}"
                )
            continue
        missing = [axis for axis in ("axial", "systemic", "skill", "rom") if axis not in entry]
        if missing:
            found.append(f"{TAX}: {exercise_id} is missing {', '.join(missing)}")
    for exercise_id, reason in sorted(missing_tax_ok.items()):
        if tax.get(exercise_id):
            found.append(
                f"{EXCEPTIONS}: missing_tax.{exercise_id} is stale, {TAX} rates it now "
                f"({reason})"
            )

    # 4. The stimulus ratings are generated: report drift, not a missing manual entry.
    reachable = set(reachable_ids())
    expected = derived_ratings()
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

    # 5. Rated demand claims must stay inside the reachable set; an unreachable rating is a
    #    claim about a lift the programme cannot select.
    catalogue = _shipped_demands()
    for exercise_id in sorted(catalogue.claims):
        if exercise_id not in reachable and exercise_id not in unreachable_ok:
            found.append(
                f"config/exercises/demands.v1.yaml: {exercise_id} is rated but not reachable "
                "(add it to a template slot or a candidate pool, record it in "
                f"{EXCEPTIONS}, or drop the rating)"
            )
    for exercise_id, reason in sorted(unreachable_ok.items()):
        if exercise_id in reachable:
            found.append(
                f"{EXCEPTIONS}: unreachable_rated.{exercise_id} is stale, the id is reachable "
                f"now ({reason})"
            )

    # 6. The generated coverage block must match the catalogue.
    current = _coverage_block()
    documented = _documented_block()
    if documented is None:
        found.append(f"{DEMANDS_DOC}: missing BEGIN/END markers for the generated coverage block")
    elif documented.strip() != current.strip():
        found.append(f"{DEMANDS_DOC}: generated coverage block is stale (run --write)")
    return found


def _coverage_block() -> str:
    catalogue = _shipped_demands()
    ids = reachable_ids()
    coverage = catalogue.coverage(ids)
    rated = coverage["rated_exercises"]
    lines = [
        BEGIN,
        "<!-- generated by tools/catalogue.py --write; do not hand-edit -->",
        "",
        f"Reachable ids: **{coverage['total']}** · rated on at least one dimension: **{rated}** "
        f"({100 * rated / coverage['total']:.1f} %) · reviewed {coverage['reviewed_on'] or 'never'} "
        f"· digest {coverage['digest'] or 'none'}",
        "",
        "| dimension | rated | unknown | unknown rate | supported | provisional |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for dimension, row in coverage["per_dimension"].items():
        lines.append(
            f"| {dimension} | {row['rated']} | {row['unknown']} | "
            f"{100 * row['unknown_rate']:.1f} % | {row['supported']} | {row['provisional']} |"
        )
    lines.extend(["", END])
    return "\n".join(lines)


def _documented_block() -> str | None:
    text = (ROOT / DEMANDS_DOC).read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        return None
    return text[text.index(BEGIN): text.index(END) + len(END)]


def _replace_ratings(text: str, ratings: dict[str, int]) -> str:
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines) if RATINGS_LINE.match(line)), None)
    if start is None:
        raise SystemExit(f"{ROLE}: could not find the ratings block")
    stop = start + 1
    while stop < len(lines) and RATING_ENTRY.match(lines[stop]):
        stop += 1
    block = [f"    {exercise_id}: {rating}" for exercise_id, rating in ratings.items()]
    return "\n".join(lines[: start + 1] + block + lines[stop:]) + "\n"


def _update(path: Path, new_text: str, label: str) -> bool:
    old_text = path.read_text(encoding="utf-8")
    if old_text == new_text:
        print(f"{label} is already current")
        return False
    path.write_text(new_text, encoding="utf-8")
    print(f"updated {label}")
    return True


def write() -> None:
    ratings = derived_ratings()
    role_path = ROOT / ROLE
    _update(role_path, _replace_ratings(role_path.read_text(encoding="utf-8"), ratings),
            f"{ROLE} stimulus ratings ({len(ratings)})")
    doc_path = ROOT / DEMANDS_DOC
    text = doc_path.read_text(encoding="utf-8")
    if not (BEGIN in text and END in text):
        raise SystemExit(f"{DEMANDS_DOC}: add the BEGIN/END markers where coverage belongs")
    start = text.index(BEGIN)
    stop = text.index(END) + len(END)
    _update(doc_path, text[:start] + _coverage_block() + text[stop:],
            f"{DEMANDS_DOC} coverage block")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="regenerate the mechanical parts")
    args = parser.parse_args(argv)
    if args.write:
        write()
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
