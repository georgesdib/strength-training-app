"""7a settings registry contract and config snapshot."""

from __future__ import annotations

from pathlib import Path

from strength_coach import settings_registry


def test_registry_keys_are_unique_and_classified():
    keys = [setting.key for setting in settings_registry.SETTINGS]
    assert len(keys) == len(set(keys))
    assert all(setting.classification in settings_registry.CLASSES
               for setting in settings_registry.SETTINGS)
    assert len(keys) == len(settings_registry.BY_KEY)


def test_registry_sources_exist():
    base = Path("config")
    for setting in settings_registry.SETTINGS:
        if setting.source == "settings profile (registry defaults)":
            # Profile-backed settings are effective-dated values. The registry supplies their
            # defaults instead of a separate YAML file, so there is no path to check.
            continue
        assert (base / setting.source).exists(), setting.key


def test_snapshot_matches_every_definition_and_validates():
    snap = settings_registry.snapshot()
    assert set(snap.values) == set(settings_registry.BY_KEY)
    for setting in settings_registry.SETTINGS:
        setting.validate(snap.get(setting.key))
    assert snap.get("deload.reactive.consecutive_weeks") == 2
    assert snap.get("deload.reactive.consecutive_flares") == 2
    assert snap.get("e1rm.source") in ("best_usable", "median", "most_recent")
    assert snap.get("volume.landmarks.squat.mev") == 6.0
    assert snap.get("cardio.max_hr_bpm") == 200
