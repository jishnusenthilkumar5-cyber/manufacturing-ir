from __future__ import annotations

import json
from pathlib import Path

import typer

from mir.compare import compare_factories
from mir.io import (
    IRLoadError,
    dumps_canonical,
    factory_json_schema,
    loads_factory,
    write_factory,
)
from mir.passes import Severity, analyze_factory, validate_factory
from mir.sim import Scenario, SimulationError, simulate
from mir.synth import CATALOG, assembly_merge, rework_loop, serial_line, unbalanced_line

app = typer.Typer(
    name="mir",
    help="Compile, validate, analyze, and simulate Manufacturing IR documents.",
    no_args_is_help=True,
)


def _load(path: Path):
    try:
        return loads_factory(path)
    except (IRLoadError, OSError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc


@app.command("validate")
def validate_command(
    path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    result = validate_factory(_load(path))
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "valid": not result.has_errors,
                    "diagnostics": [item.to_dict() for item in result.diagnostics],
                },
                indent=2,
                sort_keys=True,
            )
        )
    elif not result.diagnostics:
        typer.echo(f"{path}: valid")
    else:
        for item in result.diagnostics:
            entities = f" [{', '.join(item.entities)}]" if item.entities else ""
            typer.echo(f"{item.severity.value}: {item.code}: {item.message}{entities}")
            if item.hint:
                typer.echo(f"  hint: {item.hint}")
    if result.has_errors:
        raise typer.Exit(1)


@app.command("fmt")
def format_command(
    path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True, writable=True),
    check: bool = typer.Option(False, "--check", help="Check formatting without writing."),
) -> None:
    canonical = dumps_canonical(_load(path))
    current = path.read_text(encoding="utf-8")
    if check:
        if current != canonical:
            typer.echo(f"{path}: not canonical", err=True)
            raise typer.Exit(1)
        typer.echo(f"{path}: canonical")
        return
    path.write_text(canonical, encoding="utf-8")
    typer.echo(f"formatted {path}")


@app.command("schema")
def schema_command() -> None:
    typer.echo(json.dumps(factory_json_schema(), indent=2, sort_keys=True))


@app.command("synth")
def synth_command(
    generator: str = typer.Argument(..., help="Synthetic factory generator."),
    output: Path = typer.Option(..., "--output", "-o", dir_okay=False),
    stations: int = typer.Option(4, min=1, help="Serial-line station count."),
    cycle_times: str | None = typer.Option(
        None,
        help="Comma-separated serial-line cycle times in seconds.",
    ),
    buffer_capacity: int = typer.Option(
        10,
        "--buffer",
        min=-1,
        help="Intermediate capacity; -1 means unbounded.",
    ),
    p_rework: float = typer.Option(0.2, min=0.001, max=0.999),
) -> None:
    if generator not in CATALOG:
        typer.echo(
            f"error: unknown generator {generator!r}; choose {', '.join(sorted(CATALOG))}",
            err=True,
        )
        raise typer.Exit(2)
    try:
        if generator == "serial-line":
            times = (
                [float(value.strip()) for value in cycle_times.split(",")]
                if cycle_times
                else None
            )
            factory = serial_line(
                stations=stations,
                cycle_times_s=times,
                buffer_capacity=None if buffer_capacity == -1 else buffer_capacity,
            )
        elif generator == "assembly-merge":
            factory = assembly_merge()
        elif generator == "rework-loop":
            factory = rework_loop(p_rework=p_rework)
        else:
            factory = unbalanced_line()
        write_factory(factory, output)
    except (ValueError, OSError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"wrote {factory.meta.id} to {output}")


@app.command("analyze")
def analyze_command(
    path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    result = analyze_factory(_load(path))
    topology = result.artifacts["topology"]["analysis"]
    capacity = result.artifacts["capacity"]["analysis"]
    payload = {
        "diagnostics": [item.to_dict() for item in result.diagnostics],
        "topology": topology.to_dict(),
        "capacity": capacity.to_dict(),
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(
            f"Topology: {len(topology.topological_order)} operations, "
            f"{len(topology.inlet_flows)} inlet(s), {len(topology.outlet_flows)} outlet(s)"
        )
        typer.echo(f"Serial line: {'yes' if topology.is_serial_line else 'no'}")
        bound = capacity.throughput_upper_bound_units_per_hour
        typer.echo(
            "Throughput bound: "
            + (f"{bound:.2f} units/hour" if bound is not None else "unavailable")
        )
        typer.echo(f"Bottleneck: {capacity.bottleneck_machine or 'unavailable'}")
        for item in result.diagnostics:
            typer.echo(f"{item.severity.value}: {item.code}: {item.message}")
    if any(item.severity is Severity.ERROR for item in result.diagnostics):
        raise typer.Exit(1)


@app.command("simulate")
def simulate_command(
    path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    horizon_h: float = typer.Option(24.0, "--horizon-h", min=0.001),
    warmup_h: float = typer.Option(0.0, "--warmup-h", min=0.0),
    seed: int = typer.Option(1),
    replications: int = typer.Option(1, min=1),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        scenario = Scenario(
            horizon_s=horizon_h * 3600.0,
            warmup_s=warmup_h * 3600.0,
            seed=seed,
            replications=replications,
        )
        result = simulate(_load(path), scenario)
    except (SimulationError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    if json_output:
        typer.echo(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return
    summary = result.summary
    typer.echo(
        "Throughput: "
        f"{summary.throughput_units_per_hour_mean:.2f} ± "
        f"{summary.throughput_units_per_hour_stdev:.2f} units/hour"
    )
    typer.echo(f"Ending WIP: {summary.ending_wip_mean:.2f}")
    for machine_id, states in summary.machine_state_fractions_mean.items():
        typer.echo(
            f"{machine_id}: busy {states.get('busy', 0.0):.1%}, "
            f"blocked {states.get('blocked', 0.0):.1%}, "
            f"starved {states.get('starved', 0.0):.1%}, "
            f"down {states.get('down', 0.0):.1%}"
        )


@app.command("compare")
def compare_command(
    baseline: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    variant: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    horizon_h: float = typer.Option(24.0, "--horizon-h", min=0.001),
    warmup_h: float = typer.Option(1.0, "--warmup-h", min=0.0),
    seed: int = typer.Option(1),
    replications: int = typer.Option(10, min=1),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        scenario = Scenario(
            horizon_s=horizon_h * 3600.0,
            warmup_s=warmup_h * 3600.0,
            seed=seed,
            replications=replications,
        )
        report = compare_factories(_load(baseline), _load(variant), scenario)
    except (SimulationError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(
        json.dumps(report.to_dict(), indent=2, sort_keys=True)
        if json_output
        else report.to_markdown()
    )


if __name__ == "__main__":
    app()
