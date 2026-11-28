"""Symptom input and the back rules it unlocks.

The acceptance criterion for this phase is behavioural: with a logged pre-session number and a
declared block start, `PRG-EREC-001` stops being `unknown` and `MOD-BACK-001` transforms a
prescription. Without them, both still say `unknown` rather than assuming "no flare".
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

import pytest
from conftest import make_readiness, make_training

from strength_coach import cli
from strength_coach.prescribe import build_prescription, validate_references
from strength_coach.rules import RuleContext, evaluate, load_document
from strength_coach.rules.context import block_week, flare_from
from strength_coach.store import db, importer, queries, repositories

SESSION_ROWS = [
    {"Date": day, "Exercise": "Back Extension", "Weight_Used": "0", "RIR": "2",
     "Reps_Done": "12"}
    for day in ("2024-01-04", "2024-01-11", "2024-01-18", "2024-01-25")
]

DAY_A_ROWS = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5",
     "RIR": "2", "Reps_Done": "10"},
]


@contextmanager
def store_with(rows):
    training = make_training(rows)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        yield store
    finally:
        store.close()


def declare_block(conn, start="2024-01-01"):
    repositories.append_athlete_profile(
        conn,
        effective_from=start,
        block_start_date=start,
    )


def log(conn, date, level, settled=None):
    repositories.append_symptom(
        conn, logged_on=date, timing="pre_session", region="low_back",
        level=level, settled_within_48h=settled,
    )


# --- the flare rule --------------------------------------------------------


@pytest.mark.parametrize(
    "level,settled,expected",
    [
        (0, None, False),
        (1, True, False),
        (1, False, True),
        (1, None, True),   # unrecorded settlement fails safe (DEC-SYMPTOM-04)
        (2, True, True),
        (3, None, True),
        (None, None, None),
    ],
)
def test_flare_definition(level, settled, expected):
    assert flare_from(level, settled) is expected


def test_block_week_is_measured_from_the_declaration():
    assert block_week("2026-11-02", "2026-11-02") == 1
    assert block_week("2026-11-02", "2026-11-09") == 2
    assert block_week("2026-11-02", "2026-11-20") == 3
    assert block_week("2026-11-02", "2026-10-30") is None   # before the start


# --- storage and CLI -------------------------------------------------------


def test_a_correction_can_be_logged_for_the_same_day():
    with db.Store(":memory:") as store:
        conn = store.connection
        log(conn, "2024-01-25", 2)
        log(conn, "2024-01-25", 1)
        assert queries.symptom_for_date(conn, "2024-01-25")["level"] == 1   # latest wins


def test_symptom_entries_are_append_only():
    with db.Store(":memory:") as store:
        conn = store.connection
        log(conn, "2024-01-25", 0)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE symptom_log SET level = 3")


def test_cli_logs_and_shows(tmp_path, capsys):
    path = tmp_path / "coach.db"
    assert cli.main(["--db", str(path), "symptom", "--date", "2024-01-25", "--level", "2"]) == 0
    out = capsys.readouterr().out
    assert "logged low_back symptom 2/3 on 2024-01-25" in out
    assert "flare" in out

    assert cli.main(["--db", str(path), "symptom", "--show"]) == 0
    out = capsys.readouterr().out
    assert "2024-01-25" in out


def test_cli_logs_and_shows_attribution(tmp_path, capsys):
    path = tmp_path / "coach.db"
    training = make_training(SESSION_ROWS)
    readiness = make_readiness([{}])
    store = db.Store(path)
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
    finally:
        store.close()
    assert cli.main([
        "--db", str(path), "symptom", "--date", "2024-01-25", "--timing", "post_session",
        "--level", "0", "--session", "2024-01-25", "--exercise", "back_extension",
        "--onset", "2024-01-25", "--confidence", "likely",
    ]) == 0
    out = capsys.readouterr().out
    assert "attributed to session 2024-01-25" in out
    assert cli.main(["--db", str(path), "symptom", "--show"]) == 0
    out = capsys.readouterr().out
    assert "suspected back_extension" in out


def test_cli_points_at_the_settling_workflow(tmp_path, capsys):
    # The question "what do I log when it settles" is asked at the moment of logging, so the
    # answer belongs in this output rather than only in a document.
    path = tmp_path / "coach.db"
    assert cli.main(["--db", str(path), "symptom", "--date", "2024-01-25", "--level", "2"]) == 0
    out = capsys.readouterr().out
    assert "level-0 reading" in out and "SYMPTOM-LOGGING.md" in out

    assert cli.main(["--db", str(path), "symptom", "--date", "2024-01-26", "--level", "0"]) == 0
    assert "level-0 reading" not in capsys.readouterr().out


def test_cli_logs_a_region_and_rejects_an_unknown_one(tmp_path, capsys):
    path = tmp_path / "coach.db"
    assert cli.main(["--db", str(path), "symptom", "--date", "2024-01-25",
                     "--region", "knee", "--level", "1"]) == 0
    assert "logged knee symptom 1/3" in capsys.readouterr().out

    rows = db.Store(path)
    try:
        entries = queries.symptom_entries(rows.connection)
    finally:
        rows.close()
    assert [e["region"] for e in entries] == ["knee"]

    with pytest.raises(SystemExit, match="unknown injury region"):
        cli.main(["--db", str(path), "symptom", "--region", "elbow", "--level", "1"])


# --- context derivation ----------------------------------------------------


def test_context_derives_flare_and_block_week():
    with store_with(SESSION_ROWS) as store:
        conn = store.connection
        declare_block(conn)
        log(conn, "2024-01-25", 0)
        context = RuleContext.from_store(conn, end="2024-01-25")

    assert context.symptom_level == 0
    assert context.symptom_flare is False
    assert context.symptom_on == "2024-01-25"
    assert context.block_week_index == 4


def test_no_symptom_means_unknown_not_absent():
    with store_with(SESSION_ROWS) as store:
        declare_block(store.connection)
        context = RuleContext.from_store(store.connection, end="2024-01-25")
    assert context.symptom_flare is None
    assert context.symptom_level is None


# --- PRG-EREC-001 ----------------------------------------------------------


def test_erector_ramp_evaluates_when_inputs_exist():
    document = load_document()
    with store_with(SESSION_ROWS) as store:
        conn = store.connection
        declare_block(conn)
        log(conn, "2024-01-25", 0)
        context = RuleContext.from_store(conn, end="2024-01-25")
        verdict = evaluate(document, context, rule_ids=["PRG-EREC-001"]).verdict("PRG-EREC-001")

    assert verdict.verdict == "pass"
    assert verdict.missing_inputs == ()
    assert any(item.ref == "symptom:2024-01-25" for item in verdict.evidence)


def test_erector_ramp_fails_on_a_flare():
    document = load_document()
    with store_with(SESSION_ROWS) as store:
        conn = store.connection
        declare_block(conn)
        log(conn, "2024-01-25", 2)
        context = RuleContext.from_store(conn, end="2024-01-25")
        result = evaluate(document, context, rule_ids=["PRG-EREC-001"])

    verdict = result.verdict("PRG-EREC-001")
    assert verdict.verdict == "fail"
    assert verdict.code == "ERECTOR_RAMP_HOLD"
    assert verdict.evidence[0].ref == "symptom:2024-01-25"


# --- MOD-BACK-001 ----------------------------------------------------------


def test_back_flare_transforms_the_prescription():
    with store_with(DAY_A_ROWS) as store:
        conn = store.connection
        log(conn, "2024-01-08", 2)
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="squat")
        context = RuleContext.from_store(conn, end="2024-01-08")
        assert validate_references(prescription, context, conn) == []

    erector = next(i for i in prescription.items if i.exercise_id == "back_extension")
    assert erector.sets == 3
    assert erector.load_kg == 0.0
    assert erector.load_basis == "bodyweight_total"

    for exercise_id in ("ssb_squat", "bench_press"):
        item = next(i for i in prescription.items if i.exercise_id == exercise_id)
        assert item.rir_target == 3
        assert "MOD-BACK-001" in item.rationale_refs
        assert "symptom:2024-01-08" in item.rationale_refs

    assert any("MOD-BACK-001" in w for w in prescription.warnings)


def test_a_level_one_without_a_settlement_still_applies_the_modifier():
    # The safety contract behind Q25: "did not settle" is an observation, so a level-1 reading
    # needs an explicit settled=yes to be dismissed. Otherwise the modifier must apply.
    with store_with(DAY_A_ROWS) as store:
        conn = store.connection
        log(conn, "2024-01-08", 1)
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="squat")

    assert any("MOD-BACK-001" in w for w in prescription.warnings)
    squat = next(i for i in prescription.items if i.exercise_id == "ssb_squat")
    assert squat.rir_target == 3


def test_a_settled_level_one_leaves_the_prescription_alone():
    with store_with(DAY_A_ROWS) as store:
        conn = store.connection
        log(conn, "2024-01-08", 1, settled=True)
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="squat")

    assert not any("MOD-BACK-001" in w for w in prescription.warnings)
    squat = next(i for i in prescription.items if i.exercise_id == "ssb_squat")
    assert squat.rir_target == 2


def test_cli_says_which_way_a_level_one_went(tmp_path, capsys):
    path = tmp_path / "coach.db"
    assert cli.main(["--db", str(path), "symptom", "--date", "2024-01-25", "--level", "1"]) == 0
    assert "no recorded 48 h settlement is a flare" in capsys.readouterr().out

    assert cli.main(["--db", str(path), "symptom", "--date", "2024-01-26", "--level", "1",
                     "--settled", "yes"]) == 0
    out = capsys.readouterr().out
    assert "settled within 48 h is not a flare" in out


def test_no_flare_leaves_the_prescription_alone():
    with store_with(DAY_A_ROWS) as store:
        conn = store.connection
        log(conn, "2024-01-08", 0)
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="squat")

    assert not any("MOD-BACK-001" in w for w in prescription.warnings)
    squat = next(i for i in prescription.items if i.exercise_id == "ssb_squat")
    assert squat.rir_target == 2


# --- per-region signals in a prescription ----------------------------------


def test_a_knee_flare_warns_without_vetoing_or_touching_the_back():
    with store_with(DAY_A_ROWS) as store:
        conn = store.connection
        repositories.append_symptom(
            conn, logged_on="2024-01-08", timing="pre_session", region="knee", level=2
        )
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="squat")
        context = RuleContext.from_store(conn, end="2024-01-08")

    # The back rules did not see the knee reading (DEC-SYMPTOM-03).
    assert context.symptom_flare is None
    assert not any("MOD-BACK-001" in w for w in prescription.warnings)

    # The knee is named, and the lifts that load it are listed. Advisory only.
    knee_warnings = [w for w in prescription.warnings if w.startswith("injury signal:")]
    assert knee_warnings and "Knee" in knee_warnings[0]
    assert "ssb_squat" in knee_warnings[0]
    assert not any("CONSTRAINT_VETO" in issue for issue in prescription.issues)

    signal = prescription.notes["injury_signal"]
    assert signal["active_regions"] == ["knee"]
    assert signal["regions"]["knee"]["latest_level"] == 2

# --- regions, characters and sides ----------------------------------------


def test_every_configured_region_is_a_loggable_region():
    from strength_coach.features.injury_signal import InjuryConfig

    config = InjuryConfig.load()
    assert sorted(config.regions) == [
        "biceps", "core", "forearm", "hamstring", "hip_groin", "knee",
        "low_back", "lower_leg", "quadriceps", "shoulder", "upper_back",
    ]
    # Compatibility: the three original ids survive, and biceps may widen its label but never
    # its id (DEC-SYMPTOM-03).
    assert config.regions["biceps"].label == "Elbow / upper arm"
    assert config.regions["low_back"].label == "Low back"
    assert config.regions["knee"].label == "Knee"


def test_many_regions_can_be_logged_on_the_same_day():
    from strength_coach.features.injury_signal import InjuryConfig

    with db.Store(":memory:") as store:
        conn = store.connection
        regions = sorted(InjuryConfig.load().regions)
        for region in regions:
            repositories.append_symptom(
                conn, logged_on="2024-01-25", timing="pre_session",
                region=region, level=1,
            )
        entries = queries.symptom_entries(conn)
        assert [row["region"] for row in entries] == regions
        # Still separate readings, never one collapsed daily score.
        assert len({row["log_id"] for row in entries}) == len(regions)


def test_characters_and_side_are_stored_with_the_reading():
    with db.Store(":memory:") as store:
        conn = store.connection
        log_id = repositories.append_symptom(
            conn, logged_on="2024-01-25", timing="pre_session", region="shoulder",
            level=2, side="left", characters=("pain", "stiffness", "pain"),
        )
        assert isinstance(log_id, int)
        (entry,) = queries.symptom_entries(conn)
        # Duplicates collapse; order is preserved so the UI can show what was chosen.
        assert entry["characters"] == ["pain", "stiffness"]
        assert entry["side"] == "left"
        assert queries.latest_symptom(conn, "2024-01-25", region="shoulder")["side"] == "left"


def test_an_unknown_character_or_side_is_rejected():
    from strength_coach.domain.symptom_vocabulary import SymptomVocabularyError

    with db.Store(":memory:") as store:
        conn = store.connection
        with pytest.raises(SymptomVocabularyError, match="unknown symptom character"):
            repositories.append_symptom(
                conn, logged_on="2024-01-25", timing="pre_session", region="knee",
                level=2, characters=("clicky",),
            )
        with pytest.raises(SymptomVocabularyError, match="unknown symptom side"):
            repositories.append_symptom(
                conn, logged_on="2024-01-25", timing="pre_session", region="knee",
                level=2, side="centre",
            )
        assert queries.symptom_entries(conn) == []


def test_optional_description_fields_can_be_omitted():
    with db.Store(":memory:") as store:
        conn = store.connection
        repositories.append_symptom(
            conn, logged_on="2024-01-25", timing="pre_session", region="knee", level=2,
        )
        (entry,) = queries.symptom_entries(conn)
        assert entry["side"] is None
        assert entry["characters"] == []


def test_a_log_only_region_is_recorded_without_joining_the_signal():
    from strength_coach.features import injury_signal

    with db.Store(":memory:") as store:
        conn = store.connection
        repositories.append_symptom(
            conn, logged_on="2024-01-25", timing="pre_session", region="shoulder", level=3,
        )
        repositories.append_symptom(
            conn, logged_on="2024-01-25", timing="pre_session", region="low_back", level=0,
        )
        signal = injury_signal.compute(conn, "2024-01-26")
        regions = {region.region for region in signal.regions}
        assert "low_back" in regions
        # A shoulder reading must not start suppressing presses merely because it is stored.
        assert "shoulder" not in regions


def test_cli_accepts_characters_and_a_side(tmp_path, capsys):
    path = tmp_path / "coach.db"
    assert cli.main([
        "--db", str(path), "symptom", "--date", "2024-01-25", "--region", "shoulder",
        "--level", "2", "--char", "pain", "--char", "stiffness", "--side", "left",
    ]) == 0
    out = capsys.readouterr().out
    assert "characters: pain, stiffness" in out and "side left" in out

    assert cli.main(["--db", str(path), "symptom", "--show"]) == 0
    out = capsys.readouterr().out
    assert "pain, stiffness" in out and "side left" in out

    # Without --level the command is a survey, so the bad flag has to carry a reading.
    assert cli.main([
        "--db", str(path), "symptom", "--date", "2024-01-26", "--level", "1",
        "--char", "clicky",
    ]) == 2


def test_velocity_report_keeps_region_and_timing_apart():
    from strength_coach.features import rep_velocity

    with db.Store(":memory:") as store:
        conn = store.connection
        repositories.append_symptom(
            conn, logged_on="2024-01-25", timing="pre_session", region="knee", level=3,
        )
        repositories.append_symptom(
            conn, logged_on="2024-01-25", timing="pre_session", region="low_back", level=1,
        )
        repositories.append_symptom(
            conn, logged_on="2024-01-25", timing="next_morning", region="low_back", level=3,
        )
        by_key = rep_velocity._symptom_by_date(conn)
        assert by_key[("2024-01-25", "knee", "pre_session")] == 3
        assert by_key[("2024-01-25", "low_back", "pre_session")] == 1
        assert by_key[("2024-01-25", "low_back", "next_morning")] == 3
