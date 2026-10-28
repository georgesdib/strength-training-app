"""Append-only shadow recording for reactive signals (DEC-SHADOW-01).

Called only when a prescription is persisted, never from a forecast build: a 26-week programme
would otherwise write hundreds of rows for days that never happened. The row records what the
signal saw and what it would have done, including when the answer was "nothing".
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from strength_coach.features import demands as demands_feature
from strength_coach.features import exposure as exposure_feature
from strength_coach.prescribe import fatigue_selection, templates
from strength_coach.store import repositories
from strength_coach.utils import paths


def _config_digest() -> str:
    source = paths.exposure_yaml()
    if not source.is_file():
        return ""
    return hashlib.sha256(source.read_bytes()).hexdigest()[:16]


def _exposure_signal(report: exposure_feature.ExposureReport) -> dict[str, Any]:
    return {
        "signal": report.signal,
        "ratio": None if report.ratio is None else round(report.ratio, 3),
        "acute_hard_sets": report.acute_hard_sets,
        "chronic_hard_sets": report.chronic_hard_sets,
        "coverage": round(report.coverage, 3),
        "sessions": report.sessions,
        "abstain": list(report.abstain),
        "groups": [
            {"group": group.group,
             "ratio": None if group.ratio is None else round(group.ratio, 3),
             "signal": group.signal}
            for group in report.groups if group.signal != "unknown"
        ],
    }


def record(
    conn,
    prescription_id: str,
    *,
    for_date: str,
    session_type: str,
    notes: Mapping[str, Any] | None,
) -> list[str]:
    """Write the exposure and substitution rows for one persisted prescription."""
    if not notes or "exposure_trim" not in notes:
        return []
    trim = notes.get("exposure_trim") or {}
    report = exposure_feature.compute(conn, for_date)
    applied = bool(trim.get("applied"))
    trimmed = list(trim.get("trimmed") or ())
    if applied:
        action, reason = "trim_sets", "trim applied: " + ", ".join(trimmed)
        proposed: dict[str, Any] = {"trimmed": trimmed}
    elif report.signal == "high":
        action, reason = "none", "high signal; trim is disabled, so nothing changed"
        proposed = {
            "would_trim": True,
            "high_groups": [group.group for group in report.groups if group.signal == "high"],
        }
    else:
        action = "none"
        reason = f"signal {report.signal}; nothing changed"
        proposed = {}

    ids = [repositories.append_shadow_decision(
        conn,
        evaluated_on=for_date,
        component="exposure",
        rule_id="MOD-EXP-001",
        signal=_exposure_signal(report),
        proposed=proposed,
        reason=reason,
        action=action,
        applied=applied,
        config_digest=_config_digest(),
        prescription_id=prescription_id,
    )]

    # Part C only runs when there is an active signal; otherwise the decision is "no trigger",
    # recorded without paying for a full selection ranking.
    if report.signal == "high" and not report.abstain and session_type in templates.SESSION_TYPES:
        suggestion = fatigue_selection.suggest(
            conn, for_date, session_type, exposure_report=report
        )
        catalogue = demands_feature.load()
        if suggestion.suggestions:
            item = suggestion.suggestions[0]
            ids.append(repositories.append_shadow_decision(
                conn,
                evaluated_on=for_date,
                component="substitution",
                rule_id="MOD-SELECT-001",
                signal={"signal": report.signal, "ratio": report.ratio},
                proposed=item.as_dict(),
                reason=item.reason,
                action="suggest_substitution",
                applied=False,
                catalogue_digest=catalogue.digest,
                prescription_id=prescription_id,
            ))
        else:
            ids.append(repositories.append_shadow_decision(
                conn,
                evaluated_on=for_date,
                component="substitution",
                rule_id="MOD-SELECT-001",
                signal={"signal": report.signal, "ratio": report.ratio},
                proposed={},
                reason="; ".join(suggestion.abstentions) or "no candidate",
                action="none",
                applied=False,
                catalogue_digest=catalogue.digest,
                prescription_id=prescription_id,
            ))
    else:
        ids.append(repositories.append_shadow_decision(
            conn,
            evaluated_on=for_date,
            component="substitution",
            rule_id="MOD-SELECT-001",
            signal={"signal": report.signal, "ratio": report.ratio},
            proposed={},
            reason=(
                "no active exposure signal" if report.signal != "high"
                else "high signal, but this session type has no substitution stage"
            ),
            action="none",
            applied=False,
            prescription_id=prescription_id,
        ))
    return ids


def record_prescription(conn, prescription_id: str, prescription) -> list[str]:
    """CLI path: the engine object carries the same notes as the UI plan."""
    return record(
        conn, prescription_id,
        for_date=str(prescription.for_date),
        session_type=str(prescription.session_type),
        notes=getattr(prescription, "notes", None),
    )
