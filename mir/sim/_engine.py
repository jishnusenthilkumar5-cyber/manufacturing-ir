from __future__ import annotations

import random
from collections import defaultdict

from mir.core.model import Factory, MaterialFlow, Operation
from mir.sim._runtime import BufferRuntime, Event, EventQueue, StationRuntime
from mir.sim.metrics import BufferMetrics, MachineMetrics, ReplicationMetrics
from mir.sim.scenario import Scenario

STATES = ("busy", "idle", "blocked", "starved", "setup", "down")


class ReplicationEngine:
    def __init__(self, factory: Factory, scenario: Scenario, seed: int) -> None:
        self.factory = factory
        self.scenario = scenario
        self.seed = seed
        self.rng = random.Random(seed)
        self.now = 0.0
        self.events = EventQueue()
        self.machines = factory.machine_map()
        self.operations = factory.operation_map()
        self.flows = factory.flow_map()
        self.incoming: dict[str, list[MaterialFlow]] = {
            operation_id: [] for operation_id in self.operations
        }
        self.outgoing: dict[str, list[MaterialFlow]] = {
            operation_id: [] for operation_id in self.operations
        }
        for flow in factory.flows:
            if flow.to_op in self.incoming:
                self.incoming[flow.to_op].append(flow)
            if flow.from_op in self.outgoing:
                self.outgoing[flow.from_op].append(flow)
        for mapping in (self.incoming, self.outgoing):
            for values in mapping.values():
                values.sort(key=lambda item: item.id)
        self.input_groups: dict[str, list[list[MaterialFlow]]] = {}
        for operation_id, flows in self.incoming.items():
            grouped: defaultdict[str, list[MaterialFlow]] = defaultdict(list)
            for flow in flows:
                key = flow.input_port or f"__flow__{flow.id}"
                grouped[key].append(flow)
            self.input_groups[operation_id] = [
                sorted(grouped[key], key=lambda item: item.id)
                for key in sorted(grouped)
            ]

        self.buffers: dict[str, BufferRuntime] = {}
        for flow in factory.flows:
            needs_buffer = (
                flow.to_op is not None
                and flow.buffer_capacity != 0
                and (
                    flow.from_op is not None
                    or flow.id in scenario.arrival_rates_per_hour
                )
            )
            if needs_buffer:
                self.buffers[flow.id] = BufferRuntime(flow.id, flow.buffer_capacity)

        self.stations: dict[str, StationRuntime] = {}
        self.machine_stations: dict[str, list[StationRuntime]] = {}
        for machine in sorted(factory.machines, key=lambda item: item.id):
            stations: list[StationRuntime] = []
            for index in range(machine.num_stations):
                key = f"{machine.id}:{index + 1}"
                station = StationRuntime(key, machine.id, index)
                self.stations[key] = station
                stations.append(station)
            self.machine_stations[machine.id] = stations

        self.output_counts = {flow.id: 0 for flow in factory.flows if flow.to_op is None}
        self.scrap_counts = {operation.id: 0 for operation in factory.operations}
        self.cycle_counts = {operation.id: 0 for operation in factory.operations}
        self.input_count = 0
        self.dropped_arrivals = 0
        self.operation_last_started = {operation.id: 0 for operation in factory.operations}
        self.start_sequence = 0
        self.baseline_outputs: dict[str, int] = {}
        self.baseline_scrap: dict[str, int] = {}
        self.baseline_cycles: dict[str, int] = {}
        self.baseline_input = 0
        self.starting_wip = 0
        self.measurement_started = False

    def run(self) -> ReplicationMetrics:
        if self.scenario.warmup_s == 0:
            self._snapshot_measurement()
        else:
            self.events.push(
                self.scenario.warmup_s,
                "warmup",
                priority=100,
            )
        for flow_id in sorted(self.scenario.arrival_rates_per_hour):
            self.events.push(0.0, "arrival", (flow_id,), priority=30)
        for station in self.stations.values():
            self._schedule_failure(station)
        self._stabilize()

        while self.events:
            event = self.events.pop()
            if event.time > self.scenario.horizon_s:
                break
            self.now = event.time
            self._handle_event(event)
            self._stabilize()
        self.now = self.scenario.horizon_s
        return self._finish_metrics()

    def _handle_event(self, event: Event) -> None:
        if event.kind == "warmup":
            self._snapshot_measurement()
        elif event.kind == "arrival":
            self._handle_arrival(event.payload[0])
        elif event.kind == "failure":
            self._handle_failure(self.stations[event.payload[0]])
        elif event.kind == "repair":
            self._handle_repair(self.stations[event.payload[0]])
        elif event.kind in {"setup_complete", "process_complete"}:
            self._handle_station_event(event)
        elif event.kind == "transport_ready":
            station = self.stations[event.payload[0]]
            generation = event.payload[1]
            if station.work_generation == generation and station.current_operation:
                self._flush_station(station)

    def _schedule_station_event(
        self, station: StationRuntime, kind: str, delay_s: float
    ) -> None:
        station.event_generation += 1
        station.scheduled_kind = kind
        station.scheduled_due = self.now + delay_s
        self.events.push(
            station.scheduled_due,
            kind,
            (station.key, station.event_generation),
            priority=20,
        )

    def _schedule_failure(self, station: StationRuntime) -> None:
        availability = self.machines[station.machine_id].availability
        if availability is None or availability.mtbf_s <= 0:
            return
        delay = self.rng.expovariate(1.0 / availability.mtbf_s)
        self.events.push(self.now + delay, "failure", (station.key,), priority=10)

    def _handle_failure(self, station: StationRuntime) -> None:
        if not station.up:
            return
        station.up = False
        if station.scheduled_kind is not None and station.scheduled_due is not None:
            station.paused_kind = station.scheduled_kind
            station.paused_remaining_s = max(0.0, station.scheduled_due - self.now)
            station.event_generation += 1
            station.scheduled_kind = None
            station.scheduled_due = None
        station.set_state("down", self.now, self.scenario.warmup_s)
        availability = self.machines[station.machine_id].availability
        if availability is not None and availability.mttr_s > 0:
            delay = self.rng.expovariate(1.0 / availability.mttr_s)
            self.events.push(self.now + delay, "repair", (station.key,), priority=10)

    def _handle_repair(self, station: StationRuntime) -> None:
        if station.up:
            return
        station.up = True
        if station.paused_kind is not None:
            kind = station.paused_kind
            remaining = station.paused_remaining_s
            station.paused_kind = None
            station.paused_remaining_s = 0.0
            station.set_state(
                "setup" if kind == "setup_complete" else "busy",
                self.now,
                self.scenario.warmup_s,
            )
            self._schedule_station_event(station, kind, remaining)
        elif station.pending_outputs:
            station.set_state("blocked", self.now, self.scenario.warmup_s)
        else:
            station.set_state("idle", self.now, self.scenario.warmup_s)
        self._schedule_failure(station)

    def _handle_station_event(self, event: Event) -> None:
        station = self.stations[event.payload[0]]
        generation = event.payload[1]
        if (
            not station.up
            or station.event_generation != generation
            or station.scheduled_kind != event.kind
        ):
            return
        station.scheduled_kind = None
        station.scheduled_due = None
        if event.kind == "setup_complete":
            station.set_state("busy", self.now, self.scenario.warmup_s)
            self._schedule_station_event(
                station, "process_complete", station.sampled_cycle_s
            )
        else:
            self._complete_operation(station)

    def _handle_arrival(self, flow_id: str) -> None:
        buffer = self.buffers[flow_id]
        if buffer.can_accept(1):
            buffer.add(1, self.now, self.scenario.warmup_s)
            self.input_count += 1
        else:
            self.dropped_arrivals += 1
        interval = 3600.0 / self.scenario.arrival_rates_per_hour[flow_id]
        self.events.push(self.now + interval, "arrival", (flow_id,), priority=30)

    def _snapshot_measurement(self) -> None:
        self.baseline_outputs = dict(self.output_counts)
        self.baseline_scrap = dict(self.scrap_counts)
        self.baseline_cycles = dict(self.cycle_counts)
        self.baseline_input = self.input_count
        self.starting_wip = self._current_wip()
        for buffer in self.buffers.values():
            buffer.reset_measurement(self.now)
        self.measurement_started = True

    def _flow_available(self, flow: MaterialFlow) -> int | float:
        if flow.from_op is None and flow.id not in self.scenario.arrival_rates_per_hour:
            return float("inf")
        if flow.buffer_capacity == 0:
            return sum(
                station.pending_outputs.get(flow.id, 0)
                for station in self.stations.values()
                if station.up
                and station.state == "blocked"
                and station.output_ready_at.get(flow.id, float("inf")) <= self.now
            )
        return self.buffers[flow.id].count

    def _operation_ready(self, operation: Operation) -> bool:
        return all(
            any(
                self._flow_available(flow) >= operation.batch_size
                for flow in group
            )
            for group in self.input_groups[operation.id]
        )

    def _find_station(self, operation: Operation) -> StationRuntime | None:
        candidates = [
            station
            for machine_id in operation.machines
            for station in self.machine_stations.get(machine_id, [])
            if station.up and station.current_operation is None
        ]
        return min(candidates, key=lambda item: item.key) if candidates else None

    def _stabilize(self) -> None:
        while True:
            changed = False
            for station in sorted(self.stations.values(), key=lambda item: item.key):
                if station.up and station.pending_outputs:
                    changed = self._flush_station(station) or changed
            ready = [
                operation
                for operation in self.operations.values()
                if self._operation_ready(operation)
                and self._find_station(operation) is not None
            ]
            if ready:
                operation = min(
                    ready,
                    key=lambda item: (self.operation_last_started[item.id], item.id),
                )
                station = self._find_station(operation)
                if station is None:
                    raise RuntimeError("ready operation lost its eligible station")
                self._consume_inputs(operation)
                self._start_operation(station, operation)
                self.start_sequence += 1
                self.operation_last_started[operation.id] = self.start_sequence
                changed = True
            if not changed:
                break
        self._classify_free_stations()

    def _consume_inputs(self, operation: Operation) -> None:
        quantity = operation.batch_size
        for group in self.input_groups[operation.id]:
            available = [
                flow for flow in group if self._flow_available(flow) >= quantity
            ]
            if not available:
                raise RuntimeError(f"operation {operation.id!r} lost a required input")
            flow = min(
                available,
                key=lambda item: (item.from_op is None, item.id),
            )
            if flow.from_op is None and flow.id not in self.scenario.arrival_rates_per_hour:
                self.input_count += quantity
            elif flow.buffer_capacity == 0:
                self._consume_synchronous_flow(flow.id, quantity)
            else:
                self.buffers[flow.id].remove(
                    quantity, self.now, self.scenario.warmup_s
                )

    def _consume_synchronous_flow(self, flow_id: str, quantity: int) -> None:
        remaining = quantity
        for station in sorted(self.stations.values(), key=lambda item: item.key):
            if (
                not station.up
                or station.state != "blocked"
                or station.output_ready_at.get(flow_id, float("inf")) > self.now
            ):
                continue
            available = station.pending_outputs.get(flow_id, 0)
            consumed = min(available, remaining)
            if consumed == 0:
                continue
            station.pending_outputs[flow_id] -= consumed
            remaining -= consumed
            if station.pending_outputs[flow_id] == 0:
                del station.pending_outputs[flow_id]
                station.output_ready_at.pop(flow_id, None)
            if not station.pending_outputs:
                self._release_station(station)
            if remaining == 0:
                return
        raise RuntimeError(f"synchronous flow {flow_id!r} underflow")

    def _start_operation(
        self, station: StationRuntime, operation: Operation
    ) -> None:
        station.work_generation += 1
        station.current_operation = operation.id
        station.sampled_cycle_s = operation.cycle_time.sample(self.rng)
        needs_setup = (
            station.last_operation_kind is not None
            and station.last_operation_kind != operation.kind
            and self.machines[station.machine_id].setup_time_s > 0
        )
        station.last_operation_kind = operation.kind
        if needs_setup:
            station.set_state("setup", self.now, self.scenario.warmup_s)
            self._schedule_station_event(
                station,
                "setup_complete",
                self.machines[station.machine_id].setup_time_s,
            )
        else:
            station.set_state("busy", self.now, self.scenario.warmup_s)
            self._schedule_station_event(
                station, "process_complete", station.sampled_cycle_s
            )

    def _complete_operation(self, station: StationRuntime) -> None:
        operation = self.operations[station.current_operation or ""]
        self.cycle_counts[operation.id] += 1
        succeeded = (
            operation.yield_fraction >= 1.0
            or self.rng.random() < operation.yield_fraction
        )
        if not succeeded:
            self.scrap_counts[operation.id] += operation.batch_size
            self._release_station(station)
            return

        by_material: defaultdict[str, list[MaterialFlow]] = defaultdict(list)
        for flow in self.outgoing[operation.id]:
            by_material[flow.material].append(flow)
        selected: list[MaterialFlow] = []
        for material in sorted(by_material):
            candidates = sorted(by_material[material], key=lambda item: item.id)
            if len(candidates) == 1:
                selected.append(candidates[0])
            else:
                selected.append(
                    self.rng.choices(
                        candidates,
                        weights=[flow.routing_weight for flow in candidates],
                        k=1,
                    )[0]
                )

        if not selected:
            self._release_station(station)
            return
        station.pending_outputs = {
            flow.id: operation.batch_size for flow in selected
        }
        station.output_ready_at = {
            flow.id: self.now + flow.transport_time_s for flow in selected
        }
        station.set_state("blocked", self.now, self.scenario.warmup_s)
        ready_times = {
            ready_at
            for ready_at in station.output_ready_at.values()
            if ready_at > self.now
        }
        for ready_at in sorted(ready_times):
            self.events.push(
                ready_at,
                "transport_ready",
                (station.key, station.work_generation),
                priority=20,
            )
        self._flush_station(station)

    def _flush_station(self, station: StationRuntime) -> bool:
        if not station.up or not station.pending_outputs:
            return False
        changed = False
        for flow_id in sorted(tuple(station.pending_outputs)):
            if station.output_ready_at[flow_id] > self.now:
                continue
            quantity = station.pending_outputs[flow_id]
            flow = self.flows[flow_id]
            if flow.to_op is None:
                self.output_counts[flow_id] += quantity
            elif flow.buffer_capacity == 0:
                continue
            else:
                buffer = self.buffers[flow_id]
                if not buffer.can_accept(quantity):
                    continue
                buffer.add(quantity, self.now, self.scenario.warmup_s)
            del station.pending_outputs[flow_id]
            del station.output_ready_at[flow_id]
            changed = True
        if not station.pending_outputs:
            self._release_station(station)
        return changed

    def _release_station(self, station: StationRuntime) -> None:
        station.current_operation = None
        station.sampled_cycle_s = 0.0
        station.pending_outputs.clear()
        station.output_ready_at.clear()
        station.scheduled_kind = None
        station.scheduled_due = None
        station.set_state("idle", self.now, self.scenario.warmup_s)

    def _classify_free_stations(self) -> None:
        assigned: defaultdict[str, list[Operation]] = defaultdict(list)
        for operation in self.operations.values():
            for machine_id in operation.machines:
                assigned[machine_id].append(operation)
        for station in self.stations.values():
            if not station.up or station.current_operation is not None:
                continue
            operations = assigned[station.machine_id]
            state = (
                "idle"
                if not operations or any(self._operation_ready(item) for item in operations)
                else "starved"
            )
            station.set_state(state, self.now, self.scenario.warmup_s)

    def _current_wip(self) -> int:
        buffered = sum(buffer.count for buffer in self.buffers.values())
        in_stations = sum(
            self.operations[station.current_operation].batch_size
            for station in self.stations.values()
            if station.current_operation is not None
        )
        return buffered + in_stations

    def _finish_metrics(self) -> ReplicationMetrics:
        measurement_s = self.scenario.measurement_s
        for station in self.stations.values():
            station.finalize_state(self.now, self.scenario.warmup_s)
        for buffer in self.buffers.values():
            buffer.account_until(self.now, self.scenario.warmup_s)

        output_delta = {
            flow_id: count - self.baseline_outputs.get(flow_id, 0)
            for flow_id, count in sorted(self.output_counts.items())
        }
        scrap_delta = {
            operation_id: count - self.baseline_scrap.get(operation_id, 0)
            for operation_id, count in sorted(self.scrap_counts.items())
        }
        cycle_delta = {
            operation_id: count - self.baseline_cycles.get(operation_id, 0)
            for operation_id, count in sorted(self.cycle_counts.items())
        }
        input_delta = self.input_count - self.baseline_input
        ending_wip = self._current_wip()
        output_units = sum(output_delta.values())
        scrap_units = sum(scrap_delta.values())
        conservation_error = (
            input_delta
            - output_units
            - scrap_units
            - (ending_wip - self.starting_wip)
        )

        machine_metrics: dict[str, MachineMetrics] = {}
        for machine_id, stations in sorted(self.machine_stations.items()):
            denominator = measurement_s * len(stations)
            fractions = {
                state: sum(
                    station.state_durations.get(state, 0.0) for station in stations
                )
                / denominator
                for state in STATES
            }
            machine_metrics[machine_id] = MachineMetrics(fractions)

        buffer_metrics = {
            flow_id: BufferMetrics(
                mean_occupancy=buffer.area / measurement_s,
                max_occupancy=buffer.maximum,
                ending_occupancy=buffer.count,
            )
            for flow_id, buffer in sorted(self.buffers.items())
        }
        throughput_by_outlet = {
            flow_id: count * 3600.0 / measurement_s
            for flow_id, count in output_delta.items()
        }
        return ReplicationMetrics(
            seed=self.seed,
            measurement_s=measurement_s,
            throughput_by_outlet=throughput_by_outlet,
            throughput_units_per_hour=sum(throughput_by_outlet.values()),
            machine_metrics=machine_metrics,
            scrap_by_operation=scrap_delta,
            cycles_by_operation=cycle_delta,
            buffers=buffer_metrics,
            input_units=input_delta,
            output_units=output_units,
            starting_wip=self.starting_wip,
            ending_wip=ending_wip,
            conservation_error=conservation_error,
        )
