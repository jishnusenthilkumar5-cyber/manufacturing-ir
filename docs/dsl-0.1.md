# Manufacturing IR DSL 0.1

The `.mir` DSL is authoring syntax for Manufacturing IR 0.2. JSON remains the canonical storage and interchange format.

## Document shape

A document declares one factory and any number of the four IR primitives:

```text
factory "line-01" name "Line 01" {
  schema_version = "0.2.0"
  provenance = authored

  machine m1 {
    class = "cnc"
    capabilities = [mill]
    stations = 2
    setup = 5s
    availability(mtbf=900s, mttr=100s)
  }

  operation op1 {
    kind = "mill"
    on = [m1]
    cycle = normal(30s, 2s)
    yield = 0.98
  }

  flow inlet { "part" -> op1 cap=10 }
  flow outlet { "part" op1 -> }
}
```

Whitespace is insignificant. `#` starts a comment outside a quoted string. IDs can be bare identifiers or JSON strings.

## Values

- Durations accept `s`, `min`, or `h` and compile to seconds.
- Cycle distributions are `constant`, `uniform`, `normal`, and `exponential`.
- Strings use JSON quoting and escaping.
- `attrs`, `calendar`, and enum-state mappings use JSON object or array syntax.
- Canonical output uses stable entity ordering, field ordering, numeric rendering, and a trailing newline.

## Factory fields

- `name`
- `description`
- `provenance`: `authored`, `synthetic`, or `reconstructed`
- `source`
- `schema_version` (aliases: `schema`, `version`)

## Machine fields

- `name`
- `class` or `machine_class`
- `capabilities`
- `stations` or `num_stations`
- `setup` or `setup_time_s`
- `availability(mtbf=..., mttr=...)`, or `availability = null`
- `calendar`: a JSON array of `{day, start_s, end_s}` objects
- `attrs`

## Operation fields

- `name`
- `kind`
- `on` or `machines`
- `cycle` or `cycle_time`
- `yield` or `yield_fraction`
- `batch` or `batch_size`
- `priority`
- `attrs`

## Flow fields

A flow body begins with `MATERIAL [FROM_OPERATION] -> [TO_OPERATION]`, followed by:

- `port` or `input_port`
- `weight` or `routing_weight`
- `cap` or `buffer_capacity`
- `transport` or `transport_time_s`
- `units` or `units_per_batch`

## Signal fields

- `tag`
- `machine`
- `dtype`: `bool`, `int`, `float`, or `enum`
- `semantic`: a Manufacturing IR signal semantic
- `states` or `enum_states`
- `unit`

## CLI

```bash
mir compile examples/line.mir -o line.json
mir decompile line.json -o canonical.mir
```

Parse errors include source name, line, column, offending line, and a caret. Syntax and unreadable-input failures exit `2`; semantically invalid factories exit `1`.

The round-trip invariant is:

```text
compile(decompile(factory)) == factory
```

## Scope

The DSL describes `Factory` data only. Scenario-level settings such as the dispatch policy
(`fifo-fair`, `priority`, `shortest-cycle`), horizon, warmup, seed, and replication count are
not part of the factory document and are therefore not representable in `.mir` source; supply
them through the CLI options or the `Scenario` Python API. Operation `priority` is factory
data and does round-trip.
