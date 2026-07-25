# Manufacturing IR

The canonical semantic representation of a factory.

Manufacturing IR sits between engineering intent and physical execution. Version 0.2 keeps exactly four primitives — **Machine**, **Operation**, **MaterialFlow**, and **Signal** — and adds physical batch quantities, deterministic dispatch policies, and repeating weekly machine calendars without connecting to a factory.

This repository is a compiler core, not an AI agent. Every result is deterministic, inspectable, and traceable to the IR.

## What v0.2 does

- Defines the four-primitives IR with Pydantic and exports its JSON Schema.
- Reads v0.1 and v0.2, upgrades v0.1 defaults in memory, and writes byte-stable canonical v0.2 JSON.
- Compiles and decompiles a canonical `.mir` authoring DSL with source-located errors.
- Produces compiler-style structural and semantic diagnostics (`MIR001`–`MIR031`).
- Runs dependency-aware, non-mutating topology and ratio-aware capacity passes.
- Simulates blocking, starvation, setup, yield loss, transport, stochastic downtime, assembly, rework, shift calendars, and configurable dispatch with a deterministic discrete-event kernel.
- Sweeps bounded design spaces, recommends ranked alternatives, and reports one-at-a-time sensitivity.
- Compares alternatives with paired random seeds and renders self-contained deterministic HTML reports.
- Emits safety-labeled, vendor-neutral IEC 61131-3 Structured Text skeletons through a backend registry.
- Generates synthetic factories so every capability works without factory data.

## Quick start

Python 3.11 or newer is required.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Run the complete demonstration:

```bash
mir compile examples/line.mir -o line.json
mir validate line.json
mir analyze line.json
mir simulate line.json --horizon-h 24 --warmup-h 1 --seed 42
mir sweep line.json examples/sweep-space.json --workers 1 --json
mir recommend line.json examples/sweep-space.json --top-k 2 --workers 1
mir sensitivity line.json --percent 10 --json
mir report line.json -o line.html --horizon-h 24 --warmup-h 1
mir emit st line.json -o generated-st
```

The example exercises a weekday calendar, priority dispatch metadata, and a physical 2:1 component ratio. The decision commands evaluate bounded alternatives, the report remains a single offline file, and the emitted Structured Text is explicitly a non-deployable engineering skeleton.

Run tests:

```bash
.venv/bin/python -m pytest
```

## CLI

```text
mir compile IN.mir -o OUT.json
mir decompile IN.json -o OUT.mir
mir validate FILE [--json]
mir analyze FILE [--json]
mir simulate FILE [--horizon-h H] [--warmup-h H] [--seed N] [--replications N] [--dispatch POLICY] [--json]
mir compare BASELINE VARIANT [--horizon-h H] [--warmup-h H] [--replications N] [--dispatch POLICY] [--json]
mir sweep FACTORY SPACE.json [--workers N] [--json]
mir recommend FACTORY SPACE.json [--objective OBJECTIVE] [--top-k N] [--workers N] [--json]
mir sensitivity FACTORY [--percent P] [--json]
mir report FACTORY -o OUT.html
mir report --compare BASELINE VARIANT -o OUT.html
mir emit st FACTORY -o DIR [--force]
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
.mir DSL ──→ compiler ──→ canonical JSON
                              ↓
                         Pydantic IR ──→ validation
                              ↓
                 pass manager + DES simulation
                              ↓
             sweep / recommend / sensitivity / compare
                              ↓
                 HTML report or backend hand-off
```

```text
mir/
  core/          IDs, distributions, calendars, four primitive models
  dsl/           lexer, parser, compiler, canonical printer
  passes/        diagnostics, dependency manager, topology, capacity
  sim/           scenario, event kernel, metrics
  decide/        design spaces, sweep, recommendation, sensitivity
  report/        self-contained deterministic HTML rendering
  backends/      backend protocol, registry, Structured Text scaffold
  synth/         fluent builder and synthetic catalog
  compare.py     common-random-number alternative comparison
  io.py          canonical JSON and schema export
  cli.py         mir command
examples/        canonical JSON, DSL, and decision inputs
docs/            IR and DSL specifications
```

Passes are pure: they consume a `Factory`, emit diagnostics and named artifacts, and never mutate the IR. Dependencies are resolved by `PassManager`, so capacity consumes topology rather than rebuilding it.

The simulator owns a small `heapq` event kernel instead of hiding semantics behind a simulation framework. A station can be `busy`, `idle`, `blocked`, `starved`, `setup`, `down`, or `offshift`. Every transition is integrated over the measurement window. The same factory, scenario, and seed produce identical output.

## Canonical JSON

`mir fmt` sorts each entity collection by ID, sorts object keys, removes `null` fields, uses two-space indentation, and appends one newline. The canonicality invariant is:

```text
dumps(loads(dumps(factory))) == dumps(factory)
```

Cross-references are validated in passes rather than Pydantic. A reconstructed file with a missing reference therefore loads and emits a useful diagnostic instead of failing with an opaque parser traceback.

## Authoring DSL

The `.mir` frontend covers the four primitives and every v0.2 field. Durations accept `s`, `min`, and `h`; cycle times accept constant, uniform, normal, and exponential distributions. `mir compile` reports syntax errors with line, column, source text, and a caret. `mir decompile` produces canonical DSL, so `compile(decompile(factory)) == factory` across the catalog.

## Decision layer

A design-space JSON object maps supported parameter paths to value lists. Supported dimensions are flow buffer capacity, machine station count, operation cycle-time scale, complete availability on/off, and MTBF/MTTR. Grids are capped at 500 points. Sweep points use paired seeds against the baseline and remain ordered deterministically even when evaluated by `ProcessPoolExecutor`.

`mir recommend` ranks by throughput or throughput per WIP. `mir sensitivity` perturbs cycle time, setup, availability, and buffer capacity by a requested percentage and ranks absolute throughput impact.

## Reports and hand-off

`mir report` writes one deterministic HTML file with inline CSS and JavaScript, topology SVG, state fractions, buffers, capacity, diagnostics, and scenario details. Compare mode renders the paired-seed verdict and before/after metrics. Reports make no network requests.

`mir emit st` writes one vendor-neutral IEC 61131-3 Structured Text skeleton per machine plus `manifest.json`. The output is deliberately non-deployable, carries an explicit safety warning, and refuses a non-empty directory unless `--force` is supplied. When a machine has no `machine_state` enum signal, the state `TYPE` falls back to the simulator's seven-state vocabulary: `idle`, `running`, `blocked`, `starved`, `setup`, `down`, and `offshift`.

## Capacity semantics

The analytic pass propagates physical `units_per_batch` ratios backward from the outlet and computes expected operation cycles per shipped unit, including batch size and downstream yield loss. It allocates alternative-machine load by effective station and calendar availability and finds the resource with the highest effective seconds per unit.

The bound is exact for deterministic, single-outlet DAGs without alternative routing, setup interactions, finite-buffer effects, or stochastic downtime realization. Other graphs get `MIR100`; simulation is the decision surface for those cases.

`mir compare` runs paired replications with the same seed for each baseline/variant pair. This common-random-number design reduces variance when machine alternatives share stochastic cycle, yield, and downtime behavior.

## Deliberate limits

Version 0.2 does not include:

- PLC, SCADA, historian, CAD, MES, or ERP connectors.
- Real-data calibration or brownfield semantic reconstruction.
- Deployable control logic, vendor adapters, or hardware-specific code generation.
- Operator scheduling, business rules, or optimization beyond bounded design-space evaluation and dispatch policies.
- A detailed BOM entity system, database, web server, UI, or in-repository LLM agent.

The Structured Text backend is a reviewable hand-off seam, not a factory connector or safety-certified controller.

## Specification

The current normative schema and execution semantics are in [`docs/ir-spec-0.2.md`](docs/ir-spec-0.2.md). [`docs/ir-spec-0.1.md`](docs/ir-spec-0.1.md) remains the compatibility reference. The authoring grammar is in [`docs/dsl-0.1.md`](docs/dsl-0.1.md). The generated JSON Schema is available from `mir schema`.
