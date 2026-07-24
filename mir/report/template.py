from __future__ import annotations

from html import escape


CSS = """
:root {
  color-scheme: light;
  --ink: #172033;
  --muted: #667085;
  --line: #d9e0ea;
  --panel: #ffffff;
  --canvas: #f3f6fa;
  --accent: #175cd3;
  --accent-soft: #eaf2ff;
  --good: #067647;
  --good-soft: #e7f8ef;
  --warn: #b54708;
  --warn-soft: #fff4e5;
  --danger: #b42318;
  --danger-soft: #feeceb;
  --busy: #1570ef;
  --idle: #98a2b3;
  --blocked: #f79009;
  --starved: #7f56d9;
  --setup: #06aed4;
  --down: #d92d20;
  --other: #475467;
}
* {
  box-sizing: border-box;
}
html {
  background: var(--canvas);
}
body {
  margin: 0;
  color: var(--ink);
  background: var(--canvas);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  font-size: 15px;
  line-height: 1.5;
}
button,
table {
  font: inherit;
}
.report-shell {
  width: min(1240px, calc(100% - 32px));
  margin: 0 auto;
  padding: 28px 0 52px;
}
.report-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 24px;
  padding: 28px 30px;
  border: 1px solid #ccdaed;
  border-radius: 18px;
  color: #ffffff;
  background: #12305f;
  box-shadow: 0 18px 46px rgba(20, 39, 74, 0.14);
}
.report-header h1 {
  max-width: 860px;
  margin: 4px 0 8px;
  font-size: clamp(26px, 4vw, 40px);
  line-height: 1.12;
  letter-spacing: -0.025em;
}
.report-header p {
  max-width: 820px;
  margin: 0;
  color: #d6e4fb;
}
.eyebrow {
  margin: 0;
  color: #a9c7f6;
  font-size: 12px;
  font-weight: 750;
  letter-spacing: 0.13em;
  text-transform: uppercase;
}
.print-control {
  flex: 0 0 auto;
  padding: 9px 14px;
  border: 1px solid #6e94ca;
  border-radius: 9px;
  color: #ffffff;
  background: #1c4b87;
  cursor: pointer;
}
.print-control:hover,
.print-control:focus-visible {
  background: #245b9f;
  outline: 2px solid #b9d4fa;
  outline-offset: 2px;
}
.section {
  margin-top: 22px;
}
.section-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 16px;
  margin: 0 2px 10px;
}
.section-heading h2 {
  margin: 0;
  font-size: 20px;
  letter-spacing: -0.012em;
}
.section-heading p {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.kpi-card,
.panel {
  border: 1px solid var(--line);
  background: var(--panel);
  box-shadow: 0 5px 18px rgba(31, 50, 81, 0.055);
}
.kpi-card {
  min-height: 132px;
  padding: 17px 18px;
  border-radius: 13px;
}
.kpi-label {
  display: block;
  margin-bottom: 8px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.065em;
  text-transform: uppercase;
}
.kpi-value {
  display: block;
  font-size: 28px;
  font-weight: 760;
  line-height: 1.15;
  letter-spacing: -0.025em;
  overflow-wrap: anywhere;
}
.kpi-note {
  display: block;
  margin-top: 7px;
  color: var(--muted);
  font-size: 13px;
}
.kpi-card.is-good {
  border-color: #9ed8bc;
  background: var(--good-soft);
}
.kpi-card.is-warning {
  border-color: #f5c58f;
  background: var(--warn-soft);
}
.kpi-card.is-danger {
  border-color: #f2aaa5;
  background: var(--danger-soft);
}
.panel {
  overflow: hidden;
  border-radius: 14px;
}
.panel-body {
  padding: 18px;
}
.panel-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin: 0;
  padding: 14px 18px;
  border-bottom: 1px solid var(--line);
  font-size: 15px;
  font-weight: 750;
  background: #f8fafc;
}
.split-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(280px, 0.6fr);
  gap: 12px;
}
.scenario-grid,
.meta-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
  background: var(--line);
}
.meta-item {
  min-width: 0;
  padding: 13px 15px;
  background: var(--panel);
}
.meta-item dt {
  margin-bottom: 4px;
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.meta-item dd {
  margin: 0;
  font-weight: 650;
  overflow-wrap: anywhere;
}
.table-wrap {
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-variant-numeric: tabular-nums;
}
th,
td {
  padding: 11px 13px;
  border-bottom: 1px solid #e6eaf0;
  text-align: left;
  vertical-align: middle;
}
th {
  color: #475467;
  background: #f8fafc;
  font-size: 11px;
  font-weight: 750;
  letter-spacing: 0.055em;
  text-transform: uppercase;
}
td.number,
th.number {
  text-align: right;
  white-space: nowrap;
}
tbody tr:last-child td {
  border-bottom: 0;
}
tbody tr.is-bottleneck td {
  background: #fff8eb;
}
.badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border: 1px solid #cfd7e4;
  border-radius: 999px;
  color: #344054;
  background: #ffffff;
  font-size: 11px;
  font-weight: 720;
  white-space: nowrap;
}
.badge.is-accent {
  border-color: #a9c8fa;
  color: #1849a9;
  background: var(--accent-soft);
}
.badge.is-warning {
  border-color: #f3c083;
  color: #93370d;
  background: var(--warn-soft);
}
.badge.is-error {
  border-color: #efaaa6;
  color: #912018;
  background: var(--danger-soft);
}
.badge.is-info {
  border-color: #a9c8fa;
  color: #1849a9;
  background: var(--accent-soft);
}
.state-bar {
  display: flex;
  width: 100%;
  min-width: 280px;
  height: 16px;
  overflow: hidden;
  border-radius: 5px;
  background: #e9edf3;
}
.state-segment {
  display: block;
  height: 100%;
}
.state-busy {
  background: var(--busy);
}
.state-idle {
  background: var(--idle);
}
.state-blocked {
  background: var(--blocked);
}
.state-starved {
  background: var(--starved);
}
.state-setup {
  background: var(--setup);
}
.state-down {
  background: var(--down);
}
.state-other {
  background: var(--other);
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin-top: 12px;
  color: var(--muted);
  font-size: 12px;
}
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.legend-swatch {
  width: 10px;
  height: 10px;
  border-radius: 3px;
}
.topology-wrap {
  overflow-x: auto;
  padding: 8px;
  background: #f8fafc;
}
.topology-svg {
  display: block;
  min-width: 100%;
  height: auto;
}
.flow-line {
  fill: none;
  stroke: #98a2b3;
  stroke-width: 2;
}
.flow-arrow {
  fill: #98a2b3;
}
.flow-label {
  fill: #475467;
  font-size: 11px;
  font-weight: 650;
}
.node-card {
  stroke: #aeb9c9;
  stroke-width: 1.5;
}
.node-card.is-bottleneck {
  stroke: #e04f16;
  stroke-width: 4;
}
.node-title {
  fill: #172033;
  font-size: 13px;
  font-weight: 750;
}
.node-subtitle {
  fill: #475467;
  font-size: 11px;
}
.node-badge {
  fill: #93370d;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.05em;
}
.diagnostic-list {
  display: grid;
  gap: 9px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.diagnostic {
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-left-width: 4px;
  border-radius: 9px;
  background: #ffffff;
}
.diagnostic.error {
  border-left-color: var(--danger);
}
.diagnostic.warning {
  border-left-color: var(--warn);
}
.diagnostic.info {
  border-left-color: var(--accent);
}
.diagnostic-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 7px;
  margin-bottom: 4px;
  font-weight: 720;
}
.diagnostic p {
  margin: 3px 0 0;
  color: #475467;
}
.verdict {
  padding: 18px 20px;
  border: 1px solid #a9c8fa;
  border-left: 5px solid var(--accent);
  border-radius: 12px;
  background: var(--accent-soft);
  font-size: 18px;
  font-weight: 680;
}
.delta-positive {
  color: var(--good);
  font-weight: 750;
}
.delta-negative {
  color: var(--danger);
  font-weight: 750;
}
.delta-neutral {
  color: #475467;
  font-weight: 750;
}
.empty-state {
  margin: 0;
  padding: 20px;
  color: var(--muted);
  text-align: center;
}
.muted {
  color: var(--muted);
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
@media (max-width: 900px) {
  .kpi-grid,
  .scenario-grid,
  .meta-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .split-grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 560px) {
  .report-shell {
    width: min(100% - 20px, 1240px);
    padding-top: 10px;
  }
  .report-header {
    display: block;
    padding: 22px;
    border-radius: 13px;
  }
  .print-control {
    margin-top: 18px;
  }
  .kpi-grid,
  .scenario-grid,
  .meta-grid {
    grid-template-columns: 1fr;
  }
  th,
  td {
    padding: 9px 10px;
  }
}
@media print {
  html,
  body {
    background: #ffffff;
  }
  .report-shell {
    width: 100%;
    padding: 0;
  }
  .report-header,
  .kpi-card,
  .panel {
    box-shadow: none;
    break-inside: avoid;
  }
  .print-control {
    display: none;
  }
  .section {
    break-inside: avoid;
  }
}
""".strip()

SCRIPT = """
"use strict";
const printControl = document.querySelector("[data-print-report]");
if (printControl) {
  printControl.addEventListener("click", () => window.print());
}
""".strip()


def escaped(value: object) -> str:
    return escape(str(value), quote=True)


def render_document(title: str, subtitle: str, body: str) -> str:
    safe_title = escaped(title)
    safe_subtitle = escaped(subtitle)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title}</title>
<style>
{CSS}
</style>
</head>
<body>
<main class="report-shell">
<header class="report-header">
<div>
<p class="eyebrow">Manufacturing IR engineering report</p>
<h1>{safe_title}</h1>
<p>{safe_subtitle}</p>
</div>
<button class="print-control" type="button" data-print-report>Print report</button>
</header>
{body}
</main>
<script>
{SCRIPT}
</script>
</body>
</html>
"""
