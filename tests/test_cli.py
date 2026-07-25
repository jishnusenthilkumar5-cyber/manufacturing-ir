from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mir.cli import app
from mir.dsl import dumps_mir, loads_mir
from mir.io import loads_factory, write_factory
from mir.synth import serial_line, unbalanced_line

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
    assert payload["properties"]["schema_version"]["const"] == "0.2.0"


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


@pytest.mark.parametrize(
    "generator",
    ["assembly-merge", "rework-loop", "serial-line", "unbalanced-line"],
)
def test_every_synthetic_generator_completes_cli_smoke_chain(
    generator: str, tmp_path: Path
) -> None:
    target = tmp_path / f"{generator}.json"
    generated = runner.invoke(app, ["synth", generator, "-o", str(target)])
    assert generated.exit_code == 0, generated.output
    assert runner.invoke(app, ["validate", str(target)]).exit_code == 0
    assert runner.invoke(app, ["analyze", str(target), "--json"]).exit_code == 0
    simulated = runner.invoke(
        app,
        [
            "simulate",
            str(target),
            "--horizon-h",
            "0.1",
            "--dispatch",
            "priority",
            "--json",
        ],
    )
    assert simulated.exit_code == 0, simulated.output
    assert json.loads(simulated.output)["scenario"]["dispatch"] == "priority"
    assert runner.invoke(app, ["fmt", str(target), "--check"]).exit_code == 0


def test_compare_accepts_dispatch_policy(tmp_path: Path) -> None:
    baseline = write_factory(
        serial_line(stations=1, cycle_times_s=[10]),
        tmp_path / "baseline.json",
    )
    variant = write_factory(
        serial_line(
            stations=1,
            cycle_times_s=[8],
            factory_id="variant",
            name="Variant",
        ),
        tmp_path / "variant.json",
    )
    result = runner.invoke(
        app,
        [
            "compare",
            str(baseline),
            str(variant),
            "--horizon-h",
            "0.1",
            "--warmup-h",
            "0",
            "--replications",
            "1",
            "--dispatch",
            "shortest-cycle",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["scenario"]["dispatch"] == "shortest-cycle"


def test_compile_and_decompile_round_trip_v02_dsl(tmp_path: Path) -> None:
    factory = serial_line(stations=2, cycle_times_s=[10, 20])
    factory.machines[0].calendar = [
        {"day": 0, "start_s": 0, "end_s": 43_200}
    ]
    factory.operations[0].priority = 3
    factory.flows[0].units_per_batch = 2
    source = tmp_path / "line.mir"
    source.write_text(dumps_mir(factory), encoding="utf-8")
    compiled = tmp_path / "line.json"
    compile_result = runner.invoke(app, ["compile", str(source), "-o", str(compiled)])
    assert compile_result.exit_code == 0, compile_result.output
    assert loads_factory(compiled) == factory

    decompiled = tmp_path / "round-trip.mir"
    decompile_result = runner.invoke(
        app,
        ["decompile", str(compiled), "-o", str(decompiled)],
    )
    assert decompile_result.exit_code == 0, decompile_result.output
    assert loads_mir(decompiled.read_text(encoding="utf-8")) == factory

    malformed = tmp_path / "malformed.mir"
    malformed.write_text("factory line name {", encoding="utf-8")
    error = runner.invoke(app, ["compile", str(malformed), "-o", str(compiled)])
    assert error.exit_code == 2
    assert "^" in error.output

    invalid_utf8 = tmp_path / "invalid-utf8.mir"
    invalid_utf8.write_bytes(b"\xff")
    unreadable = runner.invoke(
        app,
        ["compile", str(invalid_utf8), "-o", str(compiled)],
    )
    assert unreadable.exit_code == 2
    assert "codec can't decode" in unreadable.output


def test_semantically_invalid_consumers_return_one(tmp_path: Path) -> None:
    factory = serial_line(stations=1, cycle_times_s=[10])
    factory.operations[0].machines = ["missing"]
    invalid = write_factory(factory, tmp_path / "invalid.json")
    valid = write_factory(
        serial_line(
            stations=1,
            cycle_times_s=[10],
            factory_id="valid",
            name="Valid",
        ),
        tmp_path / "valid.json",
    )
    space = tmp_path / "space.json"
    space.write_text(
        json.dumps({"operations.operation-01.cycle_time_scale": [1.0]}),
        encoding="utf-8",
    )
    commands = [
        ["simulate", str(invalid), "--horizon-h", "0.1"],
        ["sweep", str(invalid), str(space), "--workers", "1"],
        ["recommend", str(invalid), str(space), "--workers", "1"],
        ["sensitivity", str(invalid)],
        ["report", str(invalid), "-o", str(tmp_path / "invalid.html")],
        ["emit", "st", str(invalid), "-o", str(tmp_path / "invalid-st")],
        ["compare", str(invalid), str(valid)],
    ]
    for arguments in commands:
        result = runner.invoke(app, arguments)
        assert result.exit_code == 1, (arguments, result.output, result.exception)
        assert "MIR002" in result.output


def test_decision_commands_emit_stable_json(tmp_path: Path) -> None:
    factory = serial_line(stations=2, cycle_times_s=[10, 20], buffer_capacity=1)
    target = write_factory(factory, tmp_path / "line.json")
    internal = next(flow for flow in factory.flows if flow.from_op and flow.to_op)
    space = tmp_path / "space.json"
    space.write_text(
        json.dumps({f"flows.{internal.id}.buffer_capacity": [1, 4]}),
        encoding="utf-8",
    )
    common = [
        str(target),
        str(space),
        "--horizon-h",
        "0.2",
        "--warmup-h",
        "0",
        "--replications",
        "1",
        "--workers",
        "1",
        "--json",
    ]

    swept = runner.invoke(app, ["sweep", *common])
    assert swept.exit_code == 0, swept.output
    assert len(json.loads(swept.output)["points"]) == 2

    recommended = runner.invoke(app, ["recommend", *common, "--top-k", "1"])
    assert recommended.exit_code == 0, recommended.output
    recommendation = json.loads(recommended.output)
    assert len(recommendation["recommendations"]) == 1
    assert recommendation["objective"] == "throughput"

    sensitivity_target = write_factory(unbalanced_line(), tmp_path / "unbalanced.json")
    sensitive = runner.invoke(
        app,
        [
            "sensitivity",
            str(sensitivity_target),
            "--horizon-h",
            "0.2",
            "--warmup-h",
            "0",
            "--replications",
            "1",
            "--json",
        ],
    )
    assert sensitive.exit_code == 0, sensitive.output
    assert json.loads(sensitive.output)["entries"]


def test_report_and_emit_commands_create_artifacts(tmp_path: Path) -> None:
    baseline_factory = serial_line(stations=2, cycle_times_s=[10, 20])
    variant_factory = serial_line(
        stations=2,
        cycle_times_s=[10, 12],
        factory_id="variant",
        name="Variant",
    )
    baseline = write_factory(baseline_factory, tmp_path / "baseline.json")
    variant = write_factory(variant_factory, tmp_path / "variant.json")
    report_path = tmp_path / "factory.html"
    report_result = runner.invoke(
        app,
        [
            "report",
            str(baseline),
            "-o",
            str(report_path),
            "--horizon-h",
            "0.2",
            "--warmup-h",
            "0",
            "--replications",
            "1",
        ],
    )
    assert report_result.exit_code == 0, report_result.output
    assert report_path.read_text(encoding="utf-8").startswith("<!doctype html>")

    comparison_path = tmp_path / "comparison.html"
    comparison = runner.invoke(
        app,
        [
            "report",
            "--compare",
            str(baseline),
            str(variant),
            "-o",
            str(comparison_path),
            "--horizon-h",
            "0.2",
            "--warmup-h",
            "0",
            "--replications",
            "1",
        ],
    )
    assert comparison.exit_code == 0, comparison.output
    assert "Capacity comparison" in comparison_path.read_text(encoding="utf-8")

    output = tmp_path / "st"
    emitted = runner.invoke(app, ["emit", "st", str(baseline), "-o", str(output)])
    assert emitted.exit_code == 0, emitted.output
    assert (output / "manifest.json").exists()
    assert len(tuple(output.glob("*.st"))) == len(baseline_factory.machines)
    refused = runner.invoke(app, ["emit", "st", str(baseline), "-o", str(output)])
    assert refused.exit_code == 2
    forced = runner.invoke(
        app,
        ["emit", "st", str(baseline), "-o", str(output), "--force"],
    )
    assert forced.exit_code == 0, forced.output


def test_help_lists_every_documented_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    for command in (
        "analyze",
        "compare",
        "compile",
        "decompile",
        "emit",
        "fmt",
        "recommend",
        "report",
        "schema",
        "sensitivity",
        "simulate",
        "sweep",
        "synth",
        "validate",
    ):
        assert command in result.output
