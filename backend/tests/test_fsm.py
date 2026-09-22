from app.services.fsm import (
    APPOINTMENT_TRANSITIONS,
    WORK_ORDER_TRANSITIONS,
    IllegalTransitionError,
    transition,
)
import pytest


def test_appointment_happy_path():
    s = "scheduled"
    s = transition(APPOINTMENT_TRANSITIONS, s, "confirmed")
    s = transition(APPOINTMENT_TRANSITIONS, s, "in_progress")
    s = transition(APPOINTMENT_TRANSITIONS, s, "done")
    assert s == "done"


def test_appointment_illegal():
    with pytest.raises(IllegalTransitionError):
        transition(APPOINTMENT_TRANSITIONS, "scheduled", "done")


def test_work_order_happy_path():
    s = "draft"
    s = transition(WORK_ORDER_TRANSITIONS, s, "open")
    s = transition(WORK_ORDER_TRANSITIONS, s, "in_progress")
    s = transition(WORK_ORDER_TRANSITIONS, s, "waiting_parts")
    s = transition(WORK_ORDER_TRANSITIONS, s, "done")
    assert s == "done"


def test_work_order_illegal():
    with pytest.raises(IllegalTransitionError):
        transition(WORK_ORDER_TRANSITIONS, "draft", "done")
