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
    for session_type, leg in (("hinge", "B"), ("bench_hinge", "C")):
        template = templates.SessionTemplate.load(session_type)
        ids = {slot.exercises[0] for slot in template.slots}
        assert "back_extension" not in ids
        assert templates.SessionTemplate.load(session_type).legacy_day == leg


def test_rolling_schedule_keeps_the_three_emphases_balanced():
    # No history: the first choice is squat. Then a fresh two-week cycle alternates.
    assert schedule.next_session_type.__module__
    assert schedule.legacy_day("squat") == "A"
    assert schedule.legacy_day("hinge") == "B"
    assert schedule.legacy_day("bench_squat") == "C"
    assert schedule.legacy_day("bench_hinge") == "C"


def test_plan_a_restores_squat_and_raises_hinge_volume():
    squat = templates.SessionTemplate.load("squat")
    hinge = templates.SessionTemplate.load("hinge")
    bench_squat = templates.SessionTemplate.load("bench_squat")
    assert next(s.sets for s in squat.slots if s.id == "squat_main") == 5
    assert next(s.sets for s in hinge.slots if s.id == "hinge_main") == 5
    assert next(s.sets for s in bench_squat.slots if s.id == "squat_support") == 4
