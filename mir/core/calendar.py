from __future__ import annotations

import math

from mir.core.model import Machine

DAY_SECONDS = 86_400.0
WEEK_SECONDS = 7 * DAY_SECONDS


def is_on_shift(machine: Machine, time_s: float) -> bool:
    if not machine.calendar:
        return True
    offset = time_s % WEEK_SECONDS
    return any(
        window.day * DAY_SECONDS + window.start_s
        <= offset
        < window.day * DAY_SECONDS + window.end_s
        for window in machine.calendar
    )


def shift_fraction(machine: Machine) -> float:
    if not machine.calendar:
        return 1.0
    intervals = sorted(
        (
            window.day * DAY_SECONDS + window.start_s,
            window.day * DAY_SECONDS + window.end_s,
        )
        for window in machine.calendar
        if 0 <= window.day <= 6 and 0 <= window.start_s < window.end_s <= DAY_SECONDS
    )
    merged: list[list[float]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return sum(end - start for start, end in merged) / WEEK_SECONDS


def next_shift_transition(machine: Machine, after_s: float) -> tuple[float, bool] | None:
    if not machine.calendar:
        return None
    boundaries = sorted(
        {
            window.day * DAY_SECONDS + boundary
            for window in machine.calendar
            for boundary in (window.start_s, window.end_s)
        }
    )
    week = math.floor(after_s / WEEK_SECONDS)
    epsilon = 1e-7
    for week_index in range(week - 1, week + 3):
        for boundary in boundaries:
            candidate = week_index * WEEK_SECONDS + boundary
            if candidate <= after_s + epsilon:
                continue
            before = is_on_shift(machine, candidate - epsilon)
            after = is_on_shift(machine, candidate)
            if before != after:
                return candidate, after
    return None
