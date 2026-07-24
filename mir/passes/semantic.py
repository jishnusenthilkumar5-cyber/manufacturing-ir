from __future__ import annotations

from collections import Counter

from mir.core.model import Factory, SignalDataType, SignalSemantic
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
