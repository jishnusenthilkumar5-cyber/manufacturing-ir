from __future__ import annotations

import json

import pytest

from mir import Availability, dumps_canonical
from mir.decide import SensitivityError, SensitivityKind, sensitivity
from mir.sim import Scenario
from mir.synth import FactoryBuilder, serial_line, unbalanced_line


def _bytes(value) -> bytes:
    return json.dumps(
        value.to_dict(), separators=(",", ":"), allow_nan=False
    ).encode()


def test_unbalanced_line_ranks_machine_02_cycle_time_first() -> None:
    factory = unbalanced_line()
    before = dumps_canonical(factory)
    scenario = Scenario(horizon_s=30_000, warmup_s=3_000, seed=23, replications=2)

    first = sensitivity(factory, scenario, percent=10)
    second = sensitivity(factory, scenario, percent=10)

    assert _bytes(first) == _bytes(second)
    assert dumps_canonical(factory) == before
    top = first.entries[0]
    assert top.rank == 1
    assert top.path == "operations.operation-02.cycle_time_scale"
    assert top.kind is SensitivityKind.CYCLE_TIME
    assert top.machine_ids == ("machine-02",)
    assert top.absolute_impact > 0
    assert top.absolute_impact == max(
        abs(top.lower_paired_delta), abs(top.upper_paired_delta)
    )


def test_sensitivity_covers_setup_availability_and_finite_buffers() -> None:
    builder = FactoryBuilder("shared", "Shared Machine")
    builder.add_machine(
        "machine",
        "Machine",
        "flexible",
        ["first", "second"],
        setup_time_s=5,
        availability=Availability(mtbf_s=900, mttr_s=100),
    )
    builder.add_operation("first", "First", "first", "machine", 5)
    builder.add_operation("second", "Second", "second", "machine", 5)
    builder.add_flow("inlet", "part", to_op="first", buffer_capacity=None)
    builder.add_flow(
        "middle", "part", from_op="first", to_op="second", buffer_capacity=10
    )
    builder.add_flow("outlet", "part", from_op="second", buffer_capacity=None)
    factory = builder.build()
    result = sensitivity(
        factory,
        Scenario(horizon_s=20_000, warmup_s=2_000, seed=7, replications=1),
        percent=10,
    )
    by_path = {entry.path: entry for entry in result.entries}

    assert "machines.machine.setup_time_s" in by_path
    assert "machines.machine.availability.mtbf_s" in by_path
    assert "machines.machine.availability.mttr_s" in by_path
    assert "flows.middle.buffer_capacity" in by_path
    assert "flows.inlet.buffer_capacity" not in by_path
    assert "flows.outlet.buffer_capacity" not in by_path
    assert by_path["flows.middle.buffer_capacity"].lower_value == 9
    assert by_path["flows.middle.buffer_capacity"].upper_value == 11
    assert by_path["machines.machine.setup_time_s"].lower_value == 4.5
    assert by_path["machines.machine.setup_time_s"].upper_value == 5.5


def test_null_availability_is_skipped_and_zero_parameters_are_stable() -> None:
    factory = serial_line(stations=2, cycle_times_s=[5, 10], buffer_capacity=0)
    result = sensitivity(
        factory,
        Scenario(horizon_s=4_000, warmup_s=400, replications=1),
        percent=10,
    )

    paths = {entry.path for entry in result.entries}
    assert not any("availability" in path for path in paths)
    zero_setup = next(
        entry for entry in result.entries if entry.path == "machines.machine-01.setup_time_s"
    )
    zero_buffer = next(
        entry for entry in result.entries if entry.path == "flows.buffer-01.buffer_capacity"
    )
    assert zero_setup.lower_value == zero_setup.upper_value == 0
    assert zero_setup.absolute_impact == 0
    assert zero_buffer.lower_value == zero_buffer.upper_value == 0
    assert zero_buffer.absolute_impact == 0


@pytest.mark.parametrize("percent", [0, -1, 100, 101, True, float("nan"), float("inf")])
def test_sensitivity_rejects_invalid_percent(percent) -> None:
    with pytest.raises(SensitivityError, match="percent"):
        sensitivity(serial_line(stations=1), percent=percent)
