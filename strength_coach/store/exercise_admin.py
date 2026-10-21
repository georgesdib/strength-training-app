"""Read and edit the exercise catalogue without rewriting the commented taxonomy.

The UI writes a small override file (`config/exercises/overrides.v1.yaml`); `Taxonomy.load`
merges it over the checked-in base. Ids are immutable because changing one would orphan the
history that was just canonicalised under it.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

import yaml

from strength_coach.utils import exercises, paths

ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SKIP = {"id"}


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _override_doc() -> dict:
    raw = _read(paths.exercise_overrides_yaml())
    raw.setdefault("schema_version", "1.0.0")
    raw.setdefault("entities", {})
    return raw


def _as_list(value: Any, field: str) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, str):
        return [part.strip() for part in value.replace(",", "\n").splitlines() if part.strip()]
    raise ValueError(f"{field} must be a list")


def _normalise(entity_id: str, props: Mapping[str, Any], current: Mapping[str, Any]) -> dict:
    if not ID_RE.match(entity_id):
        raise ValueError("id must be lower_snake_case, start with a letter, and contain only a-z, 0-9, _")
    if not isinstance(props, Mapping):
        raise ValueError("properties must be an object")

    merged = dict(current)
    for key, value in props.items():
        if key in _SKIP:
            if str(value) != entity_id:
                raise ValueError("an exercise id cannot be changed")
            continue
        merged[str(key)] = value

    display = str(merged.get("display") or "").strip()
    if not display:
        raise ValueError("display is required")
    merged["display"] = display

    log_names = []
    for name in _as_list(merged.get("log_names"), "log_names"):
        text = str(name)
        if text and text not in log_names:
            log_names.append(text)
    if not log_names:
        raise ValueError("at least one log name is required")
    merged["log_names"] = log_names

    pattern = str(merged.get("pattern") or "").strip()
    if not pattern:
        raise ValueError("pattern is required")
    merged["pattern"] = pattern

    muscles = [str(m).strip() for m in _as_list(merged.get("primary_muscles"), "primary_muscles")]
    merged["primary_muscles"] = [m for m in muscles if m]

    for key in (
        "primary_compound", "loadable", "bodyweight_type", "time_based",
        "e1rm_applicable", "main_lift", "high_fatigue_spinal", "erector_family",
        "direct_erector", "counts_toward_back_extension_dose",
        "substitutable_for_back_extension",
    ):
        if key in merged and not isinstance(merged[key], bool):
            merged[key] = str(merged[key]).lower() in {"1", "true", "yes", "on"}

    return merged


def _collision(entity_id: str, log_names: list[str], merged_entities: Mapping[str, Any]) -> str | None:
    wanted = {str(n) for n in log_names}
    for other_id, entity in merged_entities.items():
        if str(other_id) == entity_id:
            continue
        for name in entity.get("log_names") or []:
            if str(name) in wanted:
                return f"log name {name!r} already belongs to {other_id}"
    return None


def catalog() -> dict[str, Any]:
    """Every entity, its source (base/override) and the full property mapping."""
    base = _read(paths.taxonomy_yaml()).get("entities") or {}
    overrides = _override_doc().get("entities") or {}
    entities: dict[str, dict] = {}
    sources: dict[str, str] = {}
    for entity_id, entity in base.items():
        entities[str(entity_id)] = dict(entity)
        sources[str(entity_id)] = "base"
    for entity_id, patch in overrides.items():
        merged = dict(entities.get(str(entity_id), {}))
        merged.update(dict(patch or {}))
        entities[str(entity_id)] = merged
        sources[str(entity_id)] = "override" if str(entity_id) in base else "new"
    rows = []
    for entity_id in sorted(entities):
        entity = entities[entity_id]
        rows.append({
            "id": entity_id,
            "display": str(entity.get("display") or entity_id),
            "pattern": entity.get("pattern"),
            "source": sources[entity_id],
            "props": entity,
        })
    return {
        "patterns": sorted({str(e.get("pattern")) for e in entities.values() if e.get("pattern")}),
        "entities": rows,
    }


def save(entity_id: str, props: Mapping[str, Any]) -> dict[str, Any]:
    """Create/update one entity in the override file. Ids are immutable."""
    entity_id = str(entity_id).strip()
    base = _read(paths.taxonomy_yaml()).get("entities") or {}
    doc = _override_doc()
    overrides = doc.setdefault("entities", {})

    current = dict(base.get(entity_id, {}))
    current.update(dict(overrides.get(entity_id, {})))
    merged = _normalise(entity_id, props, current)

    check_entities = {str(k): dict(v) for k, v in base.items()}
    for other_id, patch in overrides.items():
        target = dict(check_entities.get(str(other_id), {}))
        target.update(dict(patch or {}))
        check_entities[str(other_id)] = target
    collision = _collision(entity_id, merged["log_names"], check_entities)
    if collision:
        raise ValueError(collision)

    overrides[entity_id] = merged
    path = paths.exercise_overrides_yaml()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        "# Exercise catalogue overrides written by the local UI (Exercises tab).\n"
        "# `log_names` are exact strings; ids are immutable.\n\n"
        + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    )
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    exercises.taxonomy.cache_clear()
    return catalog()
