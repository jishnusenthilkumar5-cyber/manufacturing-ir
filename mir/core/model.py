from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from mir.core.distributions import Distribution
from mir.core.ids import EntityId, FlowId, MachineId, OperationId, SignalId

SCHEMA_VERSION = "0.2.0"
SUPPORTED_SCHEMA_VERSIONS = frozenset({"0.1.0", SCHEMA_VERSION})


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ProvenanceKind(StrEnum):
    AUTHORED = "authored"
    SYNTHETIC = "synthetic"
    RECONSTRUCTED = "reconstructed"


class SignalDataType(StrEnum):
    BOOL = "bool"
    INT = "int"
    FLOAT = "float"
    ENUM = "enum"


class SignalSemantic(StrEnum):
    MACHINE_STATE = "machine_state"
    CYCLE_COUNT = "cycle_count"
    GOOD_COUNT = "good_count"
    SCRAP_COUNT = "scrap_count"
    ALARM = "alarm"
    MEASUREMENT = "measurement"
    CUSTOM = "custom"


class Provenance(Model):
    kind: ProvenanceKind
    source: str = ""


class FactoryMeta(Model):
    id: EntityId
    name: str = Field(min_length=1)
    description: str = ""
    provenance: Provenance


class Availability(Model):
    mtbf_s: float = Field(allow_inf_nan=False)
    mttr_s: float = Field(allow_inf_nan=False)


class ShiftWindow(Model):
    day: int
    start_s: float = Field(allow_inf_nan=False)
    end_s: float = Field(allow_inf_nan=False)


class Machine(Model):
    id: MachineId
    name: str = Field(min_length=1)
    machine_class: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    num_stations: int = Field(default=1, ge=1)
    setup_time_s: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    availability: Availability | None = None
    calendar: list[ShiftWindow] = Field(default_factory=list)
    attrs: dict[str, Any] = Field(default_factory=dict)


class Operation(Model):
    id: OperationId
    name: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    machines: list[MachineId]
    cycle_time: Distribution
    yield_fraction: float = Field(default=1.0, gt=0, le=1, allow_inf_nan=False)
    batch_size: int = Field(default=1, ge=1)
    priority: int = 0
    attrs: dict[str, Any] = Field(default_factory=dict)


class MaterialFlow(Model):
    id: FlowId
    material: str = Field(min_length=1)
    from_op: OperationId | None = None
    to_op: OperationId | None = None
    input_port: str | None = Field(default=None, min_length=1)
    routing_weight: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    units_per_batch: int = Field(default=1, ge=1)
    buffer_capacity: int | None = Field(default=None, ge=0)
    transport_time_s: float = Field(default=0.0, ge=0, allow_inf_nan=False)


class Signal(Model):
    id: SignalId
    tag: str = Field(min_length=1)
    machine: MachineId
    dtype: SignalDataType
    semantic: SignalSemantic
    enum_states: dict[str, int] | None = None
    unit: str | None = None


class Factory(Model):
    schema_version: Literal["0.2.0"] = SCHEMA_VERSION
    meta: FactoryMeta
    machines: list[Machine] = Field(default_factory=list)
    operations: list[Operation] = Field(default_factory=list)
    flows: list[MaterialFlow] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)

    def machine_map(self) -> dict[str, Machine]:
        return {machine.id: machine for machine in self.machines}

    def operation_map(self) -> dict[str, Operation]:
        return {operation.id: operation for operation in self.operations}

    def flow_map(self) -> dict[str, MaterialFlow]:
        return {flow.id: flow for flow in self.flows}

    def signal_map(self) -> dict[str, Signal]:
        return {signal.id: signal for signal in self.signals}
