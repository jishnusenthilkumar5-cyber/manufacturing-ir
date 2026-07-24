from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass(order=True, slots=True)
class Event:
    time: float
    priority: int
    sequence: int
    kind: str = field(compare=False)
    payload: tuple[Any, ...] = field(compare=False, default=())


class EventQueue:
    def __init__(self) -> None:
        self._events: list[Event] = []
        self._sequence = 0

    def push(
        self,
        time: float,
        kind: str,
        payload: tuple[Any, ...] = (),
        priority: int = 20,
    ) -> None:
        self._sequence += 1
        heapq.heappush(
            self._events,
            Event(time, priority, self._sequence, kind, payload),
        )

    def pop(self) -> Event:
        return heapq.heappop(self._events)

    def __bool__(self) -> bool:
        return bool(self._events)


@dataclass(slots=True)
class BufferRuntime:
    flow_id: str
    capacity: int | None
    count: int = 0
    area: float = 0.0
    last_change: float = 0.0
    maximum: int = 0

    def account_until(self, now: float, warmup_s: float) -> None:
        start = max(self.last_change, warmup_s)
        if now > start:
            self.area += self.count * (now - start)
        self.last_change = now

    def add(self, quantity: int, now: float, warmup_s: float) -> None:
        self.account_until(now, warmup_s)
        self.count += quantity
        if now >= warmup_s:
            self.maximum = max(self.maximum, self.count)

    def remove(self, quantity: int, now: float, warmup_s: float) -> None:
        if quantity > self.count:
            raise RuntimeError(f"buffer {self.flow_id!r} underflow")
        self.account_until(now, warmup_s)
        self.count -= quantity

    def can_accept(self, quantity: int) -> bool:
        return self.capacity is None or self.count + quantity <= self.capacity

    def reset_measurement(self, now: float) -> None:
        self.area = 0.0
        self.last_change = now
        self.maximum = self.count


@dataclass(slots=True)
class StationRuntime:
    key: str
    machine_id: str
    index: int
    state: str = "idle"
    state_since: float = 0.0
    state_durations: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    up: bool = True
    current_operation: str | None = None
    last_operation_kind: str | None = None
    sampled_cycle_s: float = 0.0
    pending_outputs: dict[str, int] = field(default_factory=dict)
    output_ready_at: dict[str, float] = field(default_factory=dict)
    work_generation: int = 0
    event_generation: int = 0
    scheduled_kind: str | None = None
    scheduled_due: float | None = None
    paused_kind: str | None = None
    paused_remaining_s: float = 0.0

    def set_state(self, state: str, now: float, warmup_s: float) -> None:
        if state == self.state:
            return
        start = max(self.state_since, warmup_s)
        if now > start:
            self.state_durations[self.state] += now - start
        self.state = state
        self.state_since = now

    def finalize_state(self, now: float, warmup_s: float) -> None:
        start = max(self.state_since, warmup_s)
        if now > start:
            self.state_durations[self.state] += now - start
        self.state_since = now
