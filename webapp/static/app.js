/* ============================================================
   MIR Workbench — frontend
   Plain ES module, no build step. Talks to the /api backend
   described in the v1 contract. Organized by section:
     1. helpers + API client
     2. app state
     3. console + diagnostics panel
     4. pipeline chips
     5. editor rail (examples, synth, format toggle, scenario)
     6. editor actions (validate / fmt / compile / decompile / schema)
     7. topology + metrics (analyze / simulate)
     8. decide view (sweep / recommend / sensitivity)
     9. reports view (report / compare)
    10. codegen view (emit)
    11. view tabs + boot
   ============================================================ */

/* ---------------- 1. helpers + API client ---------------- */

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};
const fmtNum = (x, d = 2) => (x === null || x === undefined || Number.isNaN(x)) ? '—' : Number(x).toFixed(d);
const pct = (x) => Math.max(0, Math.min(100, x));

class ApiError extends Error {
  constructor(status, payload) {
    super(payload?.error || `HTTP ${status}`);
    this.status = status;
    this.payload = payload || {};
  }
}

async function api(path, { method = 'GET', body, raw = false } = {}) {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let payload = null;
    try { payload = await res.json(); } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, payload);
  }
  if (raw) return res;
  const ct = res.headers.get('content-type') || '';
  return ct.includes('application/json') ? res.json() : res.text();
}

/* ---------------- 2. app state ---------------- */

const state = {
  format: 'mir',            // editor document format
  variantFormat: 'json',
  meta: null,               // /api/meta payload
  examples: [],             // /api/examples payload
  factory: null,            // last compiled IR JSON object (for topology)
  analysis: null,           // last /api/analyze result
  simulation: null,         // last /api/simulate result
  emitted: null,            // last /api/emit files map
  lastReportHtml: null,
};

const editor = $('#editor');
const variantEditor = $('#variant-editor');
const spaceEditor = $('#space-editor');

function currentSource() {
  return { format: state.format, text: editor.value };
}
function variantSource() {
  return { format: state.variantFormat, text: variantEditor.value };
}
function currentScenario() {
  return {
    horizon_h: parseFloat($('#sc-horizon').value) || 24,
    warmup_h: parseFloat($('#sc-warmup').value) || 0,
    seed: parseInt($('#sc-seed').value, 10) || 1,
    replications: parseInt($('#sc-reps').value, 10) || 1,
    dispatch: $('#sc-dispatch').value || 'fifo-fair',
  };
}
function scenarioFlags() {
  const s = currentScenario();
  return `--horizon-h ${s.horizon_h} --warmup-h ${s.warmup_h} --seed ${s.seed} --replications ${s.replications} --dispatch ${s.dispatch}`;
}

/* ---------------- 3. console + diagnostics panel ---------------- */

const consoleBody = $('#panel-console');
const diagBody = $('#panel-diagnostics');

function logCmd(cmd) {
  consoleBody.appendChild(el('div', 'con-cmd', `$ ${cmd}`));
  consoleBody.scrollTop = consoleBody.scrollHeight;
}
function logOut(text, cls = 'con-out') {
  for (const line of String(text).split('\n')) {
    consoleBody.appendChild(el('div', cls, line));
  }
  consoleBody.scrollTop = consoleBody.scrollHeight;
}
function setStatus(text, isErr = false) {
  const chip = $('#status-chip');
  chip.textContent = text;
  chip.classList.toggle('err', isErr);
}

function showDiagnostics(diags) {
  diagBody.textContent = '';
  $('#diag-count').textContent = String(diags.length);
  if (!diags.length) {
    diagBody.appendChild(el('div', 'placeholder small', 'no diagnostics'));
    return;
  }
  for (const d of diags) {
    const row = el('div', 'diag-row');
    row.appendChild(el('span', 'diag-code', d.code || ''));
    row.appendChild(el('span', `diag-sev ${d.severity || ''}`, d.severity || ''));
    const msg = el('span', 'diag-msg', d.message || '');
    if (d.entities?.length) msg.textContent += `  [${d.entities.join(', ')}]`;
    if (d.hint) {
      msg.appendChild(el('span', 'diag-hint', `  hint: ${d.hint}`));
    }
    row.appendChild(msg);
    diagBody.appendChild(row);
  }
}

function switchPanel(name) {
  document.querySelectorAll('.panel-tab').forEach(t => t.classList.toggle('active', t.dataset.panel === name));
  document.querySelectorAll('.panel-body').forEach(b => b.classList.toggle('active', b.id === `panel-${name}`));
}
document.querySelectorAll('.panel-tab').forEach(t =>
  t.addEventListener('click', () => switchPanel(t.dataset.panel)));

/* Central error reporter: 400/422 surface in console + diagnostics. */
function reportError(cmd, err) {
  if (err instanceof ApiError) {
    logOut(`error (${err.status}): ${err.payload.error || err.message}`, 'con-err');
    if (err.payload.kind === 'semantic' && err.payload.diagnostics) {
      showDiagnostics(err.payload.diagnostics);
      switchPanel('diagnostics');
    }
  } else {
    logOut(`error: ${err.message}`, 'con-err');
  }
  setStatus('exit 1', true);
}

/* Wraps an action: logs the pseudo-CLI command, flips status/pipeline chips. */
async function runAction(cmd, stage, fn) {
  logCmd(cmd);
  if (stage) setChip(stage, 'run');
  setStatus('running…');
  try {
    const result = await fn();
    if (stage) setChip(stage, 'ok');
    setStatus('exit 0');
    return result;
  } catch (err) {
    if (stage) setChip(stage, 'err');
    reportError(cmd, err);
    return null;
  }
}

/* ---------------- 4. pipeline chips ---------------- */

function setChip(stage, cls) {
  const chip = document.querySelector(`.chip[data-stage="${stage}"]`);
  if (!chip) return;
  chip.classList.remove('ok', 'run', 'err');
  if (cls) chip.classList.add(cls);
}
function resetChips() {
  ['compile', 'validate', 'analyze', 'simulate'].forEach(s => setChip(s, null));
}

/* ---------------- 5. editor rail ---------------- */

function refreshLineNumbers() {
  const lines = editor.value.split('\n').length;
  const ln = $('#line-numbers');
  ln.textContent = '';
  for (let i = 1; i <= lines; i++) ln.appendChild(el('div', null, String(i)));
}
editor.addEventListener('input', () => {
  refreshLineNumbers();
  $('#editor-canon').textContent = '';
  state.analysis = null;
  state.simulation = null;
});
editor.addEventListener('scroll', () => { $('#line-numbers').scrollTop = editor.scrollTop; });

function setFormat(fmt) {
  state.format = fmt;
  document.querySelectorAll('#fmt-toggle button').forEach(b => b.classList.toggle('active', b.dataset.fmt === fmt));
  $('#editor-format-label').textContent = fmt === 'mir' ? 'MIR DSL' : 'IR JSON';
  const name = $('#editor-filename').textContent.replace(/\.(mir|json)$/, '');
  $('#editor-filename').textContent = `${name}.${fmt}`;
}
document.querySelectorAll('#fmt-toggle button').forEach(b =>
  b.addEventListener('click', () => setFormat(b.dataset.fmt)));

function setDocument(name, fmt, text) {
  setFormat(fmt);
  editor.value = text;
  $('#editor-filename').textContent = name;
  $('#editor-canon').textContent = '';
  refreshLineNumbers();
  resetChips();
  state.factory = null;
  state.analysis = null;
  state.simulation = null;
  updateFactoryName(text, fmt);
}

function updateFactoryName(text, fmt) {
  let id = '—';
  if (fmt === 'json') {
    try { id = JSON.parse(text)?.meta?.id || '—'; } catch { /* not parseable yet */ }
  } else {
    const m = text.match(/factory\s+("?)([\w.-]+)\1/);
    if (m) id = m[2];
  }
  $('#factory-name').textContent = id;
}

$('#example-picker').addEventListener('change', (e) => {
  const ex = state.examples.find(x => x.name === e.target.value);
  e.target.value = '';
  if (!ex) return;
  if (ex.format === 'space') {
    spaceEditor.value = ex.text;
    logCmd(`# loaded ${ex.name} into design-space editor`);
    return;
  }
  setDocument(ex.name, ex.format, ex.text);
  logCmd(`# loaded example ${ex.name}`);
});

$('#variant-example-picker').addEventListener('change', (e) => {
  const ex = state.examples.find(x => x.name === e.target.value && x.format !== 'space');
  e.target.value = '';
  if (!ex) return;
  setVariantFormat(ex.format);
  variantEditor.value = ex.text;
});

function setVariantFormat(fmt) {
  state.variantFormat = fmt;
  document.querySelectorAll('#variant-fmt-toggle button').forEach(b => b.classList.toggle('active', b.dataset.fmt === fmt));
}
document.querySelectorAll('#variant-fmt-toggle button').forEach(b =>
  b.addEventListener('click', () => setVariantFormat(b.dataset.fmt)));

$('#synth-picker').addEventListener('change', async (e) => {
  const gen = e.target.value;
  e.target.value = '';
  if (!gen) return;
  const res = await runAction(`mir synth ${gen}`, null, () =>
    api('/synth', { method: 'POST', body: { generator: gen, options: {} } }));
  if (!res) return;
  setDocument(`${gen}.mir`, 'mir', res.mir_text);
  logOut(`generated ${gen} (mir + canonical json available)`);
});

/* ---------------- 6. editor actions ---------------- */

$('#btn-validate').addEventListener('click', async () => {
  const res = await runAction('mir validate <editor>', 'validate', () =>
    api('/validate', { method: 'POST', body: { source: currentSource() } }));
  if (!res) return;
  showDiagnostics(res.diagnostics);
  if (res.valid) {
    logOut('valid: no semantic errors', 'con-ok');
  } else {
    logOut(`invalid: ${res.diagnostics.filter(d => d.severity === 'error').length} error(s)`, 'con-err');
    setChip('validate', 'err');
    switchPanel('diagnostics');
  }
});

$('#btn-format').addEventListener('click', async () => {
  const res = await runAction('mir fmt <editor>', null, () =>
    api('/fmt', { method: 'POST', body: { source: currentSource() } }));
  if (!res) return;
  editor.value = res.canonical;
  refreshLineNumbers();
  $('#editor-canon').textContent = 'canonical ✓';
  logOut(res.changed ? 'reformatted to canonical form' : 'already canonical');
});

$('#btn-compile').addEventListener('click', async () => {
  if (state.format !== 'mir') { logCmd('mir compile'); logOut('editor is already IR JSON — switch to .mir to compile', 'con-err'); return; }
  const res = await runAction('mir compile <editor> -o <editor>.json', 'compile', () =>
    api('/compile', { method: 'POST', body: { text: editor.value } }));
  if (!res) return;
  setDocument($('#editor-filename').textContent.replace(/\.mir$/, '.json'), 'json', res.json_text);
  setChip('compile', 'ok');
  logOut('compiled to canonical IR JSON');
});

$('#btn-decompile').addEventListener('click', async () => {
  if (state.format !== 'json') { logCmd('mir decompile'); logOut('editor is already MIR DSL — switch to .json to decompile', 'con-err'); return; }
  const res = await runAction('mir decompile <editor> -o <editor>.mir', 'compile', () =>
    api('/decompile', { method: 'POST', body: { text: editor.value } }));
  if (!res) return;
  setDocument($('#editor-filename').textContent.replace(/\.json$/, '.mir'), 'mir', res.mir_text);
  logOut('decompiled to MIR DSL');
});

$('#btn-schema').addEventListener('click', () => {
  logCmd('mir schema');
  window.open('/api/schema', '_blank');
  logOut('opened factory JSON schema in a new tab');
});

/* Compile the current editor text to an IR JSON object (for topology). */
async function compiledFactory() {
  if (state.format === 'json') {
    return JSON.parse(editor.value);
  }
  const res = await api('/compile', { method: 'POST', body: { text: editor.value } });
  return JSON.parse(res.json_text);
}

/* ---------------- 7. topology + metrics ---------------- */

const STATE_COLORS = {
  busy: '#3ddc84', blocked: '#f0a83a', starved: '#4aa3ff',
  setup: '#b98aff', down: '#ff4d4d', offshift: '#3a424d', idle: '#6b7684',
};
const STATE_ORDER = ['busy', 'blocked', 'starved', 'setup', 'down', 'offshift', 'idle'];

/* Order operations as a chain using flow edges (serial-friendly layout). */
function operationChain(factory) {
  const ops = factory.operations.map(o => o.id);
  const edges = factory.flows.filter(f => f.from_op && f.to_op);
  const hasIncoming = new Set(edges.map(f => f.to_op));
  const start = ops.filter(o => !hasIncoming.has(o));
  const ordered = [];
  const seen = new Set();
  const queue = [...start];
  while (queue.length) {
    const op = queue.shift();
    if (seen.has(op)) continue;
    seen.add(op);
    ordered.push(op);
    for (const e of edges) if (e.from_op === op && !seen.has(e.to_op)) queue.push(e.to_op);
  }
  for (const o of ops) if (!seen.has(o)) ordered.push(o);
  return ordered;
}

function cycleLabel(op) {
  const c = op.cycle_time || {};
  if (c.kind === 'constant') return `constant(${c.value_s}s)`;
  if (c.kind === 'uniform') return `uniform(${c.low_s}s, ${c.high_s}s)`;
  if (c.kind === 'normal') return `normal(${c.mean_s}s, ${c.stdev_s}s)`;
  if (c.kind === 'exponential') return `exp(${c.mean_s}s)`;
  return c.kind || '';
}

function renderTopology() {
  const box = $('#topology');
  box.textContent = '';
  const f = state.factory;
  if (!f) { box.appendChild(el('div', 'placeholder', 'Compile / Analyze a document to render topology.')); return; }

  const sim = state.simulation;
  const summary = sim?.summary;
  const rep = sim?.replications?.[sim.replications.length - 1];
  const bottleneck = state.analysis?.analysis?.capacity?.bottleneck_machine
    ?? null;
  const machById = Object.fromEntries(f.machines.map(m => [m.id, m]));
  const opById = Object.fromEntries(f.operations.map(o => [o.id, o]));
  const chain = operationChain(f);

  const line = el('div', 'topo-line');

  // inlet terminal
  const inlets = f.flows.filter(fl => !fl.from_op && fl.to_op);
  const inletBox = el('div', 'topo-terminal');
  inletBox.appendChild(el('div', 't-label', 'Inlet'));
  inletBox.appendChild(el('div', 't-val', inlets.map(i => i.material).join(', ') || '—'));
  inletBox.appendChild(el('div', 't-val', '∞ supply'));
  line.appendChild(inletBox);

  chain.forEach((opId, idx) => {
    const op = opById[opId];
    // connector: buffer flows into this op (from a previous op)
    const link = el('div', 'topo-link');
    const bufFlow = f.flows.find(fl => fl.to_op === opId && fl.from_op);
    if (bufFlow && bufFlow.buffer_capacity != null) {
      const buf = rep?.buffers?.[bufFlow.id];
      const level = buf ? buf.ending_occupancy ?? buf.mean_occupancy : null;
      const label = el('div', 'buf-label');
      label.append(`${bufFlow.id} `);
      const b = el('b', null, level === null ? '·' : String(Math.round(level)));
      label.appendChild(b);
      label.append(`/${bufFlow.buffer_capacity}`);
      link.appendChild(label);
      const track = el('div', 'buf-track');
      const fillPct = level === null ? 0 : pct(100 * level / bufFlow.buffer_capacity);
      const fill = el('div', `buf-fill${fillPct >= 99.5 ? ' full' : ''}`);
      fill.style.width = `${fillPct}%`;
      track.appendChild(fill);
      link.appendChild(track);
    }
    const dash = el('div', `flow-dash${sim ? ' animate' : ''}`);
    link.appendChild(dash);
    line.appendChild(link);

    // machine card(s) for this operation (first machine shown, rest listed)
    const machId = op.machines?.[0];
    const mach = machById[machId] || { id: machId, machine_class: '?', num_stations: 1 };
    const fr = summary?.machine_state_fractions_mean?.[machId] || null;
    const dominant = fr
      ? STATE_ORDER.reduce((a, b) => ((fr[a] ?? 0) >= (fr[b] ?? 0) ? a : b))
      : 'idle';
    const color = STATE_COLORS[dominant];

    const stage = el('div', 'machine-stage');
    const opLbl = el('div', 'op-label');
    opLbl.append(`${op.id} · `);
    opLbl.appendChild(el('b', null, cycleLabel(op)));
    stage.appendChild(opLbl);

    const card = el('div', `machine-card${dominant === 'busy' ? ' busy' : ''}${dominant === 'blocked' ? ' blocked' : ''}`);
    const stateRow = el('div', 'state-row');
    const led = el('span', 'led');
    led.style.background = color;
    stateRow.appendChild(led);
    const sName = el('span', 'state-name', fr ? dominant.toUpperCase() : 'IDLE');
    sName.style.color = color;
    stateRow.appendChild(sName);
    if (bottleneck && machId === bottleneck) stateRow.appendChild(el('span', 'btlnck', 'BTLNCK'));
    card.appendChild(stateRow);
    card.appendChild(el('div', 'mach-name', mach.name || mach.id));
    const extra = op.machines?.length > 1 ? ` +${op.machines.length - 1} alt` : '';
    card.appendChild(el('div', 'mach-sub', `${mach.machine_class || 'machine'} · ${mach.num_stations || 1} station${(mach.num_stations || 1) > 1 ? 's' : ''}${extra}`));
    if (fr) {
      const bars = el('div', 'mini-bars');
      for (const s of STATE_ORDER) {
        const seg = el('div');
        seg.style.width = `${pct(100 * (fr[s] ?? 0))}%`;
        seg.style.background = STATE_COLORS[s];
        bars.appendChild(seg);
      }
      card.appendChild(bars);
    }
    const stats = el('div', 'mach-stats');
    const busySpan = el('span');
    busySpan.append('busy ');
    busySpan.appendChild(el('b', null, fr ? `${(100 * (fr.busy ?? 0)).toFixed(1)}%` : '—'));
    stats.appendChild(busySpan);
    const scrapSpan = el('span');
    scrapSpan.append('scrap ');
    scrapSpan.appendChild(el('b', null, summary ? fmtNum(summary.scrap_by_operation_mean?.[op.id] ?? 0, 1) : '—'));
    stats.appendChild(scrapSpan);
    card.appendChild(stats);
    stage.appendChild(card);
    line.appendChild(stage);
  });

  // outlet terminal
  const outLink = el('div', 'topo-link');
  outLink.appendChild(el('div', `flow-dash${sim ? ' animate' : ''}`));
  line.appendChild(outLink);
  const outlets = f.flows.filter(fl => fl.from_op && !fl.to_op);
  const outBox = el('div', 'topo-terminal outlet');
  outBox.appendChild(el('div', 't-label', 'Outlet'));
  const thru = summary?.throughput_units_per_hour_mean;
  outBox.appendChild(el('div', 't-big', thru === undefined ? '—' : fmtNum(thru, 1)));
  outBox.appendChild(el('div', 't-label', outlets.map(o => o.material).join(', ') || 'units/h'));
  line.appendChild(outBox);

  box.appendChild(line);
}

function kvRow(k, v, vCls = '') {
  const row = el('div', 'kv-row');
  row.appendChild(el('span', 'k', k));
  row.appendChild(el('span', `v ${vCls}`, v));
  return row;
}

function renderCapacityCard() {
  const card = $('#capacity-card');
  card.textContent = '';
  const cap = state.analysis?.analysis?.capacity;
  const topo = state.analysis?.analysis?.topology;
  if (!cap) { card.appendChild(el('div', 'placeholder small', 'run analyze')); return; }
  card.appendChild(kvRow('Throughput bound', `${fmtNum(cap.throughput_upper_bound_units_per_hour)} u/h`));
  card.appendChild(kvRow('Bottleneck', cap.bottleneck_machine || '—', 'amber-t'));
  if (topo) card.appendChild(kvRow('Serial line', topo.is_serial_line ? 'yes' : 'no', topo.is_serial_line ? 'green-t' : ''));
  card.appendChild(kvRow('Bound exactness', cap.exact ? 'exact (det. DAG)' : 'upper bound', cap.exact ? 'green-t' : ''));
}

function renderMetrics() {
  const summary = state.simulation?.summary;
  const bound = state.analysis?.analysis?.capacity?.throughput_upper_bound_units_per_hour ?? null;
  $('#m-bound').textContent = bound === null ? '—' : fmtNum(bound);
  if (!summary) return;
  const thru = summary.throughput_units_per_hour_mean;
  $('#m-thru').textContent = fmtNum(thru);
  $('#m-thru-bar').style.width = bound ? `${pct(100 * thru / bound)}%` : '0%';
  $('#m-wip').textContent = fmtNum(summary.ending_wip_mean, 1);
  const scrapTotal = Object.values(summary.scrap_by_operation_mean || {}).reduce((a, b) => a + b, 0);
  $('#m-scrap').textContent = fmtNum(scrapTotal, 1);
  $('#m-stdev').textContent = fmtNum(summary.throughput_units_per_hour_stdev);

  const bars = $('#state-bars');
  bars.textContent = '';
  for (const [mach, fr] of Object.entries(summary.machine_state_fractions_mean || {})) {
    const row = el('div', 'sb-row');
    const head = el('div', 'sb-head');
    head.appendChild(el('span', 'm', mach));
    const dominant = STATE_ORDER.reduce((a, b) => ((fr[a] ?? 0) >= (fr[b] ?? 0) ? a : b));
    const dl = el('span', null, dominant);
    dl.style.color = STATE_COLORS[dominant];
    head.appendChild(dl);
    row.appendChild(head);
    const track = el('div', 'sb-track');
    for (const s of STATE_ORDER) {
      const seg = el('div');
      seg.style.width = `${pct(100 * (fr[s] ?? 0))}%`;
      seg.style.background = STATE_COLORS[s];
      track.appendChild(seg);
    }
    row.appendChild(track);
    bars.appendChild(row);
  }
}

$('#btn-analyze').addEventListener('click', async () => {
  const res = await runAction('mir analyze <editor>', 'analyze', async () => {
    const factory = await compiledFactory();
    const analysis = await api('/analyze', { method: 'POST', body: { source: currentSource() } });
    return { factory, analysis };
  });
  if (!res) return;
  state.factory = res.factory;
  state.analysis = res.analysis;
  updateFactoryName(editor.value, state.format);
  showDiagnostics(res.analysis.diagnostics);
  const topo = res.analysis.analysis?.topology;
  const cap = res.analysis.analysis?.capacity;
  if (topo) {
    logOut(`Topology: ${Object.keys(topo.adjacency || {}).length} operations, ${topo.inlet_flows?.length ?? 0} inlet(s), ${topo.outlet_flows?.length ?? 0} outlet(s)`);
    logOut(`Serial line: ${topo.is_serial_line ? 'yes' : 'no'}`);
  }
  if (cap) {
    logOut(`Throughput bound: ${fmtNum(cap.throughput_upper_bound_units_per_hour)} units/hour`);
    logOut(`Bottleneck: ${cap.bottleneck_machine || '—'}`);
  }
  renderTopology();
  renderCapacityCard();
  renderMetrics();
});

$('#btn-simulate').addEventListener('click', async () => {
  const res = await runAction(`mir simulate <editor> ${scenarioFlags()}`, 'simulate', async () => {
    const factory = await compiledFactory();
    const analysis = await api('/analyze', { method: 'POST', body: { source: currentSource() } });
    const sim = await api('/simulate', { method: 'POST', body: { source: currentSource(), scenario: currentScenario() } });
    return { factory, analysis, sim };
  });
  if (!res) return;
  state.factory = res.factory;
  state.analysis = res.analysis;
  state.simulation = res.sim;
  const s = res.sim.summary;
  logOut(`Throughput: ${fmtNum(s.throughput_units_per_hour_mean)} ± ${fmtNum(s.throughput_units_per_hour_stdev)} units/hour`, 'con-ok');
  for (const [mach, fr] of Object.entries(s.machine_state_fractions_mean || {})) {
    logOut(`${mach}: busy ${(100 * fr.busy).toFixed(1)}%, blocked ${(100 * fr.blocked).toFixed(1)}%, starved ${(100 * fr.starved).toFixed(1)}%, down ${(100 * fr.down).toFixed(1)}%, offshift ${(100 * fr.offshift).toFixed(1)}%`);
  }
  logOut(`Ending WIP: ${fmtNum(s.ending_wip_mean, 1)}`);
  renderTopology();
  renderCapacityCard();
  renderMetrics();
});

/* ---------------- 8. decide view ---------------- */

function parseSpace() {
  try {
    return JSON.parse(spaceEditor.value);
  } catch (e) {
    throw new Error(`design space is not valid JSON: ${e.message}`);
  }
}

function resultsTable(headers, rows) {
  const table = el('table', 'results');
  const thead = el('thead');
  const hr = el('tr');
  headers.forEach(h => hr.appendChild(el('th', null, h)));
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = el('tbody');
  rows.forEach(({ cells, cls }) => {
    const tr = el('tr', cls || '');
    cells.forEach(c => {
      const td = el('td', c.cls || '', c.text);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  return table;
}

const deltaCell = (v) => ({ text: `${v >= 0 ? '+' : ''}${fmtNum(v, 1)}%`, cls: v > 0 ? 'pos' : (v < 0 ? 'neg' : '') });
const paramsLabel = (params) => Object.entries(params).map(([k, v]) => `${k.split('.').slice(1).join('.')}=${v}`).join('  ');

$('#btn-sweep').addEventListener('click', async () => {
  const workers = parseInt($('#sweep-workers').value, 10) || null;
  const res = await runAction(`mir sweep <editor> <space> --workers ${workers ?? 'auto'} ${scenarioFlags()}`, null, () =>
    api('/sweep', { method: 'POST', body: { source: currentSource(), space: parseSpace(), scenario: currentScenario(), workers } }));
  if (!res) return;
  $('#verdict-card').textContent = '';
  const out = $('#decide-results');
  out.textContent = '';
  const block = el('div', 'result-block');
  block.appendChild(el('h3', null, `Sweep · ${res.points.length} points · baseline ${fmtNum(res.baseline.throughput_mean)} u/h`));
  const best = Math.max(...res.points.map(p => p.throughput_mean));
  block.appendChild(resultsTable(
    ['#', 'parameters', 'throughput u/h', 'Δ%', 'WIP', 'scrap', 'bottleneck'],
    res.points.map(p => ({
      cls: p.throughput_mean === best ? 'best' : '',
      cells: [
        { text: String(p.index) },
        { text: paramsLabel(p.parameters) },
        { text: `${fmtNum(p.throughput_mean)} ± ${fmtNum(p.throughput_stdev)}` },
        deltaCell(p.delta_percent),
        { text: fmtNum(p.ending_wip, 1) },
        { text: fmtNum(p.scrap, 1) },
        { text: p.bottleneck || '—' },
      ],
    }))));
  out.appendChild(block);
  logOut(`swept ${res.points.length} design points (best ${fmtNum(best)} u/h)`, 'con-ok');
});

$('#btn-recommend').addEventListener('click', async () => {
  const workers = parseInt($('#sweep-workers').value, 10) || null;
  const topK = parseInt($('#top-k').value, 10) || 3;
  const objective = $('#objective-picker').value || 'throughput';
  const res = await runAction(`mir recommend <editor> <space> --objective ${objective} --top-k ${topK}`, null, () =>
    api('/recommend', { method: 'POST', body: { source: currentSource(), space: parseSpace(), scenario: currentScenario(), workers, objective, top_k: topK } }));
  if (!res) return;
  const vc = $('#verdict-card');
  vc.textContent = '';
  vc.appendChild(el('div', 'v-title', `Verdict · objective ${res.objective}`));
  vc.appendChild(el('div', 'v-body', res.verdict || `baseline score ${fmtNum(res.baseline_score)}`));
  const out = $('#decide-results');
  out.textContent = '';
  const block = el('div', 'result-block');
  block.appendChild(el('h3', null, `Leaderboard · top ${res.recommendations.length} of design space`));
  block.appendChild(resultsTable(
    ['rank', 'parameters', 'score', 'throughput u/h', 'Δ%', 'bottleneck'],
    res.recommendations.map(r => ({
      cls: r.rank === 1 ? 'best' : '',
      cells: [
        { text: `#${r.rank}` },
        { text: paramsLabel(r.point.parameters) },
        { text: fmtNum(r.score) },
        { text: `${fmtNum(r.point.throughput_mean)} ± ${fmtNum(r.point.throughput_stdev)}` },
        deltaCell(r.point.delta_percent),
        { text: r.point.bottleneck || '—' },
      ],
    }))));
  out.appendChild(block);
  logOut(`top recommendation: ${paramsLabel(res.recommendations[0]?.point.parameters || {})} → score ${fmtNum(res.recommendations[0]?.score)}`, 'con-ok');
});

$('#btn-sensitivity').addEventListener('click', async () => {
  const percent = parseFloat($('#sens-percent').value) || 10;
  const res = await runAction(`mir sensitivity <editor> --percent ${percent}`, null, () =>
    api('/sensitivity', { method: 'POST', body: { source: currentSource(), scenario: currentScenario(), percent } }));
  if (!res) return;
  $('#verdict-card').textContent = '';
  const out = $('#decide-results');
  out.textContent = '';
  const block = el('div', 'result-block');
  block.appendChild(el('h3', null, `Sensitivity · ±${res.percent}% one-at-a-time · baseline ${fmtNum(res.baseline.throughput_mean)} u/h`));
  const maxImpact = Math.max(...res.entries.map(e => Math.abs(e.absolute_impact)), 1e-9);
  const bars = el('div', 'rank-bars');
  for (const e of res.entries) {
    const row = el('div', 'rank-row');
    const head = el('div', 'rr-head');
    head.appendChild(el('span', 'p', `#${e.rank} ${e.path}`));
    head.appendChild(el('span', 'v', `impact ${fmtNum(e.absolute_impact)} u/h`));
    row.appendChild(head);
    const track = el('div', 'rr-track');
    const fill = el('div', 'rr-fill');
    fill.style.width = `${pct(100 * Math.abs(e.absolute_impact) / maxImpact)}%`;
    track.appendChild(fill);
    row.appendChild(track);
    bars.appendChild(row);
  }
  block.appendChild(bars);
  block.appendChild(resultsTable(
    ['rank', 'parameter', 'kind', '-Δ throughput', '+Δ throughput'],
    res.entries.map(e => ({
      cells: [
        { text: `#${e.rank}` },
        { text: e.path },
        { text: e.kind },
        { text: fmtNum(e.lower_throughput_mean) },
        { text: fmtNum(e.upper_throughput_mean) },
      ],
    }))));
  out.appendChild(block);
  logOut(`sensitivity ranked ${res.entries.length} parameters`, 'con-ok');
});

/* ---------------- 9. reports view ---------------- */

function showReport(html) {
  state.lastReportHtml = html;
  $('#report-frame').srcdoc = html;
}

$('#btn-report').addEventListener('click', async () => {
  const html = await runAction(`mir report <editor> ${scenarioFlags()}`, null, () =>
    api('/report', { method: 'POST', body: { source: currentSource(), scenario: currentScenario() } }));
  if (html === null) return;
  showReport(html);
  logOut('rendered factory report (right pane / open in tab)', 'con-ok');
});

$('#btn-report-compare').addEventListener('click', async () => {
  const html = await runAction('mir report --compare <editor> <variant>', null, () =>
    api('/report/compare', { method: 'POST', body: { baseline: currentSource(), variant: variantSource(), scenario: currentScenario() } }));
  if (html === null) return;
  showReport(html);
  logOut('rendered comparison report', 'con-ok');
});

$('#btn-report-newtab').addEventListener('click', () => {
  if (!state.lastReportHtml) { logCmd('# no report yet — run Report first'); return; }
  const blob = new Blob([state.lastReportHtml], { type: 'text/html' });
  window.open(URL.createObjectURL(blob), '_blank');
});

$('#btn-compare').addEventListener('click', async () => {
  const res = await runAction('mir compare <editor> <variant>', null, () =>
    api('/compare', { method: 'POST', body: { baseline: currentSource(), variant: variantSource(), scenario: currentScenario() } }));
  if (!res) return;
  const out = $('#compare-result');
  out.textContent = '';
  const card = el('div', 'card kv');
  card.appendChild(kvRow('Baseline', `${res.baseline_id} · ${fmtNum(res.throughput.baseline_mean)} u/h`));
  card.appendChild(kvRow('Variant', `${res.variant_id} · ${fmtNum(res.throughput.variant_mean)} u/h`));
  const d = res.throughput.delta_percent;
  card.appendChild(kvRow('Δ throughput', `${d >= 0 ? '+' : ''}${fmtNum(d, 1)}%`, d > 0 ? 'green-t' : (d < 0 ? '' : '')));
  card.appendChild(kvRow('Paired Δ', `${fmtNum(res.throughput.paired_delta_mean)} ± ${fmtNum(res.throughput.paired_delta_stdev)}`));
  card.appendChild(kvRow('Bottleneck', `${res.bottleneck.before} → ${res.bottleneck.after}`, 'amber-t'));
  card.appendChild(kvRow('Verdict', res.verdict || '—', 'green-t'));
  out.appendChild(card);
  logOut(`compare: Δ ${d >= 0 ? '+' : ''}${fmtNum(d, 1)}% (${res.verdict || 'no verdict'})`, 'con-ok');
});

/* ---------------- 10. codegen view ---------------- */

function renderFiles(files) {
  state.emitted = files;
  const tree = $('#file-tree');
  tree.textContent = '';
  const names = Object.keys(files).sort();
  names.forEach((name, i) => {
    const item = el('button', `file-item${i === 0 ? ' active' : ''}`, name);
    item.addEventListener('click', () => {
      tree.querySelectorAll('.file-item').forEach(b => b.classList.remove('active'));
      item.classList.add('active');
      $('#file-content').textContent = files[name];
    });
    tree.appendChild(item);
  });
  $('#file-content').textContent = names.length ? files[names[0]] : '';
}

$('#btn-emit').addEventListener('click', async () => {
  const backend = $('#backend-picker').value || 'st';
  const res = await runAction(`mir emit ${backend} <editor> -o generated-${backend}`, null, () =>
    api('/emit', { method: 'POST', body: { source: currentSource(), backend } }));
  if (!res) return;
  renderFiles(res.files);
  logOut(`emitted ${Object.keys(res.files).length} file(s) via backend '${backend}'`, 'con-ok');
});

$('#btn-emit-zip').addEventListener('click', async () => {
  const backend = $('#backend-picker').value || 'st';
  logCmd(`mir emit ${backend} <editor> --zip`);
  try {
    const res = await api('/emit/zip', { method: 'POST', body: { source: currentSource(), backend }, raw: true });
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `emitted-${backend}.zip`;
    a.click();
    URL.revokeObjectURL(a.href);
    logOut('downloaded zip', 'con-ok');
    setStatus('exit 0');
  } catch (err) {
    reportError('emit zip', err);
  }
});

/* ---------------- 11. view tabs + boot ---------------- */

function switchView(name) {
  document.querySelectorAll('.view-tab').forEach(t => t.classList.toggle('active', t.dataset.view === name));
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === `view-${name}`));
}
document.querySelectorAll('.view-tab').forEach(t =>
  t.addEventListener('click', () => switchView(t.dataset.view)));

function fillSelect(sel, values, keep = false) {
  if (!keep) sel.textContent = '';
  for (const v of values) {
    const o = el('option', null, v);
    o.value = v;
    sel.appendChild(o);
  }
}

async function boot() {
  try {
    const [meta, examples] = await Promise.all([api('/meta'), api('/examples')]);
    state.meta = meta;
    state.examples = examples;
    $('#meta-version').textContent = meta.version;
    fillSelect($('#sc-dispatch'), meta.dispatch_policies);
    fillSelect($('#synth-picker'), meta.generators, true);
    fillSelect($('#backend-picker'), meta.backends);
    fillSelect($('#objective-picker'), meta.objectives);
    fillSelect($('#example-picker'), examples.map(e => e.name), true);
    fillSelect($('#variant-example-picker'), examples.filter(e => e.format !== 'space').map(e => e.name), true);

    // sensible starting documents
    const first = examples.find(e => e.format === 'mir') || examples.find(e => e.format === 'json');
    if (first) setDocument(first.name, first.format, first.text);
    const space = examples.find(e => e.format === 'space');
    if (space) spaceEditor.value = space.text;
    const variant = examples.find(e => e.format === 'json');
    if (variant) { setVariantFormat('json'); variantEditor.value = variant.text; }

    logCmd('mir --version');
    logOut(`MIR Workbench connected · mir v${meta.version} · backends: ${meta.backends.join(', ')}`);
  } catch (err) {
    reportError('boot', err);
    logOut('could not reach /api — is the backend running?', 'con-err');
  }
  refreshLineNumbers();
}

boot();
