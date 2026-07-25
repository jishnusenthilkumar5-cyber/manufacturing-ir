# Changelog

All notable changes to Manufacturing IR are documented here.

## 0.2.0

- Add IR schema 0.2 with backward-compatible 0.1 loading and canonical 0.2 writing.
- Add physical `units_per_batch` flow quantities, ratio-aware capacity propagation, and per-flow conservation ledgers.
- Add deterministic `fifo-fair`, `priority`, and `shortest-cycle` dispatch policies through Python and CLI scenarios.
- Add repeating weekly machine calendars with off-shift pause/resume semantics and capacity adjustment.
- Add `MIR030` calendar and `MIR031` flow-quantity diagnostics.
- Add deterministic design-space sweeps, ranked recommendations, and sensitivity analysis.
- Add the canonical `.mir` authoring DSL with source-located errors and v0.2 round trips.
- Add deterministic, self-contained factory and comparison HTML reports.
- Add a backend registry and safety-labeled IEC 61131-3 Structured Text skeleton emitter.
- Add CLI commands and canonical examples for every v0.2 layer.

## 0.1.0

- Define the Machine, Operation, MaterialFlow, and Signal primitives.
- Add version-gated, canonical JSON serialization and JSON Schema export.
- Add compiler-style structural and semantic validation diagnostics.
- Add dependency-aware topology and analytic capacity passes.
- Add deterministic synthetic serial, assembly, unbalanced, and rework factories.
- Add a seeded discrete-event simulator with finite and synchronous buffers, setup, transport, yield, arrival, and downtime behavior.
- Add paired-replication capacity comparison reports.
- Add the `mir` CLI and normative v0.1 specification.
