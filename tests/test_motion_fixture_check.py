"""The fixture harness must fail loudly when a recording contradicts its label."""

from __future__ import annotations

import json

from tests.test_motion_segmentation import _profile, _recording
from tools import motion_fixture_check as harness


def _write(tmp_path, name: str, reps: int) -> None:
    x = _profile(reps=reps, lower_s=1.2, lift_s=0.8, rest_s=2.0, rom=0.35)
    (tmp_path / name).write_text(json.dumps(_recording(x)), encoding="utf-8")


def test_manifest_that_agrees_passes(tmp_path):
    _write(tmp_path, "set.json", reps=3)
    manifest = tmp_path / "expected.json"
    manifest.write_text(json.dumps({"fixtures": [{"file": "set.json", "reps": 3}]}))

    results = harness.check(manifest)

    assert results[0]["ok"]
    assert harness.main(["--manifest", str(manifest)]) == 0


def test_manifest_that_disagrees_fails(tmp_path):
    _write(tmp_path, "set.json", reps=2)
    manifest = tmp_path / "expected.json"
    manifest.write_text(json.dumps({"fixtures": [{"file": "set.json", "reps": 3}]}))

    results = harness.check(manifest)

    assert not results[0]["ok"]
    assert harness.main(["--manifest", str(manifest)]) == 1
