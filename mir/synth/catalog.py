from __future__ import annotations

from collections.abc import Sequence

from mir.core.model import Factory
from mir.synth.builder import FactoryBuilder


def serial_line(
    stations: int = 4,
    cycle_times_s: Sequence[float] | None = None,
    buffer_capacity: int | None = 10,
    *,
    factory_id: str = "serial-line",
    name: str = "Synthetic Serial Line",
) -> Factory:
    if stations < 1:
        raise ValueError("stations must be at least 1")
    times = list(cycle_times_s or [20.0 + index * 5.0 for index in range(stations)])
    if len(times) != stations:
        raise ValueError("cycle_times_s must have one value per station")
    builder = FactoryBuilder(factory_id, name)
    for index, cycle_time in enumerate(times, start=1):
        suffix = f"{index:02d}"
        kind = f"stage-{suffix}"
        builder.add_machine(
            f"machine-{suffix}",
            f"Machine {suffix}",
            "generic-processor",
            [kind],
        ).add_operation(
            f"operation-{suffix}",
            f"Operation {suffix}",
            kind,
            f"machine-{suffix}",
            cycle_time,
        )
    builder.add_flow("inlet", "part", to_op="operation-01", buffer_capacity=None)
    for index in range(1, stations):
        builder.add_flow(
            f"buffer-{index:02d}",
            "part",
            from_op=f"operation-{index:02d}",
            to_op=f"operation-{index + 1:02d}",
            buffer_capacity=buffer_capacity,
        )
    builder.add_flow(
        "outlet",
        "part",
        from_op=f"operation-{stations:02d}",
        buffer_capacity=None,
    )
    return builder.with_default_signals().build()


def unbalanced_line() -> Factory:
    return serial_line(
        stations=3,
        cycle_times_s=[20.0, 55.0, 25.0],
        buffer_capacity=20,
        factory_id="unbalanced-line",
        name="Unbalanced Demonstration Line",
    )


def assembly_merge() -> Factory:
    builder = FactoryBuilder("assembly-merge", "Two-Feeder Assembly Line")
    builder.add_machine("feeder-a", "Feeder A", "feeder", ["feed-a"])
    builder.add_machine("feeder-b", "Feeder B", "feeder", ["feed-b"])
    builder.add_machine("assembler", "Assembler", "assembly", ["assemble"])
    builder.add_operation("feed-a", "Feed A", "feed-a", "feeder-a", 12)
    builder.add_operation("feed-b", "Feed B", "feed-b", "feeder-b", 15)
    builder.add_operation("assemble", "Assemble", "assemble", "assembler", 20)
    builder.add_flow("in-a", "part", to_op="feed-a")
    builder.add_flow("in-b", "part", to_op="feed-b")
    builder.add_flow("a-to-assembly", "part", from_op="feed-a", to_op="assemble", buffer_capacity=8)
    builder.add_flow("b-to-assembly", "part", from_op="feed-b", to_op="assemble", buffer_capacity=8)
    builder.add_flow("assembled-out", "part", from_op="assemble")
    return builder.with_default_signals().build()


def rework_loop(p_rework: float = 0.2) -> Factory:
    if not 0 < p_rework < 1:
        raise ValueError("p_rework must be between 0 and 1")
    builder = FactoryBuilder(
        "rework-loop",
        "Buffered Rework Loop",
        description=f"Topology fixture with nominal rework probability {p_rework:.3f}.",
    )
    builder.add_machine("processor", "Processor", "processor", ["process"])
    builder.add_machine("inspector", "Inspector", "inspection", ["inspect"])
    builder.add_operation("process", "Process", "process", "processor", 20)
    builder.add_operation(
        "inspect",
        "Inspect",
        "inspect",
        "inspector",
        8,
        attrs={"nominal_rework_probability": p_rework},
    )
    builder.add_flow("inlet", "part", to_op="process", input_port="feed")
    builder.add_flow("to-inspection", "part", from_op="process", to_op="inspect", buffer_capacity=5)
    builder.add_flow(
        "rework",
        "part",
        from_op="inspect",
        to_op="process",
        input_port="feed",
        routing_weight=p_rework,
        buffer_capacity=5,
    )
    builder.add_flow(
        "outlet",
        "part",
        from_op="inspect",
        routing_weight=1.0 - p_rework,
    )
    return builder.with_default_signals().build()


CATALOG = {
    "assembly-merge": assembly_merge,
    "rework-loop": rework_loop,
    "serial-line": serial_line,
    "unbalanced-line": unbalanced_line,
}
