# Changelog

All notable changes to Manufacturing IR are documented here.

## Unreleased

- Add IR schema 0.2 with backward-compatible 0.1 loading and canonical 0.2 writing.
- Add physical `units_per_batch` flow quantities, ratio-aware capacity propagation, and per-flow conservation ledgers.
- Add deterministic `fifo-fair`, `priority`, and `shortest-cycle` dispatch policies through Python and CLI scenarios.
- Add repeating weekly machine calendars with off-shift pause/resume semantics and capacity adjustment.
- Add `MIR030` calendar and `MIR031` flow-quantity diagnostics.

## 0.1.0

- Define the Machine, Operation, MaterialFlow, and Signal primitives.
- Add version-gated, canonical JSON serialization and JSON Schema export.
- Add compiler-style structural and semantic validation diagnostics.
- Add dependency-aware topology and analytic capacity passes.
- Add deterministic synthetic serial, assembly, unbalanced, and rework factories.
- Add a seeded discrete-event simulator with finite and synchronous buffers, setup, transport, yield, arrival, and downtime behavior.
- Add paired-replication capacity comparison reports.
- Add the `mir` CLI and normative v0.1 specification.
