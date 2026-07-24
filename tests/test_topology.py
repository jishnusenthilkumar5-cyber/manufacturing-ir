from __future__ import annotations

from mir.passes import analyze_factory
from mir.synth import assembly_merge, rework_loop, serial_line


def topology(factory):
    return analyze_factory(factory).artifacts["topology"]["analysis"]


def test_serial_line_has_total_order() -> None:
    analysis = topology(serial_line(stations=3, cycle_times_s=[10, 20, 30]))
    assert analysis.topological_order == (
        "operation-01",
        "operation-02",
        "operation-03",
    )
    assert analysis.inlet_flows == ("inlet",)
    assert analysis.outlet_flows == ("outlet",)
    assert analysis.cycles == ()
    assert analysis.is_serial_line


def test_assembly_merge_is_dag_but_not_serial() -> None:
    analysis = topology(assembly_merge())
    assert analysis.topological_order[-1] == "assemble"
    assert set(analysis.reverse_adjacency["assemble"]) == {"feed-a", "feed-b"}
    assert not analysis.is_serial_line


def test_rework_loop_reports_cycle() -> None:
    analysis = topology(rework_loop())
    assert analysis.topological_order == ()
    assert analysis.cycles == (("inspect", "process"),)
    assert set(analysis.reachable_operations) == {"inspect", "process"}
