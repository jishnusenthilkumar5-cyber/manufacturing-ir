from __future__ import annotations

from pathlib import Path

import pytest

from mir.compare import compare_factories
from mir.report import (
    ReportError,
    render_comparison_report,
    render_factory_report,
    write_report,
)
from mir.sim import Scenario
from mir.synth import CATALOG, serial_line, unbalanced_line


SHORT_SCENARIO = Scenario(horizon_s=1_200, warmup_s=120, seed=17, replications=1)


def test_factory_report_is_deterministic_and_writes_exact_bytes(tmp_path: Path) -> None:
    factory = serial_line(stations=2, cycle_times_s=[8, 13], buffer_capacity=3)
    scenario = Scenario(horizon_s=4_000, warmup_s=400, seed=29, replications=2)

    first = render_factory_report(factory, scenario)
    second = render_factory_report(factory, scenario)

    assert first == second
    first_path = tmp_path / "first.html"
    second_path = tmp_path / "second.html"
    assert write_report(first, first_path) == first_path
    assert write_report(second, second_path) == second_path
    assert first_path.read_bytes() == second_path.read_bytes() == first.encode("utf-8")


def test_comparison_report_is_deterministic() -> None:
    baseline = serial_line(stations=3, cycle_times_s=[20, 40, 30])
    variant = baseline.model_copy(deep=True)
    variant.meta.id = "faster-variant"
    variant.meta.name = "Faster Variant"
    variant.operations[1].cycle_time = variant.operations[1].cycle_time.model_copy(
        update={"value_s": 15.0}
    )
    scenario = Scenario(horizon_s=8_000, warmup_s=800, seed=31, replications=2)

    first = render_comparison_report(baseline, variant, scenario)
    second = render_comparison_report(baseline, variant, scenario)

    assert first == second
    assert first.encode("utf-8") == second.encode("utf-8")


@pytest.mark.parametrize("catalog_name", sorted(CATALOG))
def test_all_catalog_models_render(catalog_name: str) -> None:
    factory = CATALOG[catalog_name]()

    report = render_factory_report(factory, SHORT_SCENARIO)

    assert report.startswith("<!doctype html>")
    assert report.endswith("</html>\n")
    assert factory.meta.id in report
    assert '<svg class="topology-svg"' in report
    for operation in factory.operations:
        assert operation.id in report


def test_factory_report_contains_engineering_content() -> None:
    factory = unbalanced_line()
    scenario = Scenario(horizon_s=7_200, warmup_s=600, seed=5, replications=2)

    report = render_factory_report(factory, scenario)

    assert "Measured throughput" in report
    assert "Analytic upper bound" in report
    assert "Bound attainment" in report
    assert "machine-02" in report
    assert "BOTTLENECK" in report
    assert "Machine-state utilization" in report
    assert "State fractions" in report
    for state in ("busy", "idle", "blocked", "starved", "setup", "down", "offshift"):
        assert state in report
    assert "--offshift: #344054" in report
    assert ".state-offshift" in report
    assert "Dispatch" in report
    assert "fifo-fair" in report
    assert "Units/batch" in report
    assert "Buffer performance" in report
    assert "Mean occupancy" in report
    assert "Ending WIP" in report
    assert "Scrap by operation" in report
    assert "Diagnostics" in report


def test_comparison_report_contains_verdict_and_before_after_metrics() -> None:
    baseline = serial_line(stations=3, cycle_times_s=[20, 40, 30])
    variant = baseline.model_copy(deep=True)
    variant.meta.id = "faster-variant"
    variant.meta.name = "Faster Variant"
    variant.operations[1].cycle_time = variant.operations[1].cycle_time.model_copy(
        update={"value_s": 15.0}
    )
    scenario = Scenario(horizon_s=12_000, warmup_s=1_200, seed=11, replications=3)
    expected = compare_factories(baseline, variant, scenario)

    report = render_comparison_report(baseline, variant, scenario)

    assert expected.verdict in report
    assert "Baseline throughput" in report
    assert "Variant throughput" in report
    assert "Throughput change" in report
    assert "Bottleneck movement" in report
    assert expected.bottleneck_before in report
    assert expected.bottleneck_after in report
    assert "Machine utilization" in report
    assert "Ending WIP" in report
    assert "Scrap" in report


def test_invalid_factory_error_is_explicit_and_deterministic() -> None:
    invalid = serial_line(stations=1, cycle_times_s=[10])
    invalid.operations[0].machines = []

    with pytest.raises(ReportError) as first:
        render_factory_report(invalid, SHORT_SCENARIO)
    with pytest.raises(ReportError) as second:
        render_factory_report(invalid, SHORT_SCENARIO)

    assert str(first.value) == str(second.value)
    assert str(first.value).startswith("input factory is invalid:")
    assert "MIR005" in str(first.value)


def test_comparison_identifies_invalid_side() -> None:
    valid = serial_line(stations=1, cycle_times_s=[10])
    invalid = valid.model_copy(deep=True)
    invalid.operations[0].machines = ["missing"]

    with pytest.raises(ReportError, match=r"^baseline factory is invalid: MIR002"):
        render_comparison_report(invalid, valid, SHORT_SCENARIO)
    with pytest.raises(ReportError, match=r"^variant factory is invalid: MIR002"):
        render_comparison_report(valid, invalid, SHORT_SCENARIO)
