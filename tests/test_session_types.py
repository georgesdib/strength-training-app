"""Session-type templates and the rolling emphasis scheduler."""

from __future__ import annotations

from strength_coach.prescribe import schedule, templates


def test_every_session_has_an_upper_body_push_and_a_row():
    for session_type in templates.SESSION_TYPES:
        template = templates.SessionTemplate.load(session_type)
        ids = {exercise for slot in template.slots for exercise in slot.exercises}
        assert "dumbbell_row" in ids
        assert ({"bench_press", "bench_press_narrow", "bench_press_pause"}
                & ids) or "overhead_press_seated" in ids


def test_hinge_sessions_do_not_carry_direct_erector_work():
    for session_type in ("hinge", "bench_hinge"):
        template = templates.SessionTemplate.load(session_type)
        ids = {slot.exercises[0] for slot in template.slots}
        assert "back_extension" not in ids


def test_rolling_schedule_keeps_the_three_emphases_balanced():
    # No history: the first choice is squat. Then a fresh two-week cycle alternates.
    assert schedule.next_session_type.__module__
    assert schedule.SESSION_TYPES == ("squat", "hinge", "bench_squat", "bench_hinge")


def test_plan_a_restores_squat_and_raises_hinge_volume():
    squat = templates.SessionTemplate.load("squat")
    hinge = templates.SessionTemplate.load("hinge")
    bench_squat = templates.SessionTemplate.load("bench_squat")
    assert next(s.sets for s in squat.slots if s.id == "squat_main") == 5
    assert next(s.sets for s in hinge.slots if s.id == "hinge_main") == 5
    assert next(s.sets for s in bench_squat.slots if s.id == "squat_support") == 4


def test_history_without_squat_rotates_instead_of_three_squats():
    # A recent block of four hinge and two bench sessions used to produce squat x3 because
    # the old tie-break always chose the first family. The scheduler must rotate.
    history = ["hinge", "hinge", "hinge", "hinge", "bench_squat", "bench_squat"]
    prior: list[str] = []
    for _ in range(6):
        family = schedule._choose_family(history + prior, schedule.TARGET_COUNTS)
        prior.append("bench_squat" if family == "bench" else family)
    assert prior != ["squat", "squat", "squat", "bench_hinge", "squat", "bench_squat"]
    assert prior.count("squat") == 2
    assert prior.count("hinge") == 2
    assert sum(1 for value in prior if value.startswith("bench")) == 2

def test_bench_squat_does_not_repeat_the_squat_sessions_main_lift():
    # DEC-PROGRAMME-08: bench+squat used to program the same SSB squat as the squat session,
    # so the same movement landed on two sessions two days apart and the emphasis alternation
    # was invisible in the actual lifts.
    squat_main = next(
        slot.exercise for slot in templates.SessionTemplate.load("squat").slots
        if slot.id == "squat_main"
    )
    support = next(
        slot.exercise for slot in templates.SessionTemplate.load("bench_squat").slots
        if slot.id == "squat_support"
    )
    assert squat_main == "ssb_squat"
    assert support is not None
    assert support != squat_main


def test_validate_text_accepts_the_shipped_document_and_rejects_bad_schema():
    from strength_coach.utils import paths

    text = paths.session_types_yaml().read_text(encoding="utf-8")
    parsed = templates.validate_text(text)
    assert set(parsed["session_types"]) == set(templates.SESSION_TYPES)
    bad = text.replace('schema_version: "1.0.0"', 'schema_version: "9.9.9"')
    try:
        templates.validate_text(bad)
    except templates.TemplateError:
        pass
    else:
        raise AssertionError("bad schema was accepted")


def test_validate_text_rejects_ambiguous_slots_and_missing_essential_work():
    from strength_coach.utils import paths

    text = paths.session_types_yaml().read_text(encoding="utf-8")
    ambiguous = text.replace(
        "        - id: power\n          exercise: box_jump",
        "        - id: power\n          exercise: box_jump\n          exercise_variants: [box_jump]",
        1,
    )
    try:
        templates.validate_text(ambiguous)
    except templates.TemplateError as exc:
        assert "exactly one of exercise or exercise_variants" in str(exc)
    else:
        raise AssertionError("ambiguous slot was accepted")

    no_essential = text.replace("          essential: true", "          essential: false")
    try:
        templates.validate_text(no_essential)
    except templates.TemplateError:
        pass
    else:
        raise AssertionError("session with no essential slot was accepted")


def test_a_constrained_primary_family_falls_back_and_rebalances():
    from strength_coach.store import db, repositories

    store = db.Store(":memory:")
    try:
        repositories.append_exercise_suitability(
            store.connection, exercise_id="trap_bar_deadlift", rated_on="2024-01-01",
            can_do=False, will_do=False, feels_bad=False,
        )
        availability = schedule._availability(store.connection)
        assert availability["hinge"] is False
        assert availability["bench_hinge"] is True  # bench primary is available
        targets = schedule._targets({"squat", "bench"})
        assert targets == {"squat": 3, "hinge": 0, "bench": 3}
        chosen = schedule.next_session_type(store.connection, "2024-02-01")
        assert chosen in {"squat", "bench_squat", "bench_hinge"}
    finally:
        store.close()
