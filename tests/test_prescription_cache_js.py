"""Behavioural tests for the browser prescription cache.

Node is available in CI and on the owner's machine; the cache itself is browser JavaScript, so
these tests execute the same module the page loads rather than reimplementing its rules in Python.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "strength_coach/web/static/prescription-cache.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is required for browser cache tests")

RUNNER = r"""
const api = require(process.argv[1]);
const scenario = JSON.parse(process.argv[2]);
const storage = {
  data: new Map(),
  getItem(key) { return this.data.has(key) ? this.data.get(key) : null; },
  setItem(key, value) { this.data.set(key, String(value)); },
  removeItem(key) { this.data.delete(key); }
};
const plan = {
  for_date: "2024-01-15",
  session_type: "squat",
  items: [{ exercise_id: "ssb_squat", sets: 3 }]
};
let out = {};
if (scenario.op === "roundtrip") {
  out.saved = api.save(storage, plan, scenario.now);
  const fresh = api.read(storage, scenario.now);
  out.plan = fresh ? fresh.plan : null;
  out.atSevenDays = Boolean(api.read(storage, scenario.now + api.MAX_AGE_MS));
  out.expired = api.read(storage, scenario.now + api.MAX_AGE_MS + 1);
  out.cleared = storage.getItem(api.KEY) === null;
} else if (scenario.op === "future") {
  api.save(storage, plan, scenario.now);
  out.future = api.read(storage, scenario.now - 1);
  out.clearedFuture = storage.getItem(api.KEY) === null;
} else if (scenario.op === "invalid") {
  storage.setItem(api.KEY, "{");
  out.invalid = api.read(storage, scenario.now);
  out.clearedInvalid = storage.getItem(api.KEY) === null;
} else if (scenario.op === "discard") {
  api.save(storage, plan, scenario.now);
  api.clear(storage);
  out.read = api.read(storage, scenario.now);
} else if (scenario.op === "selection") {
  out.autoSame = api.selectionDiffers(plan, { date: "2024-01-15", session_type: "auto" });
  out.explicitSame = api.selectionDiffers(plan, { date: "2024-01-15", session_type: "squat" });
  out.dateDiffers = api.selectionDiffers(plan, { date: "2024-01-16", session_type: "auto" });
  out.typeDiffers = api.selectionDiffers(plan, { date: "2024-01-15", session_type: "hinge" });
}
process.stdout.write(JSON.stringify(out));
"""


def _run(scenario: dict) -> dict:
    result = subprocess.run(
        [NODE, "-e", RUNNER, str(MODULE), json.dumps(scenario)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_cache_round_trip_and_seven_day_expiry() -> None:
    out = _run({"op": "roundtrip", "now": 1_000_000})
    assert out["saved"] is True
    assert out["plan"]["for_date"] == "2024-01-15"
    assert out["plan"]["session_type"] == "squat"
    assert out["atSevenDays"] is True
    assert out["expired"] is None
    assert out["cleared"] is True


def test_cache_rejects_future_and_invalid_timestamps() -> None:
    future = _run({"op": "future", "now": 1_000_000})
    assert future["future"] is None
    assert future["clearedFuture"] is True
    invalid = _run({"op": "invalid", "now": 1_000_000})
    assert invalid["invalid"] is None
    assert invalid["clearedInvalid"] is True


def test_cache_discard_is_immediate() -> None:
    out = _run({"op": "discard", "now": 1_000_000})
    assert out["read"] is None


def test_cache_distinguishes_cached_selection_from_current_form() -> None:
    out = _run({"op": "selection", "now": 1_000_000})
    assert out["autoSame"] is False
    assert out["explicitSame"] is False
    assert out["dateDiffers"] is True
    assert out["typeDiffers"] is True
