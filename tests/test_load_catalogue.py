"""The load catalogue is the resolver's own output, and the client tail is exactly reproducible."""

from __future__ import annotations

import datetime

import pytest
from conftest import make_readiness, make_training

from strength_coach.prescribe import catalogue, config, engine, loads, templates
from strength_coach.rules import RuleContext
from strength_coach.store import db, importer

_SQUAT = "competition_squat"
_BENCH = "bench_press"


@pytest.fixture
def seeded(tmp_path):
    path = tmp_path / "coach.db"
    today = datetime.date.today()
    days = [(today - datetime.timedelta(days=offset)).isoformat() for offset in (0, 3, 7)]
    rows = []
    for day in days:
        rows.append({"Date": day, "Exercise": "Competition Squat",
                     "Weight_Used": "140", "RIR": "2", "Reps_Done": "3"})
        rows.append({"Date": day, "Exercise": "Competition Bench Press",
                     "Weight_Used": "100", "RIR": "2", "Reps_Done": "5"})
    training = make_training(rows)
    readiness = make_readiness([{"Date": days[0]}])
    store = db.Store(path)
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    yield {"conn": store.connection, "today": days[0]}
    store.close()


def _client_load(entry, reps: int, rir: int):
    """The only arithmetic the phone is allowed to do (WP0 section 9.2)."""
    base = entry["base_load_kg"]
    if base is None:
        return None
    return loads.round_down(base / (1 + (reps + rir) / 30), entry["increment_kg"])


def _slot(exercise_id: str, *, reps: int, rir: int) -> templates.Slot:
    return templates.Slot(
        id=f"parity-{exercise_id}", sets=3, reps_low=reps, reps_high=reps,
        rir_low=rir, rir_high=rir, rest_s=120, essential=True,
        load_source="e1rm", exercise=exercise_id,
    )


def test_every_taxonomy_exercise_has_an_entry(seeded):
    built = catalogue.build_catalogue(
        seeded["conn"], for_date=seeded["today"], session_type="squat",
    )
    assert built["catalogue_version"] == catalogue.CATALOGUE_VERSION
    assert built["as_of"] == seeded["today"]
    assert len(built["exercises"]) >= 100
    squat = built["exercises"][_SQUAT]
    assert squat["load_source"] == "e1rm"
    assert squat["base_load_kg"] > 0
    assert squat["increment_kg"] > 0
    assert squat["accessory_load_kg"] == pytest.approx(140.0)

    # An exercise with no history still has an entry: the phone must be able to say "no base".
    cold = built["exercises"]["barbell_curl"]
    assert cold["base_load_kg"] is None

    raw = catalogue.dumps(built)
    assert len(raw) < 60_000


def test_client_formula_reproduces_the_resolver(seeded):
    """The parity gate: shipped base + the documented tail equals build_item's load."""
    conn = seeded["conn"]
    for_date = seeded["today"]
    built = catalogue.build_catalogue(conn, for_date=for_date, session_type="squat")
    thresholds = config.Thresholds.load()
    template = templates.SessionTemplate.load("squat")
    context = RuleContext.from_store(conn, end=for_date, rep_ranges=template.rep_ranges())

    checked = 0
    for exercise_id in (_SQUAT, _BENCH):
        entry = built["exercises"][exercise_id]
        assert entry["base_load_kg"] is not None, exercise_id
        for reps, rir in ((5, 2), (8, 1), (3, 3), (10, 0)):
            item, _ = engine.build_item(
                conn, context, _slot(exercise_id, reps=reps, rir=rir),
                0, thresholds, for_date, {}, template, exercise_id=exercise_id,
            )
            assert _client_load(entry, reps, rir) == pytest.approx(item.load_kg), (
                exercise_id, reps, rir,
            )
            checked += 1
    assert checked == 8
