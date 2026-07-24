from __future__ import annotations

import pytest

from mir import Availability
from mir.passes import analyze_factory, validate_factory
from mir.synth import assembly_merge, serial_line, unbalanced_line


def capacity(factory):
    return analyze_factory(factory).artifacts["capacity"]["analysis"]


def test_catalog_dag_factories_validate_cleanly() -> None:
    assert validate_factory(serial_line()).diagnostics == ()
    assert validate_factory(assembly_merge()).diagnostics == ()
    assert validate_factory(unbalanced_line()).diagnostics == ()


def test_unbalanced_line_finds_planted_bottleneck() -> None:
    analysis = capacity(unbalanced_line())
    assert analysis.exact
    assert analysis.bottleneck_machine == "machine-02"
    assert analysis.throughput_upper_bound_units_per_hour == pytest.approx(3600 / 55)


def test_assembly_capacity_accounts_for_both_feeders() -> None:
    analysis = capacity(assembly_merge())
    assert analysis.operation_cycles_per_unit == {
        "assemble": 1.0,
        "feed-a": 1.0,
        "feed-b": 1.0,
    }
    assert analysis.bottleneck_machine == "assembler"


def test_yield_loss_inflates_upstream_cycles() -> None:
    factory = serial_line(stations=2, cycle_times_s=[10, 10])
    factory.operations[1].yield_fraction = 0.8
    analysis = capacity(factory)
    assert analysis.operation_cycles_per_unit["operation-02"] == pytest.approx(1.25)
    assert analysis.operation_cycles_per_unit["operation-01"] == pytest.approx(1.25)


def test_availability_reduces_capacity() -> None:
    factory = serial_line(stations=1, cycle_times_s=[10])
    factory.machines[0].availability = Availability(mtbf_s=90, mttr_s=10)
    analysis = capacity(factory)
    assert analysis.machine_capacities["machine-01"].availability_fraction == 0.9
    assert analysis.throughput_upper_bound_units_per_hour == pytest.approx(324)
