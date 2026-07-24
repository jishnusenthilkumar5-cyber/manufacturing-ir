# Manufacturing IR Specification 0.2

**Status:** normative
**Schema version:** `0.2.0`
**Default time unit:** second
**Default rate unit:** unit/hour

## 1. Scope

Manufacturing IR 0.2 extends version 0.1 with physical batch quantities, deterministic dispatch policy, and weekly machine calendars. The four domain primitives remain `Machine`, `Operation`, `MaterialFlow`, and `Signal`. Unless this document changes a rule explicitly, Manufacturing IR 0.1 semantics remain normative.

## 2. Compatibility

Readers MUST accept `0.1.0` and `0.2.0` documents. A `0.1.0` document is upgraded in memory by applying these defaults:

- `Machine.calendar = []`
- `Operation.priority = 0`
- `MaterialFlow.units_per_batch = 1`

These defaults preserve version 0.1 execution. Writers MUST emit canonical `0.2.0` documents. Unsupported versions MUST fail before model validation with a readable compatibility error. Canonical serialization remains sorted, null-omitting, UTF-8 JSON with two-space indentation and a final newline.

## 3. Machine calendars

`Machine` adds:

| Field | Type | Default | Semantics |
|---|---|---:|---|
| `calendar` | `ShiftWindow[]` | `[]` | Repeating weekly periods during which every station on the machine is on shift. |

A `ShiftWindow` contains:

| Field | Type | Semantics |
|---|---|---|
| `day` | integer | Day of week, where `0` is Monday and `6` is Sunday. |
| `start_s` | finite number | Seconds from the start of the selected day, inclusive. |
| `end_s` | finite number | Seconds from the start of the selected day, exclusive. |

A valid window MUST satisfy `0 <= day <= 6` and `0 <= start_s < end_s <= 86400`. Windows on the same machine and day MUST NOT overlap. Adjacent windows are valid. Overnight shifts MUST be represented as two windows on adjacent days. An empty calendar means continuously on shift.

Calendars repeat every 604800 seconds. Simulation time zero is Monday at 00:00. Setup or processing interrupted by the end of a shift pauses with its remaining duration and resumes at the next shift start. Output retained by a blocked station cannot transfer while that station is off shift. Off-shift state takes reporting precedence over idle, blocked, starved, setup, busy, and down; reliability repair events may still advance in wall-clock time.

Machine state metrics add `offshift`. State fractions across `busy`, `idle`, `blocked`, `starved`, `setup`, `down`, and `offshift` MUST sum to one. Generated default machine-state signals SHOULD map `offshift` to integer `6` after the version 0.1 six-state vocabulary.

Analytic capacity multiplies station availability by the fraction of the week covered by valid, unioned shift windows.

## 4. Operation priority and dispatch

`Operation` adds:

| Field | Type | Default | Semantics |
|---|---|---:|---|
| `priority` | integer | `0` | Relative strict-priority dispatch rank; larger values run first. |

`Scenario.dispatch` selects one of:

| Policy | Ordering |
|---|---|
| `fifo-fair` | Least recently started operation, then operation ID. |
| `priority` | Larger `Operation.priority`, then least recently started, then operation ID. |
| `shortest-cycle` | Smaller mean cycle time, then least recently started, then operation ID. |

The default is `fifo-fair`, preserving version 0.1 behavior. Policies are deterministic for a fixed factory, scenario, and seed. Priority and shortest-cycle policies are strict and MAY starve lower-ranked operations that remain simultaneously eligible.

## 5. Physical batch quantities

`MaterialFlow` adds:

| Field | Type | Default | Semantics |
|---|---|---:|---|
| `units_per_batch` | integer >= 1 | `1` | Physical flow units transferred for each operation batch unit. |

For operation `O` and adjacent flow `F`, one cycle consumes or produces:

```text
quantity(O, F) = O.batch_size * F.units_per_batch
```

Every required inbound flow must contain its complete quantity before an operation can start. One selected alternative satisfies a named input port. A successful cycle emits the complete quantity on each selected output material route. Routing weights select a route but do not scale its quantity. A finite buffer accepts a transfer only when the complete quantity fits. A synchronous flow transfers the complete quantity directly.

Flows sharing one input port are alternatives and MUST have equal `units_per_batch`. Same-material output routing alternatives from one operation MUST have equal `units_per_batch`. A positive finite buffer fed by an operation MUST be large enough for one complete produced quantity.

For a single-outlet DAG, analytic capacity propagates one physical outlet unit backward. Required successful cycles equal required output-flow units divided by produced quantity; yield inflates attempted cycles; each inbound requirement equals attempted cycles multiplied by its consumed quantity. The analysis artifact exposes `flow_units_per_output` and `operation_cycles_per_unit`.

## 6. Conservation

Version 0.2 replaces the one-for-one scalar token assumption with a per-flow ledger. For every flow over the measurement window:

```text
produced_delta - consumed_delta - (ending_inventory - starting_inventory) = 0
```

Flow inventory includes buffered and blocked pending units. Boundary arrivals are production on inlet flows; downstream starts are consumption. Operation completion is production on selected output flows; factory shipment is consumption on outlet flows. Material transformations therefore do not require unrelated materials to share a scalar unit.

`ReplicationMetrics.conservation_by_flow` contains the signed residual for every flow. `conservation_error` is the sum of absolute per-flow residuals and MUST be zero for a correctly executed model. `input_units` and `output_units` remain physical boundary counts and need not be equal for assembly, split, or conversion operations.

## 7. Validation diagnostics

Version 0.2 adds:

| Code | Severity | Meaning |
|---|---|---|
| `MIR030` | error | Calendar window is out of range, empty/reversed, or overlaps another window on the same machine and day. |
| `MIR031` | error | Flow quantities conflict across alternatives or cannot fit one produced batch in a positive finite buffer. |

Schema constraints reject non-integer or nonpositive `units_per_batch` values before semantic validation. A factory with an error-severity `MIR030` or `MIR031` diagnostic is not executable.

## 8. Determinism and conformance

A conforming implementation MUST satisfy all of the following:

1. A version 0.1 document loaded with version 0.2 defaults retains its version 0.1 simulation metrics for the same scenario and seed, excluding newly added zero-valued metric dimensions.
2. Canonical version 0.2 output is byte-stable across load/write cycles.
3. Fixed-seed simulations are byte-for-byte reproducible.
4. Per-flow conservation residuals are zero for valid serial, assembly, and rework fixtures.
5. A machine scheduled on shift for exactly half of every week has half its always-on analytic capacity; a deterministic continuously supplied simulation converges to the same result.
6. Every dispatch policy produces deterministic ordering, and factories with competing eligible operations can observe different policy outcomes.
