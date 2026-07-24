# Manufacturing IR

The canonical semantic representation of a factory.

Manufacturing IR sits between engineering intent and physical execution. Version 0.2 keeps exactly four primitives — **Machine**, **Operation**, **MaterialFlow**, and **Signal** — and adds physical batch quantities, deterministic dispatch policies, and repeating weekly machine calendars without connecting to a factory.

This repository is a compiler core, not an AI agent. Every result is deterministic, inspectable, and traceable to the IR.

## What v0.2 does

- Defines the four-primitives IR with Pydantic and exports its JSON Schema.
- Reads v0.1 and v0.2, upgrades v0.1 defaults in memory, and writes byte-stable canonical v0.2 JSON.
- Produces compiler-style structural and semantic diagnostics (`MIR001`–`MIR031`).
- Runs dependency-aware, non-mutating topology and ratio-aware capacity passes.
- Simulates blocking, starvation, setup, yield loss, transport, stochastic downtime, assembly, rework, shift calendars, and configurable dispatch with a deterministic discrete-event kernel.
- Compares two alternatives with paired random seeds and reports throughput, bottleneck, utilization, WIP, and scrap changes.
- Generates synthetic factories so every capability works without factory data.

## Quick start

Python 3.11 or newer is required.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Run the complete demonstration:

```bash
mir synth serial-line --stations 4 --cycle-times 20,30,55,25 -o line.json
mir validate line.json
mir analyze line.json
mir simulate line.json --horizon-h 24 --warmup-h 1 --seed 42
mir compare examples/unbalanced-line.json examples/faster-alternative.json --horizon-h 24 --warmup-h 1
```

The planted line reports `machine-03` as its bottleneck and converges on its analytic throughput bound. The comparison reports whether the faster alternative improves the *line*, not merely the purchased machine.

Run tests:

```bash
.venv/bin/python -m pytest
```

## CLI

```text
mir validate FILE [--json]
mir analyze FILE [--json]
mir simulate FILE [--horizon-h H] [--warmup-h H] [--seed N] [--replications N] [--dispatch POLICY] [--json]
mir compare BASELINE VARIANT [--horizon-h H] [--warmup-h H] [--replications N] [--dispatch POLICY] [--json]
mir synth {serial-line,unbalanced-line,assembly-merge,rework-loop} -o FILE
mir fmt FILE [--check]
mir schema
```

Commands return exit code `1` for an invalid IR and `2` for unreadable input or an invalid invocation. `--json` outputs are stable machine-readable contracts; default outputs are optimized for engineering review.

## Python API

```python
from mir.passes import analyze_factory, validate_factory
from mir.sim import Scenario, simulate
from mir.synth import serial_line

factory = serial_line(stations=3, cycle_times_s=[20, 55, 25])
validation = validate_factory(factory)
analysis = analyze_factory(factory)
result = simulate(
    factory,
    Scenario(horizon_s=86_400, warmup_s=3_600, seed=42, replications=5),
)

assert not validation.has_errors
print(analysis.artifacts["capacity"]["analysis"].bottleneck_machine)
print(result.summary.throughput_units_per_hour_mean)
```

## Architecture

```text
JSON
  ↓
Pydantic IR ──→ structural + semantic validation
  ↓
Pass manager ─→ topology ─→ analytic capacity bound
  ↓
DES kernel ───→ throughput / states / WIP / scrap
  ↓
Comparison ───→ paired A-vs-B decision report
```

```text
mir/
  core/          IDs, tagged distributions, four primitive models
  passes/        diagnostics, dependency manager, topology, capacity
  sim/           scenario, event kernel, metrics
  synth/         fluent builder and synthetic catalog
  compare.py     common-random-number alternative comparison
  io.py          canonical JSON and schema export
  cli.py         mir command
examples/        committed canonical synthetic IR documents
docs/            normative v0.1 and v0.2 specifications
```

Passes are pure: they consume a `Factory`, emit diagnostics and named artifacts, and never mutate the IR. Dependencies are resolved by `PassManager`, so capacity consumes topology rather than rebuilding it.

The simulator owns a small `heapq` event kernel instead of hiding semantics behind a simulation framework. A station can be `busy`, `idle`, `blocked`, `starved`, `setup`, `down`, or `offshift`. Every transition is integrated over the measurement window. The same factory, scenario, and seed produce identical output.

## Canonical JSON

`mir fmt` sorts each entity collection by ID, sorts object keys, removes `null` fields, uses two-space indentation, and appends one newline. The canonicality invariant is:

```text
dumps(loads(dumps(factory))) == dumps(factory)
```

Cross-references are validated in passes rather than Pydantic. A reconstructed file with a missing reference therefore loads and emits a useful diagnostic instead of failing with an opaque parser traceback.

## Capacity semantics

The analytic pass propagates physical `units_per_batch` ratios backward from the outlet and computes expected operation cycles per shipped unit, including batch size and downstream yield loss. It allocates alternative-machine load by effective station and calendar availability and finds the resource with the highest effective seconds per unit.

The bound is exact for deterministic, single-outlet DAGs without alternative routing, setup interactions, finite-buffer effects, or stochastic downtime realization. Other graphs get `MIR100`; simulation is the decision surface for those cases.

`mir compare` runs paired replications with the same seed for each baseline/variant pair. This common-random-number design reduces variance when machine alternatives share stochastic cycle, yield, and downtime behavior.

## Deliberate limits

Version 0.2 does not include:

- PLC, SCADA, historian, CAD, MES, or ERP connectors.
- Brownfield semantic reconstruction.
- PLC/SCADA generation or any other greenfield backend.
- Operator scheduling, optimization, business rules, or a detailed BOM entity system.
- A database, web server, UI, LLM, or textual `.mir` DSL.

Those are frontends, backends, or higher-level passes over the IR. They are intentionally excluded until the core representation proves stable.

## Specification

The current normative schema and execution semantics are in [`docs/ir-spec-0.2.md`](docs/ir-spec-0.2.md). [`docs/ir-spec-0.1.md`](docs/ir-spec-0.1.md) remains the compatibility reference. The generated JSON Schema is available from `mir schema`.
