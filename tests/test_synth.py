from __future__ import annotations

import pytest

from mir import Machine
from mir.synth import FactoryBuilder, serial_line, swap_machine


def test_builder_returns_independent_factory_copy() -> None:
    builder = FactoryBuilder("test", "Test")
    builder.add_machine("machine", "Machine", "generic", ["run"])
    first = builder.build()
    first.machines[0].name = "Changed"
    assert builder.build().machines[0].name == "Machine"


def test_serial_line_rejects_wrong_cycle_count() -> None:
    with pytest.raises(ValueError, match="one value per station"):
        serial_line(stations=2, cycle_times_s=[10])


def test_swap_machine_rewrites_references() -> None:
    factory = serial_line(stations=1, cycle_times_s=[10])
    replacement = Machine(
        id="machine-b",
        name="Machine B",
        machine_class="generic-processor",
        capabilities=["stage-01"],
        num_stations=2,
    )
    variant = swap_machine(factory, "machine-01", replacement)
    assert variant.operations[0].machines == ["machine-b"]
    assert {signal.machine for signal in variant.signals} == {"machine-b"}
    assert factory.operations[0].machines == ["machine-01"]
