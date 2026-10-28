"""The companion demand catalogue: validation, unknown defaults and coverage."""

from __future__ import annotations

import pytest

from strength_coach.features import demands
from strength_coach.utils import exercises

BASE = """schema_version: "1.0.0"
reviewed_on: "2026-10-28"
evidence: {}
exercises: {}
"""

VALID = """schema_version: "1.0.0"
reviewed_on: "2026-10-28"
evidence:
  EV-1:
    citation: "Example et al. 2026."
    doi: "10.1000/example"
    study_type: biomechanical
    confidence: supported
exercises:
  ssb_squat:
    axial_spinal: {level: high, confidence: supported, reason: "trunk-loaded squat", evidence: [EV-1]}
"""


def write(tmp_path, text: str):
    path = tmp_path / "demands.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_shipped_catalogue_loads_and_keeps_unknown_as_the_default():
    catalogue = demands.load()
    assert catalogue.reviewed_on == "2026-10-28"
    assert catalogue.claims  # Phase 1 populated the core lifts
    for exercise_id, claims in catalogue.claims.items():
        assert exercise_id in exercises.taxonomy().entities
        for claim in claims.values():
            if claim.level == "unknown":
                continue
            assert claim.reason
            assert claim.confidence in demands.CONFIDENCES
            if claim.confidence in {"supported", "contested"}:
                assert claim.evidence
    # An id outside the populated set is unrated, not low-demand.
    assert catalogue.level("seal_row", "axial_spinal") == "unknown"
    coverage = catalogue.coverage(["ssb_squat", "seal_row"])
    assert coverage["total"] == 2
    assert coverage["rated_exercises"] == 1
    assert coverage["per_dimension"]["axial_spinal"]["unknown_rate"] == 0.5


def test_a_rated_claim_loads_with_its_evidence(tmp_path):
    catalogue = demands.load(write(tmp_path, VALID))
    claim = catalogue.claim("ssb_squat", "axial_spinal")
    assert claim is not None and claim.level == "high"
    assert claim.confidence == "supported"
    assert claim.evidence == ("EV-1",)
    assert catalogue.rated("ssb_squat", "axial_spinal")
    assert not catalogue.rated("ssb_squat", "technical")
    assert catalogue.evidence["EV-1"].doi == "10.1000/example"


def test_an_unrated_exercise_is_not_low_demand(tmp_path):
    catalogue = demands.load(write(tmp_path, VALID))
    assert catalogue.level("bench_press", "axial_spinal") == "unknown"
    assert not catalogue.comparable("ssb_squat", "bench_press", "axial_spinal")


def test_coverage_counts_rated_and_unknown_per_dimension(tmp_path):
    catalogue = demands.load(write(tmp_path, VALID))
    coverage = catalogue.coverage(["ssb_squat", "bench_press"])
    axial = coverage["per_dimension"]["axial_spinal"]
    assert axial["rated"] == 1
    assert axial["unknown"] == 1
    assert axial["unknown_rate"] == 0.5
    assert axial["supported"] == 1
    assert coverage["rated_exercises"] == 1
    assert coverage["per_dimension"]["technical"]["rated"] == 0


@pytest.mark.parametrize(
    "body, message",
    [
        (BASE.replace('"1.0.0"', '"2.0.0"'), "schema_version"),
        (BASE + "score: 7\n", "unknown top-level keys"),
        (BASE.replace('reviewed_on: "2026-10-28"', 'reviewed_on: "28/10/2026"'), "ISO date"),
        (BASE.replace("exercises: {}", "exercises:\n  not_a_lift: {axial_spinal: {level: low}}"),
         "not a canonical exercise id"),
        (BASE.replace("exercises: {}", "exercises:\n  ssb_squat: {bogus: {level: low}}"),
         "unknown dimension"),
        (BASE.replace("exercises: {}", "exercises:\n  ssb_squat: {axial_spinal: {level: extreme}}"),
         "level"),
        (BASE.replace("exercises: {}", "exercises:\n  ssb_squat: {axial_spinal: {level: high}}"),
         "needs a confidence"),
        (BASE.replace(
            "exercises: {}",
            'exercises:\n  ssb_squat: {axial_spinal: {level: high, confidence: supported, reason: "r"}}',
         ), "needs at least one evidence id"),
        (BASE.replace(
            "exercises: {}",
            'exercises:\n  ssb_squat: {axial_spinal: {level: high, confidence: provisional, reason: "r", evidence: [NOPE]}}',
         ), "unknown evidence ids"),
        (BASE.replace(
            "exercises: {}",
            'exercises:\n  ssb_squat: {axial_spinal: {level: high, confidence: provisional}}',
         ), "reason"),
    ],
)
def test_invalid_catalogues_are_refused(tmp_path, body, message):
    with pytest.raises(demands.DemandError, match=message):
        demands.load(write(tmp_path, body))


def test_an_unknown_level_needs_no_reason(tmp_path):
    body = BASE.replace(
        "exercises: {}",
        "exercises:\n  ssb_squat: {axial_spinal: {level: unknown}}",
    )
    catalogue = demands.load(write(tmp_path, body))
    claim = catalogue.claim("ssb_squat", "axial_spinal")
    assert claim is not None and claim.level == "unknown"
    assert not catalogue.rated("ssb_squat", "axial_spinal")


def test_a_missing_file_is_all_unknown_without_crashing(tmp_path):
    catalogue = demands.load(tmp_path / "absent.yaml")
    assert catalogue.claims == {}
    assert catalogue.coverage(["ssb_squat"])["per_dimension"]["axial_spinal"]["rated"] == 0


def test_the_digest_is_stable_and_content_addressed(tmp_path):
    first = demands.load(write(tmp_path, VALID))
    second = demands.load(write(tmp_path, VALID))
    assert first.digest == second.digest
    changed = demands.load(write(tmp_path, VALID.replace("high", "moderate", 1)))
    assert changed.digest != first.digest


def test_the_coverage_report_covers_every_reachable_id():
    from tools import demands_report

    data = demands_report.report()
    assert data["total"] == len(demands_report.reachable_ids())
    assert data["total"] >= 50  # the shipped templates plus configured candidates
    assert 0 < data["rated_exercises"] < data["total"]  # populated core, honest unknowns
    assert data["per_dimension"]["axial_spinal"]["rated"] == data["rated_exercises"]
    rendered = demands_report.render(data)
    assert "exercises rated" in rendered
    assert data["unrated_ids"]
