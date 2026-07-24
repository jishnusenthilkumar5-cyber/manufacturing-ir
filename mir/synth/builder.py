from __future__ import annotations

from collections.abc import Iterable

from mir.core.distributions import ConstantDistribution, Distribution
from mir.core.model import (
    Availability,
    Factory,
    FactoryMeta,
    Machine,
    MaterialFlow,
    Operation,
    Provenance,
    ProvenanceKind,
    Signal,
    SignalDataType,
    SignalSemantic,
)


class FactoryBuilder:
    def __init__(
        self,
        factory_id: str,
        name: str,
        description: str = "",
        provenance: ProvenanceKind = ProvenanceKind.SYNTHETIC,
        source: str = "mir.synth",
    ) -> None:
        self._factory = Factory(
            meta=FactoryMeta(
                id=factory_id,
                name=name,
                description=description,
                provenance=Provenance(kind=provenance, source=source),
            )
        )

    def add_machine(
        self,
        machine_id: str,
        name: str,
        machine_class: str,
        capabilities: Iterable[str],
        *,
        num_stations: int = 1,
        setup_time_s: float = 0.0,
        availability: Availability | None = None,
        attrs: dict | None = None,
    ) -> "FactoryBuilder":
        self._factory.machines.append(
            Machine(
                id=machine_id,
                name=name,
                machine_class=machine_class,
                capabilities=list(capabilities),
                num_stations=num_stations,
                setup_time_s=setup_time_s,
                availability=availability,
                attrs=attrs or {},
            )
        )
        return self

    def add_operation(
        self,
        operation_id: str,
        name: str,
        kind: str,
        machines: str | Iterable[str],
        cycle_time: float | Distribution,
        *,
        yield_fraction: float = 1.0,
        batch_size: int = 1,
        attrs: dict | None = None,
    ) -> "FactoryBuilder":
        machine_ids = [machines] if isinstance(machines, str) else list(machines)
        distribution = (
            ConstantDistribution(value_s=float(cycle_time))
            if isinstance(cycle_time, int | float)
            else cycle_time
        )
        self._factory.operations.append(
            Operation(
                id=operation_id,
                name=name,
                kind=kind,
                machines=machine_ids,
                cycle_time=distribution,
                yield_fraction=yield_fraction,
                batch_size=batch_size,
                attrs=attrs or {},
            )
        )
        return self

    def add_flow(
        self,
        flow_id: str,
        material: str,
        *,
        from_op: str | None = None,
        to_op: str | None = None,
        input_port: str | None = None,
        routing_weight: float = 1.0,
        buffer_capacity: int | None = None,
        transport_time_s: float = 0.0,
    ) -> "FactoryBuilder":
        self._factory.flows.append(
            MaterialFlow(
                id=flow_id,
                material=material,
                from_op=from_op,
                to_op=to_op,
                input_port=input_port,
                routing_weight=routing_weight,
                buffer_capacity=buffer_capacity,
                transport_time_s=transport_time_s,
            )
        )
        return self

    def add_signal(
        self,
        signal_id: str,
        tag: str,
        machine: str,
        dtype: SignalDataType,
        semantic: SignalSemantic,
        *,
        enum_states: dict[str, int] | None = None,
        unit: str | None = None,
    ) -> "FactoryBuilder":
        self._factory.signals.append(
            Signal(
                id=signal_id,
                tag=tag,
                machine=machine,
                dtype=dtype,
                semantic=semantic,
                enum_states=enum_states,
                unit=unit,
            )
        )
        return self

    def with_default_signals(self) -> "FactoryBuilder":
        existing = {signal.machine for signal in self._factory.signals}
        for machine in self._factory.machines:
            if machine.id in existing:
                continue
            prefix = machine.id.upper().replace("-", "_")
            self.add_signal(
                f"{machine.id}-state",
                f"{prefix}_STATE",
                machine.id,
                SignalDataType.ENUM,
                SignalSemantic.MACHINE_STATE,
                enum_states={
                    "idle": 0,
                    "running": 1,
                    "blocked": 2,
                    "starved": 3,
                    "setup": 4,
                    "down": 5,
                },
            )
            self.add_signal(
                f"{machine.id}-cycle-count",
                f"{prefix}_CYCLE_CT",
                machine.id,
                SignalDataType.INT,
                SignalSemantic.CYCLE_COUNT,
            )
            self.add_signal(
                f"{machine.id}-good-count",
                f"{prefix}_GOOD_CT",
                machine.id,
                SignalDataType.INT,
                SignalSemantic.GOOD_COUNT,
            )
            self.add_signal(
                f"{machine.id}-scrap-count",
                f"{prefix}_SCRAP_CT",
                machine.id,
                SignalDataType.INT,
                SignalSemantic.SCRAP_COUNT,
            )
        return self

    def build(self) -> Factory:
        result = self._factory.model_copy(deep=True)
        result.machines.sort(key=lambda item: item.id)
        result.operations.sort(key=lambda item: item.id)
        result.flows.sort(key=lambda item: item.id)
        result.signals.sort(key=lambda item: item.id)
        return result


def swap_machine(factory: Factory, machine_id: str, replacement: Machine) -> Factory:
    result = factory.model_copy(deep=True)
    indexes = [index for index, machine in enumerate(result.machines) if machine.id == machine_id]
    if len(indexes) != 1:
        raise ValueError(f"expected exactly one machine {machine_id!r}")
    result.machines[indexes[0]] = replacement.model_copy(deep=True)
    if replacement.id != machine_id:
        for operation in result.operations:
            operation.machines = [
                replacement.id if candidate == machine_id else candidate
                for candidate in operation.machines
            ]
        for signal in result.signals:
            if signal.machine == machine_id:
                signal.machine = replacement.id
    return result
