from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from mir.cli import app
from mir.io import write_factory
from mir.synth import serial_line

runner = CliRunner()


def test_synth_validate_analyze_simulate_and_format(tmp_path: Path) -> None:
    target = tmp_path / "line.json"
    generated = runner.invoke(
        app,
        [
            "synth",
            "serial-line",
            "--stations",
            "3",
            "--cycle-times",
            "10,20,15",
            "-o",
            str(target),
        ],
    )
    assert generated.exit_code == 0, generated.output
    assert target.exists()

    validated = runner.invoke(app, ["validate", str(target)])
    assert validated.exit_code == 0, validated.output
    assert "valid" in validated.output

    analyzed = runner.invoke(app, ["analyze", str(target)])
    assert analyzed.exit_code == 0, analyzed.output
    assert "machine-02" in analyzed.output
    assert "180.00 units/hour" in analyzed.output

    simulated = runner.invoke(
        app,
        [
            "simulate",
            str(target),
            "--horizon-h",
            "2",
            "--warmup-h",
            "0.2",
            "--seed",
            "42",
        ],
    )
    assert simulated.exit_code == 0, simulated.output
    assert "Throughput:" in simulated.output

    canonical = runner.invoke(app, ["fmt", str(target), "--check"])
    assert canonical.exit_code == 0, canonical.output


def test_schema_command_outputs_json_schema() -> None:
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["properties"]["schema_version"]["const"] == "0.1.0"


def test_validate_returns_one_for_semantic_error(tmp_path: Path) -> None:
    factory = serial_line(stations=1, cycle_times_s=[10])
    factory.operations[0].machines = ["missing"]
    target = write_factory(factory, tmp_path / "broken.json")
    result = runner.invoke(app, ["validate", str(target)])
    assert result.exit_code == 1
    assert "MIR002" in result.output


def test_compare_outputs_json_report(tmp_path: Path) -> None:
    baseline = serial_line(stations=2, cycle_times_s=[10, 20])
    variant = serial_line(
        stations=2,
        cycle_times_s=[10, 12],
        factory_id="variant",
        name="Variant",
    )
    before = write_factory(baseline, tmp_path / "before.json")
    after = write_factory(variant, tmp_path / "after.json")
    result = runner.invoke(
        app,
        [
            "compare",
            str(before),
            str(after),
            "--horizon-h",
            "2",
            "--warmup-h",
            "0.2",
            "--replications",
            "2",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["throughput"]["delta_percent"] > 0
