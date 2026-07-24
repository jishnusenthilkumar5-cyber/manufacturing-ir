# Manufacturing IR Specification 0.1

**Status:** normative
**Schema version:** `0.1.0`
**Default time unit:** second
**Default rate unit:** unit/hour

## 1. Scope

Manufacturing IR 0.1 is a canonical semantic model of a production system. It has exactly four domain primitives:

1. `Machine` — a capacity-bearing physical resource.
2. `Operation` — a material transformation or inspection step.
3. `MaterialFlow` — a directed material path and buffer boundary.
4. `Signal` — a semantic interpretation of a raw automation tag.

`Factory` is the versioned document container. Metadata, tagged probability distributions, diagnostics, scenarios, and analysis results support the primitives but are not additional factory primitives.

Scheduling, operators, optimization, business logic, BOMs, persistence, and source-system integration are outside this version.

## 2. Conformance language

The terms **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are normative. A document is structurally valid when it parses against the Pydantic/JSON schema and emits no error-severity structural diagnostics. It is semantically valid when it additionally emits no error-severity semantic diagnostics.

Warnings identify suspicious but executable models. Informational diagnostics identify recognized constructs such as buffered rework loops.

## 3. Identity and references

Every entity has an `id`. IDs MUST match:

```text
^[a-z0-9][a-z0-9_-]*$
```

IDs are case-sensitive and MUST be unique within their primitive collection. References contain IDs, never array positions or embedded entities. Renaming an ID requires updating every reference.

## 4. Factory document

| Field | Type | Required | Semantics |
|---|---|---:|---|
| `schema_version` | literal `0.1.0` | yes | Reader compatibility gate. |
| `meta` | `FactoryMeta` | yes | Stable identity and provenance. |
| `machines` | `Machine[]` | no | Defaults to empty. |
| `operations` | `Operation[]` | no | Defaults to empty. |
| `flows` | `MaterialFlow[]` | no | Defaults to empty. |
| `signals` | `Signal[]` | no | Defaults to empty. |

`FactoryMeta` contains `id`, nonempty `name`, optional `description`, and `provenance`. Provenance `kind` is one of `authored`, `synthetic`, or `reconstructed`; `source` is free text identifying the origin.

## 5. Machine

| Field | Type | Default | Semantics |
|---|---|---:|---|
| `id` | MachineId | — | Stable resource identity. |
| `name` | nonempty string | — | Human-facing name. |
| `machine_class` | nonempty string | — | Open taxonomy/template hook such as `cnc_mill`. |
| `capabilities` | nonempty `string[]` | — | Operation kinds the machine can execute. |
| `num_stations` | integer ≥ 1 | `1` | Parallel identical processing positions. |
| `setup_time_s` | number ≥ 0 | `0` | Changeover paid when a station switches operation kind. |
| `availability` | object or null | null | Optional `mtbf_s` and `mttr_s`. Both MUST be positive to execute. |
| `attrs` | object | `{}` | Uninterpreted extension data. Passes MUST NOT infer core semantics from it. |

A station alternates independently between up and down when availability is present. Simulator up and repair durations are exponential with the declared means. Interrupted setup and processing resume after repair.

## 6. Operation

| Field | Type | Default | Semantics |
|---|---|---:|---|
| `id` | OperationId | — | Stable process-step identity. |
| `name` | nonempty string | — | Human-facing name. |
| `kind` | nonempty string | — | Required machine capability. |
| `machines` | `MachineId[]` | — | Eligible resources. At least one is required semantically. |
| `cycle_time` | Distribution | — | Processing duration per batch. |
| `yield_fraction` | number in `(0,1]` | `1` | Probability that a completed batch produces good output. |
| `batch_size` | integer ≥ 1 | `1` | Units consumed from each required input port and emitted on the selected output path. |
| `attrs` | object | `{}` | Uninterpreted extension data. |

### 6.1 Distributions

Distributions are discriminated by `kind`:

| Kind | Fields | Mean used by capacity pass |
|---|---|---:|
| `constant` | `value_s > 0` | `value_s` |
| `uniform` | `0 < low_s <= high_s` | `(low_s + high_s) / 2` |
| `normal` | `mean_s > 0`, `std_s >= 0` | `mean_s` |
| `exponential` | `mean_s > 0` | `mean_s` |

Normal samples are truncated at zero. Every simulation replication uses an explicitly seeded pseudo-random stream.

## 7. MaterialFlow

| Field | Type | Default | Semantics |
|---|---|---:|---|
| `id` | FlowId | — | Stable path/buffer identity. |
| `material` | nonempty string | — | Open material identity. |
| `from_op` | OperationId or null | null | Producer; null denotes a factory inlet. |
| `to_op` | OperationId or null | null | Consumer; null denotes a factory outlet. |
| `input_port` | nonempty string or null | null | Flows sharing a port are alternative inputs; ungrouped flows are independently required. |
| `routing_weight` | number > 0 | `1` | Relative probability among same-material outputs. |
| `buffer_capacity` | integer ≥ 0 or null | null | `null` unbounded, `0` synchronous handoff, positive finite capacity. |
| `transport_time_s` | number ≥ 0 | `0` | Delay before completed output may transfer. |

Both endpoints MUST NOT be null. An inlet has only `to_op`; an outlet has only `from_op`; an internal flow has both.

### 7.1 Input semantics

For each operation:

- Every inbound flow without `input_port` is an independent required input.
- Inbound flows with the same `input_port` are alternatives; one available flow satisfies that port.
- A cycle consumes `batch_size` units from every required ungrouped flow and from one flow in every named port.
- When multiple alternatives are available, internal recirculation is consumed before boundary supply, then IDs break ties. This makes rework drain before new feed and is deterministic.
- An inlet without a configured scenario arrival rate is infinite supply. A configured rate creates deterministic periodic arrivals into its buffer.

### 7.2 Output semantics

On a successful operation cycle:

- Outgoing flows are grouped by `material`.
- The operation emits `batch_size` units for each distinct material group.
- A single flow in a material group is selected directly.
- Multiple same-material flows are alternatives selected with probability proportional to `routing_weight`.
- A failed-yield batch emits no output and records `batch_size` scrap units.

This supports assembly through multiple input ports, co-products through distinct output materials, and probabilistic routing/rework through same-material outputs.

### 7.3 Blocking and transport

A positive-capacity destination accepts a complete batch only when the batch fits. A full destination blocks the producing station. Capacity `0` stores no token: the producer remains blocked until the downstream operation starts and consumes the handoff. `null` capacity is unbounded.

Output cannot transfer before `transport_time_s`. In 0.1 the producing station retains the output position during that delay and is classified as blocked.

## 8. Signal

| Field | Type | Default | Semantics |
|---|---|---:|---|
| `id` | SignalId | — | Stable semantic signal identity. |
| `tag` | nonempty string | — | Raw source-system tag. |
| `machine` | MachineId | — | Owning resource. |
| `dtype` | `bool`, `int`, `float`, or `enum` | — | Decoded value type. |
| `semantic` | vocabulary value | — | Meaning attached to the raw tag. |
| `enum_states` | `string → int` or null | null | Required for `machine_state`. |
| `unit` | string or null | null | Engineering unit, principally for measurements. |

Semantic vocabulary: `machine_state`, `cycle_count`, `good_count`, `scrap_count`, `alarm`, `measurement`, `custom`.

Signals do not affect v0.1 execution. They preserve the mapping needed by future brownfield frontends and generated automation backends.

## 9. Canonical JSON

Canonical serialization MUST:

1. Sort `machines`, `operations`, `flows`, and `signals` lexicographically by `id`.
2. Sort object keys lexicographically.
3. Omit null-valued fields.
4. Use UTF-8, two-space indentation, and a final newline.
5. Preserve semantically meaningful list order outside entity collections.

A canonical implementation MUST satisfy:

```text
dumps(loads(dumps(factory))) == dumps(factory)
```

## 10. Validation diagnostics

| Code | Severity | Meaning |
|---|---|---|
| `MIR001` | error | Duplicate entity ID within one collection. |
| `MIR002` | error | Operation references an unknown machine. |
| `MIR003` | error | Flow references an unknown operation. |
| `MIR004` | error | Flow has neither endpoint. |
| `MIR005` | error | Operation has no eligible machine. |
| `MIR006` | error | Signal references an unknown machine. |
| `MIR007` | error | Signal tag is duplicated on one machine. |
| `MIR010` | warning | Operation has no material flows. |
| `MIR011` | warning | Operation is unreachable from every inlet. |
| `MIR012` | error/info | Fully synchronous cycle deadlocks; buffered cycle is recognized as rework. |
| `MIR020` | error | Eligible machine lacks the operation capability. |
| `MIR021` | warning | Machine is unused by all operations. |
| `MIR022` | error | Machine-state signal lacks enum mapping. |
| `MIR023` | error | Count signal does not use integer dtype. |
| `MIR024` | warning | Measurement unit is outside the documented vocabulary. |
| `MIR025` | error | MTBF or MTTR is nonpositive. |
| `MIR026` | warning | Boundary material has no process-flow continuity. |
| `MIR100` | warning | Analytic capacity is approximate for the topology. |

Field constraints such as ID syntax, positive cycle time, yield range, and batch size are schema errors rather than MIR diagnostics.

## 11. Analysis semantics

The topology pass emits adjacency, reverse adjacency, inlets, outlets, deterministic topological order, strongly connected components, inlet reachability, and serial-line classification.

For a single-outlet DAG, the capacity pass propagates one shipped unit backward. It inflates expected cycles by operation yield and batch size, converts cycles to mean busy seconds, distributes alternative-machine load by effective station capacity, and applies steady-state availability `mtbf / (mtbf + mttr)`. The machine with greatest effective seconds per shipped unit is the bottleneck; its reciprocal is the line throughput upper bound.

Finite buffers, setup interactions, routing, and stochastic realization require simulation. Cyclic or multi-outlet models emit `MIR100` and receive only an approximate local bound.

## 12. Simulation and metrics

The simulator is a terminating discrete-event model over a finite horizon. An operation starts when every input group is satisfied and an eligible up station is free. Events at the same timestamp are ordered deterministically.

Each station reports fractions of measured time in `busy`, `idle`, `blocked`, `starved`, `setup`, and `down`. Fractions sum to one. Other outputs include per-outlet throughput, operation cycles and scrap, time-weighted buffer occupancy, ending WIP, and a serial-flow conservation residual.

Warmup discards counters and integrated state before `warmup_s`. Conservation over a measurement window is:

```text
measured input = measured output + measured scrap + (ending WIP - starting WIP)
```

This scalar token invariant applies to one-for-one flows. Assembly and co-product models can change token cardinality; future versions may add dimensional material quantities.

## 13. Compatibility

Readers MUST reject unsupported `schema_version` values with a clear compatibility error. Version 0.1 defines no migration protocol. Producers MUST NOT silently relabel a document from another version.
