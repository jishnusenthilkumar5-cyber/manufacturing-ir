from __future__ import annotations

import statistics
from collections import defaultdict
from pathlib import Path

from mir.compare import ComparisonReport, compare_factories
from mir.core.model import Factory, MaterialFlow
from mir.passes import Diagnostic, Severity, analyze_factory, validate_factory
from mir.passes.capacity import CapacityAnalysis
from mir.passes.topology import TopologyAnalysis
from mir.report.template import escaped, render_document
from mir.sim import Scenario, SimulationResult, simulate


STATE_ORDER = ("busy", "idle", "blocked", "starved", "setup", "down", "offshift")
STATE_COLORS = {
    "busy": "#1570ef",
    "idle": "#667085",
    "blocked": "#f79009",
    "starved": "#7f56d9",
    "setup": "#0891b2",
    "down": "#d92d20",
    "offshift": "#344054",
}
NODE_WIDTH = 220
NODE_HEIGHT = 118


class ReportError(ValueError):
    pass


def _number(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def _percent(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}%}"


def _short(value: object, limit: int) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _validate(factory: Factory, role: str) -> tuple[Diagnostic, ...]:
    result = validate_factory(factory)
    errors = sorted(
        (item for item in result.diagnostics if item.severity is Severity.ERROR),
        key=lambda item: (item.code, item.entities, item.message, item.hint),
    )
    if errors:
        details = "; ".join(f"{item.code}: {item.message}" for item in errors)
        raise ReportError(f"{role} factory is invalid: {details}")
    return result.diagnostics


def _state_names(states_by_machine: dict[str, dict[str, float]]) -> tuple[str, ...]:
    present = {state for states in states_by_machine.values() for state in states}
    return STATE_ORDER + tuple(sorted(present - set(STATE_ORDER)))


def _dominant_state(fractions: dict[str, float]) -> str:
    states = STATE_ORDER + tuple(sorted(set(fractions) - set(STATE_ORDER)))
    if not states:
        return "idle"
    order = {state: index for index, state in enumerate(states)}
    return max(states, key=lambda state: (fractions.get(state, 0.0), -order[state]))


def _state_class(state: str) -> str:
    return state if state in STATE_COLORS else "other"


def _meta_item(label: str, value: object) -> str:
    return f"<div class=\"meta-item\"><dt>{escaped(label)}</dt><dd>{escaped(value)}</dd></div>"


def _panel(title: str, content: str) -> str:
    return f'<article class="panel"><h3 class="panel-title">{escaped(title)}</h3>{content}</article>'


def _section(title: str, note: str, content: str) -> str:
    return (
        '<section class="section">'
        f'<div class="section-heading"><h2>{escaped(title)}</h2><p>{escaped(note)}</p></div>'
        f"{content}</section>"
    )


def _kpi(label: str, value: str, note: str, tone: str = "") -> str:
    tone_class = f" {tone}" if tone else ""
    return (
        f'<div class="kpi-card{tone_class}">'
        f'<span class="kpi-label">{escaped(label)}</span>'
        f'<strong class="kpi-value">{escaped(value)}</strong>'
        f'<span class="kpi-note">{escaped(note)}</span></div>'
    )


def _scenario_details(scenario: Scenario) -> str:
    arrivals = ", ".join(
        f"{flow_id}: {_number(rate)} units/h"
        for flow_id, rate in sorted(scenario.arrival_rates_per_hour.items())
    ) or "Unconstrained inlets"
    content = "".join(
        [
            _meta_item("Horizon", f"{_number(scenario.horizon_s / 3600)} h"),
            _meta_item("Warm-up", f"{_number(scenario.warmup_s / 3600)} h"),
            _meta_item("Replications", scenario.replications),
            _meta_item("Seed range", f"{scenario.seed}–{scenario.seed + scenario.replications - 1}"),
            _meta_item("Measurement", f"{_number(scenario.measurement_s / 3600)} h per replication"),
            _meta_item("Dispatch", scenario.dispatch.value),
            _meta_item("Arrivals", arrivals),
        ]
    )
    return f'<dl class="scenario-grid">{content}</dl>'


def _state_bar(fractions: dict[str, float], states: tuple[str, ...]) -> str:
    segments = "".join(
        f'<span class="state-segment state-{_state_class(state)}" '
        f'style="width:{max(0.0, min(100.0, fractions.get(state, 0.0) * 100.0)):.6f}%"></span>'
        for state in states
        if fractions.get(state, 0.0) > 0
    )
    detail = " · ".join(
        f"{escaped(state)} {_percent(fractions.get(state, 0.0))}" for state in states
    )
    return f'<div class="state-bar" aria-label="Machine state fractions">{segments}</div><div class="muted">{detail}</div>'


def _topology_positions(
    factory: Factory, topology: TopologyAnalysis
) -> tuple[list[str], dict[str, tuple[float, float]], int, int]:
    operation_ids = set(factory.operation_map())
    ordered = []
    for operation_id in topology.topological_order:
        if operation_id in operation_ids and operation_id not in ordered:
            ordered.append(operation_id)
    ordered.extend(sorted(operation_ids - set(ordered)))
    topological = set(topology.topological_order)
    ranks: dict[str, int] = {}
    for operation_id in ordered:
        predecessors = [
            predecessor
            for predecessor in topology.reverse_adjacency.get(operation_id, ())
            if predecessor in ranks
        ]
        if operation_id in topological:
            ranks[operation_id] = max((ranks[item] + 1 for item in predecessors), default=0)
        else:
            ranks[operation_id] = max(ranks.values(), default=-1) + 1
    groups: defaultdict[int, list[str]] = defaultdict(list)
    for operation_id in ordered:
        groups[ranks[operation_id]].append(operation_id)
    row_count = max((len(group) for group in groups.values()), default=1)
    positions: dict[str, tuple[float, float]] = {}
    for rank in sorted(groups):
        group = groups[rank]
        offset = (row_count - len(group)) * 72
        for index, operation_id in enumerate(group):
            positions[operation_id] = (120 + rank * 310, 50 + offset + index * 144)
    rank_count = max(ranks.values(), default=0) + 1
    width = max(720, 240 + rank_count * 310)
    height = max(250, 110 + row_count * 144 + len(factory.flows) * 5)
    return ordered, positions, width, height


def _arrow(x: float, y: float, direction: str) -> str:
    points = (
        f"{x:.1f},{y:.1f} {x - 9:.1f},{y - 5:.1f} {x - 9:.1f},{y + 5:.1f}"
        if direction == "right"
        else f"{x:.1f},{y:.1f} {x + 9:.1f},{y - 5:.1f} {x + 9:.1f},{y + 5:.1f}"
    )
    return f'<polygon class="flow-arrow" points="{points}"></polygon>'


def _flow_label(flow: MaterialFlow) -> str:
    capacity = (
        "handoff"
        if flow.buffer_capacity == 0
        else "unbounded"
        if flow.buffer_capacity is None
        else f"cap {flow.buffer_capacity}"
    )
    return _short(
        f"{flow.id} | {flow.material} | {flow.units_per_batch}/batch | {capacity}",
        42,
    )


def _flow_art(flow: MaterialFlow, index: int, positions: dict[str, tuple[float, float]]) -> str:
    source = positions.get(flow.from_op or "")
    target = positions.get(flow.to_op or "")
    if source and target and flow.from_op == flow.to_op:
        x, y = source
        start_x, end_x = x + 160, x + 60
        top = max(15.0, y - 48 - index * 3)
        path = f"M {start_x:.1f} {y:.1f} C {start_x:.1f} {top:.1f}, {end_x:.1f} {top:.1f}, {end_x:.1f} {y:.1f}"
        arrow = _arrow(end_x, y, "left")
        label_x, label_y = x + 110, top - 4
    elif source and target:
        source_x, source_y = source
        target_x, target_y = target
        if target_x > source_x:
            start_x, start_y = source_x + NODE_WIDTH, source_y + NODE_HEIGHT / 2
            end_x, end_y = target_x, target_y + NODE_HEIGHT / 2
            middle = (start_x + end_x) / 2
            path = f"M {start_x:.1f} {start_y:.1f} C {middle:.1f} {start_y:.1f}, {middle:.1f} {end_y:.1f}, {end_x:.1f} {end_y:.1f}"
            arrow = _arrow(end_x, end_y, "right")
        else:
            start_x, start_y = source_x, source_y + NODE_HEIGHT / 2
            end_x, end_y = target_x + NODE_WIDTH, target_y + NODE_HEIGHT / 2
            bend = max(start_y, end_y) + 72 + index * 5
            path = f"M {start_x:.1f} {start_y:.1f} C {start_x - 70:.1f} {bend:.1f}, {end_x + 70:.1f} {bend:.1f}, {end_x:.1f} {end_y:.1f}"
            arrow = _arrow(end_x, end_y, "left")
        label_x, label_y = (start_x + end_x) / 2, (start_y + end_y) / 2 - 9
    elif target:
        target_x, target_y = target
        start_x, end_x, end_y = target_x - 82, target_x, target_y + NODE_HEIGHT / 2
        path = f"M {start_x:.1f} {end_y:.1f} L {end_x:.1f} {end_y:.1f}"
        arrow = _arrow(end_x, end_y, "right")
        label_x, label_y = (start_x + end_x) / 2, end_y - 9
    elif source:
        source_x, source_y = source
        start_x, end_x, end_y = source_x + NODE_WIDTH, source_x + NODE_WIDTH + 82, source_y + NODE_HEIGHT / 2
        path = f"M {start_x:.1f} {end_y:.1f} L {end_x:.1f} {end_y:.1f}"
        arrow = _arrow(end_x, end_y, "right")
        label_x, label_y = (start_x + end_x) / 2, end_y - 9
    else:
        return ""
    label = escaped(_flow_label(flow))
    return f'<path class="flow-line" d="{path}"></path>{arrow}<text class="flow-label" x="{label_x:.1f}" y="{label_y:.1f}" text-anchor="middle">{label}</text>'


def _render_topology(
    factory: Factory,
    topology: TopologyAnalysis,
    capacity: CapacityAnalysis,
    simulation: SimulationResult,
) -> str:
    ordered, positions, width, height = _topology_positions(factory, topology)
    operations = factory.operation_map()
    states_by_machine = simulation.summary.machine_state_fractions_mean
    flows = "".join(
        _flow_art(flow, index, positions)
        for index, flow in enumerate(sorted(factory.flows, key=lambda item: item.id))
    )
    nodes: list[str] = []
    for operation_id in ordered:
        operation = operations[operation_id]
        x, y = positions[operation_id]
        is_bottleneck = capacity.bottleneck_machine in operation.machines
        node_class = "node-card is-bottleneck" if is_bottleneck else "node-card"
        badges: list[str] = []
        for badge_index, machine_id in enumerate(sorted(operation.machines)[:2]):
            state = _dominant_state(states_by_machine.get(machine_id, {}))
            badge_x = x + 10 + badge_index * 101
            color = STATE_COLORS.get(state, "#475467")
            badges.append(
                f'<g><title>{escaped(machine_id)}: dominant state {escaped(state)}</title>'
                f'<rect x="{badge_x:.1f}" y="{y + 84:.1f}" width="96" height="23" rx="6" fill="{color}"></rect>'
                f'<text x="{badge_x + 48:.1f}" y="{y + 100:.1f}" text-anchor="middle" fill="#ffffff" font-size="10" font-weight="700">{escaped(_short(machine_id, 14))}</text></g>'
            )
        if len(operation.machines) > 2:
            badges.append(
                f'<text class="node-subtitle" x="{x + NODE_WIDTH - 12:.1f}" y="{y + 80:.1f}" text-anchor="end">+{len(operation.machines) - 2} machines</text>'
            )
        bottleneck = (
            f'<text class="node-badge" x="{x + NODE_WIDTH - 10:.1f}" y="{y + 68:.1f}" text-anchor="end">BOTTLENECK</text>'
            if is_bottleneck
            else ""
        )
        nodes.append(
            f'<g><rect class="{node_class}" x="{x:.1f}" y="{y:.1f}" width="{NODE_WIDTH}" height="{NODE_HEIGHT}" rx="11" fill="#ffffff"></rect>'
            f'<text class="node-title" x="{x + 12:.1f}" y="{y + 23:.1f}">{escaped(_short(operation.id, 29))}</text>'
            f'<text class="node-subtitle" x="{x + 12:.1f}" y="{y + 43:.1f}">{escaped(_short(operation.name, 31))}</text>'
            f'<text class="node-subtitle" x="{x + 12:.1f}" y="{y + 63:.1f}">{escaped(operation.kind)} | {_number(operation.cycle_time.mean_seconds())} s</text>'
            f'{bottleneck}{"".join(badges)}</g>'
        )
    svg = (
        f'<div class="topology-wrap"><svg class="topology-svg" viewBox="0 0 {width} {height}" role="img" aria-label="Factory operation and material-flow topology">'
        f'<title>Topology for {escaped(factory.meta.name)}</title>{flows}{"".join(nodes)}</svg></div>'
    )
    return _panel("Operation and material-flow topology", svg)


def _factory_kpis(capacity: CapacityAnalysis, simulation: SimulationResult) -> str:
    summary = simulation.summary
    bound = capacity.throughput_upper_bound_units_per_hour
    measured = summary.throughput_units_per_hour_mean
    bound_value = f"{_number(bound)} units/h" if bound is not None else "Unavailable"
    bound_note = "Exact analytic result" if capacity.exact else "Approximate analytic result"
    attainment = measured / bound if bound is not None and bound > 0 else None
    attainment_value = _percent(attainment) if attainment is not None else "Unavailable"
    attainment_note = "Measured throughput divided by bound" if attainment is not None else "No finite analytic bound"
    scrap = sum(summary.scrap_by_operation_mean.values())
    cards = [
        _kpi(
            "Measured throughput",
            f"{_number(measured)} units/h",
            f"± {_number(summary.throughput_units_per_hour_stdev)} across {simulation.scenario.replications} replication(s)",
            "is-good" if measured > 0 else "is-warning",
        ),
        _kpi("Analytic upper bound", bound_value, bound_note),
        _kpi("Bound attainment", attainment_value, attainment_note),
        _kpi(
            "Bottleneck machine",
            capacity.bottleneck_machine or "Unavailable",
            "Highest effective seconds per unit",
            "is-warning" if capacity.bottleneck_machine else "",
        ),
        _kpi("Ending WIP", _number(summary.ending_wip_mean), "Mean units at the horizon"),
        _kpi("Scrap", _number(scrap), "Mean units during measurement"),
    ]
    return f'<div class="kpi-grid">{"".join(cards)}</div>'


def _render_machine_states(
    factory: Factory, capacity: CapacityAnalysis, simulation: SimulationResult
) -> str:
    states_by_machine = simulation.summary.machine_state_fractions_mean
    states = _state_names(states_by_machine)
    machine_map = factory.machine_map()
    rows: list[str] = []
    for machine_id in sorted(machine_map):
        machine = machine_map[machine_id]
        fractions = states_by_machine.get(machine_id, {})
        dominant = _dominant_state(fractions)
        row_class = ' class="is-bottleneck"' if machine_id == capacity.bottleneck_machine else ""
        bottleneck = '<span class="badge is-warning">Bottleneck</span>' if machine_id == capacity.bottleneck_machine else ""
        rows.append(
            f"<tr{row_class}><td><strong>{escaped(machine.name)}</strong><br><span class=\"mono muted\">{escaped(machine_id)}</span></td>"
            f'<td><span class="badge">{escaped(dominant)}</span> {bottleneck}</td>'
            f'<td>{_state_bar(fractions, states)}</td>'
            f'<td class="number">{_percent(fractions.get("busy", 0.0))}</td>'
            f'<td class="number">{_percent(fractions.get("blocked", 0.0))}</td>'
            f'<td class="number">{_percent(fractions.get("starved", 0.0))}</td>'
            f'<td class="number">{_percent(fractions.get("down", 0.0))}</td></tr>'
        )
    table = (
        '<div class="table-wrap"><table><thead><tr><th>Machine</th><th>Dominant state</th>'
        '<th>State fractions</th><th class="number">Busy</th><th class="number">Blocked</th>'
        '<th class="number">Starved</th><th class="number">Down</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></div>"
        if rows
        else '<p class="empty-state">No machines were simulated.</p>'
    )
    legend = '<div class="legend">' + "".join(
        f'<span class="legend-item"><span class="legend-swatch state-{_state_class(state)}"></span>{escaped(state)}</span>'
        for state in states
    ) + "</div>"
    return _panel("Machine-state utilization", table + f'<div class="panel-body">{legend}</div>')


def _buffer_summary(simulation: SimulationResult) -> dict[str, tuple[float, int, float]]:
    buffer_ids = sorted(
        {
            flow_id
            for replication in simulation.replications
            for flow_id in replication.buffers
        }
    )
    result: dict[str, tuple[float, int, float]] = {}
    for flow_id in buffer_ids:
        metrics = [
            replication.buffers[flow_id]
            for replication in simulation.replications
            if flow_id in replication.buffers
        ]
        result[flow_id] = (
            _mean([item.mean_occupancy for item in metrics]),
            max((item.max_occupancy for item in metrics), default=0),
            _mean([float(item.ending_occupancy) for item in metrics]),
        )
    return result


def _render_buffers(factory: Factory, simulation: SimulationResult) -> str:
    summaries = _buffer_summary(simulation)
    flows = factory.flow_map()
    flow_ids = sorted(
        set(summaries)
        | {
            flow.id
            for flow in factory.flows
            if flow.from_op is not None and flow.to_op is not None
        }
    )
    rows: list[str] = []
    for flow_id in flow_ids:
        flow = flows.get(flow_id)
        if flow is None:
            raise ReportError(f"simulation reported unknown flow '{flow_id}'")
        metrics = summaries.get(flow_id)
        capacity = (
            "0 (synchronous)"
            if flow.buffer_capacity == 0
            else "Unbounded"
            if flow.buffer_capacity is None
            else str(flow.buffer_capacity)
        )
        mean, peak, ending = metrics if metrics is not None else (None, None, None)
        rows.append(
            f'<tr><td><strong>{escaped(flow_id)}</strong><br><span class="muted">{escaped(flow.material)}</span></td>'
            f'<td class="number">{flow.units_per_batch}</td>'
            f'<td class="number">{escaped(capacity)}</td>'
            f'<td class="number">{_number(mean) if mean is not None else "n/a"}</td>'
            f'<td class="number">{peak if peak is not None else "n/a"}</td>'
            f'<td class="number">{_number(ending) if ending is not None else "n/a"}</td></tr>'
        )
    content = (
        '<div class="table-wrap"><table><thead><tr><th>Flow buffer</th><th class="number">Units/batch</th>'
        '<th class="number">Capacity</th><th class="number">Mean occupancy</th><th class="number">Peak observed</th>'
        '<th class="number">Ending occupancy</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></div>"
        if rows
        else '<p class="empty-state">This model has no internal or scheduled-arrival buffers.</p>'
    )
    return _panel("Buffer performance", content)


def _render_flow_accounting(factory: Factory, simulation: SimulationResult) -> str:
    replications = simulation.replications
    summary = simulation.summary
    ledger = "".join(
        [
            _meta_item("Mean input units", _number(_mean([float(item.input_units) for item in replications]))),
            _meta_item("Mean output units", _number(_mean([float(item.output_units) for item in replications]))),
            _meta_item("Mean starting WIP", _number(_mean([float(item.starting_wip) for item in replications]))),
            _meta_item("Max |conservation error|", max((abs(item.conservation_error) for item in replications), default=0)),
        ]
    )
    flow_map = factory.flow_map()
    outlet_rows = "".join(
        f'<tr><td>{escaped(flow_id)}</td><td>{escaped(flow_map[flow_id].material if flow_id in flow_map else "unknown")}</td>'
        f'<td class="number">{_number(rate)} units/h</td></tr>'
        for flow_id, rate in sorted(summary.throughput_by_outlet_mean.items())
    )
    operation_map = factory.operation_map()
    scrap_rows = "".join(
        f'<tr><td>{escaped(operation_id)}</td><td>{escaped(operation_map[operation_id].name if operation_id in operation_map else "unknown")}</td>'
        f'<td class="number">{_number(value)}</td></tr>'
        for operation_id, value in sorted(summary.scrap_by_operation_mean.items())
    )
    outlets = (
        '<h4>Outlet throughput</h4><div class="table-wrap"><table><thead><tr><th>Outlet flow</th><th>Material</th>'
        '<th class="number">Mean rate</th></tr></thead><tbody>' + outlet_rows + "</tbody></table></div>"
        if outlet_rows
        else '<h4>Outlet throughput</h4><p class="empty-state">No outlet throughput was observed.</p>'
    )
    scrap = (
        '<h4>Scrap by operation</h4><div class="table-wrap"><table><thead><tr><th>Operation</th><th>Name</th>'
        '<th class="number">Mean scrap units</th></tr></thead><tbody>' + scrap_rows + "</tbody></table></div>"
        if scrap_rows
        else '<h4>Scrap by operation</h4><p class="empty-state">No operations were simulated.</p>'
    )
    return _panel(
        "Material accounting",
        f'<div class="panel-body"><dl class="meta-grid">{ledger}</dl>{outlets}{scrap}</div>',
    )


def _render_diagnostics(diagnostics: tuple[Diagnostic, ...]) -> str:
    severity_order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
    ordered = sorted(
        diagnostics,
        key=lambda item: (
            severity_order[item.severity],
            item.code,
            item.entities,
            item.message,
            item.hint,
        ),
    )
    if not ordered:
        return _panel("Diagnostics", '<p class="empty-state">No analysis diagnostics.</p>')
    items: list[str] = []
    for item in ordered:
        severity = item.severity.value
        entities = (
            f'<p><strong>Entities:</strong> {escaped(", ".join(item.entities))}</p>'
            if item.entities
            else ""
        )
        hint = f'<p><strong>Guidance:</strong> {escaped(item.hint)}</p>' if item.hint else ""
        items.append(
            f'<li class="diagnostic {severity}"><div class="diagnostic-title">'
            f'<span class="badge is-{severity}">{escaped(severity)}</span>'
            f'<span class="mono">{escaped(item.code)}</span><span>{escaped(item.message)}</span></div>'
            f"{entities}{hint}</li>"
        )
    return _panel("Diagnostics", f'<div class="panel-body"><ul class="diagnostic-list">{"".join(items)}</ul></div>')


def _factory_metadata(factory: Factory, topology: TopologyAnalysis) -> str:
    description = factory.meta.description or "No description provided"
    values = "".join(
        [
            _meta_item("Factory ID", factory.meta.id),
            _meta_item("Schema", factory.schema_version),
            _meta_item("Provenance", factory.meta.provenance.kind.value),
            _meta_item("Source", factory.meta.provenance.source or "Not specified"),
            _meta_item("Machines", len(factory.machines)),
            _meta_item("Operations", len(factory.operations)),
            _meta_item("Material flows", len(factory.flows)),
            _meta_item("Topology", "Serial line" if topology.is_serial_line else "General network"),
            _meta_item("Description", description),
        ]
    )
    return f'<dl class="meta-grid">{values}</dl>'


def render_factory_report(factory: Factory, scenario: Scenario) -> str:
    _validate(factory, "input")
    analysis = analyze_factory(factory)
    topology: TopologyAnalysis = analysis.artifacts["topology"]["analysis"]
    capacity: CapacityAnalysis = analysis.artifacts["capacity"]["analysis"]
    simulation = simulate(factory, scenario)
    body = "".join(
        [
            _section("Factory definition", "Model identity and structure", _factory_metadata(factory, topology)),
            _section("Performance overview", "Simulation compared with analytic capacity", _factory_kpis(capacity, simulation)),
            _section("Process topology", "Stable layout derived from topology analysis", _render_topology(factory, topology, capacity, simulation)),
            _section("Machine behavior", "Mean state fractions across replications", _render_machine_states(factory, capacity, simulation)),
            _section(
                "Material flow",
                "Buffer behavior, WIP, throughput, and scrap",
                f'<div class="split-grid">{_render_buffers(factory, simulation)}{_render_flow_accounting(factory, simulation)}</div>',
            ),
            _section("Analysis diagnostics", "Validation and capacity findings", _render_diagnostics(analysis.diagnostics)),
            _section("Scenario", "Deterministic simulation inputs", _scenario_details(scenario)),
        ]
    )
    return render_document(
        f"{factory.meta.name} — Factory performance",
        f"Factory {factory.meta.id} · schema {factory.schema_version} · seeded simulation and analytic capacity",
        body,
    )


def _delta_class(value: float | None) -> str:
    if value is None or abs(value) < 1e-12:
        return "delta-neutral"
    return "delta-positive" if value > 0 else "delta-negative"


def _comparison_kpis(report: ComparisonReport) -> str:
    delta_percent = report.delta_percent
    delta_value = "n/a" if delta_percent is None else f"{delta_percent:+.2f}%"
    movement = (
        f"{report.bottleneck_before or 'n/a'} → {report.bottleneck_after or 'n/a'}"
    )
    cards = [
        _kpi(
            "Baseline throughput",
            f"{_number(report.baseline_throughput_mean)} units/h",
            f"± {_number(report.baseline_throughput_stdev)}",
        ),
        _kpi(
            "Variant throughput",
            f"{_number(report.variant_throughput_mean)} units/h",
            f"± {_number(report.variant_throughput_stdev)}",
            "is-good" if report.paired_delta_mean > 0 else "is-warning" if report.paired_delta_mean < 0 else "",
        ),
        _kpi(
            "Throughput change",
            delta_value,
            f"Paired delta {report.paired_delta_mean:+.2f} ± {_number(report.paired_delta_stdev)} units/h",
        ),
        _kpi("Bottleneck movement", movement, "Analytic bottleneck before and after"),
        _kpi(
            "Ending WIP",
            f"{_number(report.ending_wip_before)} → {_number(report.ending_wip_after)}",
            f"Delta {report.ending_wip_after - report.ending_wip_before:+.2f}",
        ),
        _kpi(
            "Scrap",
            f"{_number(report.scrap_before)} → {_number(report.scrap_after)}",
            f"Delta {report.scrap_after - report.scrap_before:+.2f}",
        ),
    ]
    return f'<div class="kpi-grid">{"".join(cards)}</div>'


def _comparison_metrics(report: ComparisonReport) -> str:
    percent = "n/a" if report.delta_percent is None else f"{report.delta_percent:+.2f}%"
    rows = [
        (
            "Throughput (units/h)",
            f"{_number(report.baseline_throughput_mean)} ± {_number(report.baseline_throughput_stdev)}",
            f"{_number(report.variant_throughput_mean)} ± {_number(report.variant_throughput_stdev)}",
            f"{report.paired_delta_mean:+.2f} ({percent})",
            _delta_class(report.paired_delta_mean),
        ),
        (
            "Bottleneck",
            report.bottleneck_before or "n/a",
            report.bottleneck_after or "n/a",
            "Moved" if report.bottleneck_before != report.bottleneck_after else "Unchanged",
            "delta-neutral",
        ),
        (
            "Ending WIP",
            _number(report.ending_wip_before),
            _number(report.ending_wip_after),
            f"{report.ending_wip_after - report.ending_wip_before:+.2f}",
            _delta_class(report.ending_wip_after - report.ending_wip_before),
        ),
        (
            "Scrap units",
            _number(report.scrap_before),
            _number(report.scrap_after),
            f"{report.scrap_after - report.scrap_before:+.2f}",
            _delta_class(report.scrap_after - report.scrap_before),
        ),
    ]
    body = "".join(
        f'<tr><td><strong>{escaped(metric)}</strong></td><td class="number">{escaped(before)}</td>'
        f'<td class="number">{escaped(after)}</td><td class="number {tone}">{escaped(delta)}</td></tr>'
        for metric, before, after, delta, tone in rows
    )
    table = (
        '<div class="table-wrap"><table><thead><tr><th>Metric</th><th class="number">Baseline</th>'
        '<th class="number">Variant</th><th class="number">Delta</th></tr></thead><tbody>'
        + body
        + "</tbody></table></div>"
    )
    return _panel("Before-and-after metrics", table)


def _comparison_utilization(
    baseline: Factory, variant: Factory, report: ComparisonReport
) -> str:
    baseline_machines = baseline.machine_map()
    variant_machines = variant.machine_map()
    machine_ids = sorted(
        set(report.utilization_before)
        | set(report.utilization_after)
        | set(baseline_machines)
        | set(variant_machines)
    )
    rows: list[str] = []
    for machine_id in machine_ids:
        before = report.utilization_before.get(machine_id, 0.0)
        after = report.utilization_after.get(machine_id, 0.0)
        delta = after - before
        before_name = baseline_machines[machine_id].name if machine_id in baseline_machines else "Not present"
        after_name = variant_machines[machine_id].name if machine_id in variant_machines else "Not present"
        names = before_name if before_name == after_name else f"{before_name} → {after_name}"
        rows.append(
            f'<tr><td><strong>{escaped(machine_id)}</strong><br><span class="muted">{escaped(names)}</span></td>'
            f'<td class="number">{_percent(before)}</td><td class="number">{_percent(after)}</td>'
            f'<td class="number {_delta_class(delta)}">{delta:+.1%}</td></tr>'
        )
    table = (
        '<div class="table-wrap"><table><thead><tr><th>Machine</th><th class="number">Baseline utilization</th>'
        '<th class="number">Variant utilization</th><th class="number">Delta</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></div>"
        if rows
        else '<p class="empty-state">No machine utilization was recorded.</p>'
    )
    return _panel("Machine utilization", table)


def _comparison_metadata(baseline: Factory, variant: Factory) -> str:
    content = "".join(
        [
            _meta_item("Baseline ID", baseline.meta.id),
            _meta_item("Baseline name", baseline.meta.name),
            _meta_item("Variant ID", variant.meta.id),
            _meta_item("Variant name", variant.meta.name),
            _meta_item("Baseline machines", len(baseline.machines)),
            _meta_item("Variant machines", len(variant.machines)),
            _meta_item("Baseline operations", len(baseline.operations)),
            _meta_item("Variant operations", len(variant.operations)),
        ]
    )
    return f'<dl class="meta-grid">{content}</dl>'


def render_comparison_report(
    baseline: Factory, variant: Factory, scenario: Scenario
) -> str:
    _validate(baseline, "baseline")
    _validate(variant, "variant")
    report = compare_factories(baseline, variant, scenario)
    body = "".join(
        [
            f'<section class="section"><div class="verdict">{escaped(report.verdict)}</div></section>',
            _section("Compared factories", "Baseline and variant identity", _comparison_metadata(baseline, variant)),
            _section("Comparison overview", "Paired-seed engineering outcomes", _comparison_kpis(report)),
            _section(
                "Before and after",
                "Throughput, bottleneck, WIP, scrap, and utilization",
                f'<div class="split-grid">{_comparison_metrics(report)}{_comparison_utilization(baseline, variant, report)}</div>',
            ),
            _section("Scenario", "Shared paired-seed simulation inputs", _scenario_details(scenario)),
        ]
    )
    return render_document(
        f"{baseline.meta.name} vs {variant.meta.name} — Capacity comparison",
        f"Baseline {baseline.meta.id} · variant {variant.meta.id} · paired deterministic replications",
        body,
    )


def write_report(html: str, path: str | Path) -> Path:
    destination = Path(path)
    destination.write_text(html, encoding="utf-8", newline="\n")
    return destination
