from __future__ import annotations

from collections import Counter, defaultdict

from mir.core.model import Factory, MaterialFlow, SignalDataType, SignalSemantic
from mir.passes.base import Diagnostic, PassContext, PassResult, Severity

COUNT_SEMANTICS = {
    SignalSemantic.CYCLE_COUNT,
    SignalSemantic.GOOD_COUNT,
    SignalSemantic.SCRAP_COUNT,
}
KNOWN_MEASUREMENT_UNITS = {
    "%",
    "A",
    "Hz",
    "K",
    "Pa",
    "V",
    "bar",
    "degC",
    "kg",
    "kg/h",
    "m",
    "m/s",
    "mm",
    "mm/s",
    "rpm",
    "s",
}


class SemanticValidationPass:
    name = "semantic"
    requires: tuple[str, ...] = ()

    def run(self, factory: Factory, context: PassContext) -> PassResult:
        diagnostics: list[Diagnostic] = []
        machines = factory.machine_map()

        for operation in factory.operations:
            for machine_id in operation.machines:
                machine = machines.get(machine_id)
                if machine is not None and operation.kind not in machine.capabilities:
                    diagnostics.append(
                        Diagnostic(
                            "MIR020",
                            Severity.ERROR,
                            f"machine {machine_id!r} cannot perform operation kind {operation.kind!r}",
                            (operation.id, machine_id),
                            "Add the capability or assign a compatible machine.",
                        )
                    )

        assigned = Counter(
            machine_id
            for operation in factory.operations
            for machine_id in operation.machines
            if machine_id in machines
        )
        for machine_id in sorted(machines):
            if assigned[machine_id] == 0:
                diagnostics.append(
                    Diagnostic(
                        "MIR021",
                        Severity.WARNING,
                        f"machine {machine_id!r} is not assigned to any operation",
                        (machine_id,),
                        "Bind an operation to the machine or remove it.",
                    )
                )

        for signal in factory.signals:
            if signal.semantic is SignalSemantic.MACHINE_STATE and not signal.enum_states:
                diagnostics.append(
                    Diagnostic(
                        "MIR022",
                        Severity.ERROR,
                        f"machine-state signal {signal.id!r} has no enum_states mapping",
                        (signal.id,),
                        "Define the raw integer value for each machine state.",
                    )
                )
            if signal.semantic in COUNT_SEMANTICS and signal.dtype is not SignalDataType.INT:
                diagnostics.append(
                    Diagnostic(
                        "MIR023",
                        Severity.ERROR,
                        f"count signal {signal.id!r} must use int dtype",
                        (signal.id,),
                        "Set dtype to 'int'.",
                    )
                )
            if (
                signal.semantic is SignalSemantic.MEASUREMENT
                and signal.unit not in KNOWN_MEASUREMENT_UNITS
            ):
                diagnostics.append(
                    Diagnostic(
                        "MIR024",
                        Severity.WARNING,
                        f"measurement signal {signal.id!r} uses unknown unit {signal.unit!r}",
                        (signal.id,),
                        "Use a documented unit or extend the unit vocabulary.",
                    )
                )

        for machine in factory.machines:
            availability = machine.availability
            if availability is not None and (
                availability.mtbf_s <= 0 or availability.mttr_s <= 0
            ):
                diagnostics.append(
                    Diagnostic(
                        "MIR025",
                        Severity.ERROR,
                        f"machine {machine.id!r} has nonpositive MTBF or MTTR",
                        (machine.id,),
                        "Set mtbf_s and mttr_s to positive durations.",
                    )
                )

        for machine in factory.machines:
            valid_windows: defaultdict[int, list[tuple[float, float, int]]] = defaultdict(list)
            for index, window in enumerate(machine.calendar):
                valid = (
                    0 <= window.day <= 6
                    and 0 <= window.start_s < window.end_s <= 86_400
                )
                if not valid:
                    diagnostics.append(
                        Diagnostic(
                            "MIR030",
                            Severity.ERROR,
                            f"machine {machine.id!r} has an invalid shift window at index {index}",
                            (machine.id,),
                            "Use day 0-6 and 0 <= start_s < end_s <= 86400.",
                        )
                    )
                    continue
                valid_windows[window.day].append((window.start_s, window.end_s, index))
            for day, windows in sorted(valid_windows.items()):
                ordered = sorted(windows)
                for previous, current in zip(ordered, ordered[1:], strict=False):
                    if current[0] < previous[1]:
                        diagnostics.append(
                            Diagnostic(
                                "MIR030",
                                Severity.ERROR,
                                f"machine {machine.id!r} has overlapping shift windows on day {day}",
                                (machine.id,),
                                "Merge overlapping windows or make their boundaries disjoint.",
                            )
                        )

        input_ports: defaultdict[tuple[str, str], list[MaterialFlow]] = defaultdict(list)
        output_routes: defaultdict[tuple[str, str], list[MaterialFlow]] = defaultdict(list)
        for flow in factory.flows:
            if flow.to_op is not None and flow.input_port is not None:
                input_ports[(flow.to_op, flow.input_port)].append(flow)
            if flow.from_op is not None:
                output_routes[(flow.from_op, flow.material)].append(flow)
        for (operation_id, port), flows in sorted(input_ports.items()):
            quantities = {flow.units_per_batch for flow in flows}
            if len(quantities) > 1:
                diagnostics.append(
                    Diagnostic(
                        "MIR031",
                        Severity.ERROR,
                        f"alternative input port {port!r} on {operation_id!r} has conflicting units_per_batch",
                        tuple(flow.id for flow in sorted(flows, key=lambda item: item.id)),
                        "Give every alternative on one input port the same units_per_batch.",
                    )
                )
        for (operation_id, material), flows in sorted(output_routes.items()):
            quantities = {flow.units_per_batch for flow in flows}
            if len(flows) > 1 and len(quantities) > 1:
                diagnostics.append(
                    Diagnostic(
                        "MIR031",
                        Severity.ERROR,
                        f"alternative {material!r} outputs on {operation_id!r} have conflicting units_per_batch",
                        tuple(flow.id for flow in sorted(flows, key=lambda item: item.id)),
                        "Give every same-material routing alternative the same units_per_batch.",
                    )
                )
        operations = factory.operation_map()
        for flow in factory.flows:
            producer = operations.get(flow.from_op or "")
            consumer = operations.get(flow.to_op or "")
            adjacent = [item for item in (producer, consumer) if item is not None]
            required_capacity = max(
                (
                    operation.batch_size * flow.units_per_batch
                    for operation in adjacent
                ),
                default=0,
            )
            if (
                flow.buffer_capacity not in (None, 0)
                and flow.buffer_capacity < required_capacity
            ):
                diagnostics.append(
                    Diagnostic(
                        "MIR031",
                        Severity.ERROR,
                        f"flow {flow.id!r} cannot hold one required batch",
                        (flow.id, *(operation.id for operation in adjacent)),
                        "Increase buffer_capacity or reduce the adjacent batch quantity.",
                    )
                )

        consumed_materials = {
            flow.material for flow in factory.flows if flow.to_op is not None
        }
        produced_materials = {
            flow.material for flow in factory.flows if flow.from_op is not None
        }
        for flow in factory.flows:
            opposite_materials: set[str] | None = None
            if flow.from_op is None and flow.to_op is not None:
                opposite_materials = produced_materials
            elif flow.to_op is None and flow.from_op is not None:
                opposite_materials = consumed_materials
            if opposite_materials is not None and flow.material not in opposite_materials:
                boundary = "inlet" if flow.from_op is None else "outlet"
                diagnostics.append(
                    Diagnostic(
                        "MIR026",
                        Severity.WARNING,
                        f"{boundary} material {flow.material!r} has no process-flow continuity",
                        (flow.id,),
                        "Reuse the material across the process or document its transformation in operation attrs.",
                    )
                )

        return PassResult(diagnostics=diagnostics)
