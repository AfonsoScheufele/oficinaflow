from __future__ import annotations


class IllegalTransitionError(ValueError):
    pass


APPOINTMENT_TRANSITIONS: dict[str, set[str]] = {
    "scheduled": {"confirmed", "cancelled", "no_show"},
    "confirmed": {"in_progress", "cancelled", "no_show"},
    "in_progress": {"done", "cancelled"},
    "done": set(),
    "cancelled": set(),
    "no_show": set(),
}

WORK_ORDER_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"open", "cancelled"},
    "open": {"in_progress", "cancelled"},
    "in_progress": {"waiting_parts", "done", "cancelled"},
    "waiting_parts": {"in_progress", "done", "cancelled"},
    "done": set(),
    "cancelled": set(),
}


def transition(machine: dict[str, set[str]], current: str, target: str) -> str:
    allowed = machine.get(current, set())
    if target not in allowed:
        raise IllegalTransitionError(f"Transição ilegal: {current} → {target}")
    return target
