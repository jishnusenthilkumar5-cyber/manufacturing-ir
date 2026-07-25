/* ============================================================
   MIR Workbench — frontend
   Plain ES module, no build step. Talks to the /api backend.
   Sections: STATE · API · CONSOLE · PIPELINE · EDITOR ·
   TOPOLOGY · METRICS · ACTIONS · DECIDE · COMPARE · EMIT ·
   SCHEMA · INIT
   ============================================================ */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt2 = (x) => (typeof x === 'number' && isFinite(x) ? x.toFixed(2) : '—');

/* ============================================================
   STATE
   ============================================================ */
const state = {
  meta: null,            // GET /api/meta
  examples: [],          // GET /api/examples
  format: 'mir',         // editor format toggle
  filename: 'untitled.mir',
  factory: null,         // parsed IR JSON object of last compiled/loaded doc
  analysis: null,        // last /api/analyze analysis
  sim: null,             // last /api/simulate result
  bound: null,           // analytic throughput bound
  bottleneck: null,
  emitFiles: null,       // last /api/emit files map
  variantFormat: 'mir',
  lastReportUrl: null,
};

/* ============================================================
   API — fetch helpers; all errors surface in console/diagnostics
   ============================================================ */
async function api(path, opts = {}) {
  const res = await fetch('/api' + path, opts);
  const ctype = res.headers.get('content-type') || '';
  if (!res.ok) {
    let payload = null;
    try { payload = ctype.includes('json') ? await res.json() : { error: await res.text() }; }
    catch { payload = { error: `HTTP ${res.status}` }; }
    const err = new Error(payload.error || `HTTP ${res.status}`);
    err.payload = payload;
    err.status = res.status;
    throw err;
  }
  if (ctype.includes('json')) return res.json();
  if (ctype.includes('zip')) return res.blob();
  return res.text();
}

const postJSON = (path, body) => api(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

function currentSource() {
  return { format: state.format, text: $('#editor').value };
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

/* Handle an API error: log it, fill diagnostics, mark pipeline stage. */
function surfaceError(cmd, err, stage) {
  const p = err.payload || {};
  logLine(`error: ${p.error || err.message}`, 'console-err');
  if (p.kind) logLine(`kind: ${p.kind}`, 'console-dim');
  if (Array.isArray(p.diagnostics) && p.diagnostics.length) {
    renderDiagnostics(p.diagnostics);
    switchTab('diagnostics');
  }
  if (stage) setChip(stage, 'fail');
  $('#hdr-exit').textContent = 'exit 1';
  $('#hdr-exit').classList.add('err');
}

/* ============================================================
   CONSOLE + DIAGNOSTICS
   ============================================================ */
function logCmd(cmd) {
  const div = document.createElement('div');
  div.className = 'console-cmd';
  div.textContent = '$ ' + cmd;
  $('#panel-console').appendChild(div);
  div.scrollIntoView();
}

function logLine(text, cls = 'console-out') {
  const div = document.createElement('div');
  div.className = cls;
  div.textContent = text;
  $('#panel-console').appendChild(div);
  div.scrollIntoView();
}

function renderDiagnostics(diags) {
  const panel = $('#panel-diagnostics');
  $('#diag-count').textContent = diags.length;
  if (!diags.length) {
    panel.innerHTML = '<div class="muted-note">no diagnostics — document is clean</div>';
    return;
  }
  panel.innerHTML = diags.map((d) => `
    <div class="diag-row">
      <span class="diag-code amber">${esc(d.code || '')}</span>
      <span class="diag-sev ${esc(d.severity || '')}">${esc(d.severity || '')}</span>
      <span>
        <span class="diag-msg">${esc(d.message || '')}</span>
        ${d.entities && d.entities.length ? `<span class="diag-entities"> [${d.entities.map(esc).join(', ')}]</span>` : ''}
        ${d.hint ? `<div class="diag-hint">hint: ${esc(d.hint)}</div>` : ''}
      </span>
    </div>`).join('');
}

function switchTab(name) {
  $$('.ctab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
  $$('.cpanel').forEach((p) => p.classList.toggle('active', p.id === 'panel-' + name));
}
$$('.ctab').forEach((t) => t.addEventListener('click', () => switchTab(t.dataset.tab)));

/* ============================================================
   PIPELINE CHIPS
   ============================================================ */
function setChip(stage, status) {
  const chip = document.querySelector(`.chip[data-stage="${stage}"]`);
  if (!chip) return;
  chip.classList.remove('ok', 'fail', 'active');
  const ico = chip.querySelector('.chip-ico');
  if (status === 'ok') { chip.classList.add('ok'); ico.textContent = '✓'; }
  else if (status === 'fail') { chip.classList.add('fail'); ico.textContent = '✗'; }
  else if (status === 'active') { chip.classList.add('active'); ico.textContent = ''; }
  else { ico.textContent = '·'; }
}

function resetExit() {
  $('#hdr-exit').textContent = 'exit 0';
  $('#hdr-exit').classList.remove('err');
}

/* ============================================================
   EDITOR — textarea + line-number gutter
   ============================================================ */
const editor = $('#editor');
const gutter = $('#editor-gutter');

function refreshGutter() {
  const lines = editor.value.split('\n').length;
  gutter.textContent = Array.from({ length: lines }, (_, i) => i + 1).join('\n');
  gutter.scrollTop = editor.scrollTop;
}

function refreshCursorPos() {
  const upto = editor.value.slice(0, editor.selectionStart).split('\n');
  $('#editor-pos').textContent = `Ln ${upto.length}, Col ${upto[upto.length - 1].length + 1}`;
}

editor.addEventListener('input', () => { refreshGutter(); markDirty(); });
editor.addEventListener('scroll', () => { gutter.scrollTop = editor.scrollTop; });
['keyup', 'click'].forEach((ev) => editor.addEventListener(ev, refreshCursorPos));

function markDirty() {
  $('#editor-canonical').textContent = '';
  $('#editor-dot').className = 'editor-dot';
}

function setFormat(fmt) {
  state.format = fmt;
  $$('#fmt-toggle button').forEach((b) => b.classList.toggle('active', b.dataset.fmt === fmt));
  $('#editor-mode').textContent = fmt === 'mir' ? 'MIR DSL' : 'IR JSON';
}
$$('#fmt-toggle button').forEach((b) => b.addEventListener('click', () => setFormat(b.dataset.fmt)));

function setDocument(text, fmt, filename) {
  editor.value = text;
  setFormat(fmt);
  state.filename = filename || (fmt === 'mir' ? 'untitled.mir' : 'untitled.json');
  $('#editor-filename').textContent = state.filename;
  refreshGutter();
  markDirty();
  updateHeaderFactoid();
}

function updateHeaderFactoid() {
  try {
    if (state.format === 'json') {
      const obj = JSON.parse(editor.value);
      $('#hdr-factory').textContent = obj.meta?.id || '—';
      $('#hdr-provenance').textContent = obj.meta?.provenance?.kind || '—';
      return;
    }
    const m = editor.value.match(/factory\s+"([^"]+)"/);
    $('#hdr-factory').textContent = m ? m[1] : '—';
    const p = editor.value.match(/provenance\s*=\s*(\w+)/);
    $('#hdr-provenance').textContent = p ? p[1] : '—';
  } catch { /* leave as-is */ }
}

/* example picker */
$('#example-picker').addEventListener('change', (e) => {
  const ex = state.examples.find((x) => x.name === e.target.value);
  if (!ex) return;
  if (ex.format === 'space') {
    $('#space-editor').value = ex.text;
    logLine(`loaded ${ex.name} into the design-space editor (open sweep/recommend)`, 'console-dim');
  } else {
    setDocument(ex.text, ex.format, ex.name);
    logCmd(`load examples/${ex.name}`);
  }
  e.target.value = '';
});

/* synth picker */
$('#synth-picker').addEventListener('change', async (e) => {
  const gen = e.target.value;
  e.target.value = '';
  if (!gen) return;
  logCmd(`mir synth ${gen}`);
  try {
    const r = await postJSON('/synth', { generator: gen, options: {} });
    const text = state.format === 'mir' ? r.mir_text : r.json_text;
    setDocument(text, state.format, `${gen}.${state.format === 'mir' ? 'mir' : 'json'}`);
    logLine(`generated synthetic factory '${gen}'`, 'console-ok');
  } catch (err) { surfaceError('synth', err); }
});

/* ============================================================
   TOPOLOGY — render machines / buffers / flows from IR JSON
   ============================================================ */
const STATE_COLORS = {
  busy: '#3ddc84', blocked: '#f0a83a', starved: '#4aa3ff',
  setup: '#b98aff', down: '#ff4d4d', offshift: '#3a424d', idle: '#6b7684',
};
const STATE_LABELS = {
  busy: 'RUNNING', blocked: 'BLOCKED', starved: 'STARVED',
  setup: 'SETUP', down: 'DOWN', offshift: 'OFFSHIFT', idle: 'IDLE',
};

function factoryFromEditor() {
  if (state.format === 'json') {
    try { return JSON.parse(editor.value); } catch { return null; }
  }
  return null;
}

/* Order operations for display: topological order from analysis if present,
   otherwise walk the flows from the inlet. */
function operationOrder(factory, analysis) {
  const topo = analysis?.topology?.analysis || analysis?.topology;
  if (topo?.topological_order?.length) return topo.topological_order;
  const flows = factory.flows || [];
  const ops = (factory.operations || []).map((o) => o.id);
  const order = [];
  const seen = new Set();
  const queue = flows.filter((f) => !f.from_op && f.to_op).map((f) => f.to_op);
  while (queue.length) {
    const op = queue.shift();
    if (seen.has(op)) continue;
    seen.add(op); order.push(op);
    flows.filter((f) => f.from_op === op && f.to_op).forEach((f) => queue.push(f.to_op));
  }
  ops.forEach((o) => { if (!seen.has(o)) order.push(o); });
  return order;
}

function dominantState(fractions) {
  let best = 'idle', bestVal = -1;
  for (const [k, v] of Object.entries(fractions || {})) {
    if (v > bestVal) { bestVal = v; best = k; }
  }
  return best;
}

function cycleLabel(ct) {
  if (!ct) return '';
  if (ct.kind === 'constant') return `constant(${ct.value_s}s)`;
  const args = Object.entries(ct).filter(([k]) => k !== 'kind').map(([, v]) => v).join(', ');
  return `${ct.kind}(${args})`;
}

function renderTopology() {
  const canvas = $('#topo-canvas');
  const factory = state.factory;
  if (!factory) {
    canvas.innerHTML = '<div class="topo-empty" id="topo-empty">compile or load a document, then <span class="amber">analyze</span> / <span class="amber">simulate</span></div>';
    $('#topo-status').textContent = 'no factory compiled';
    return;
  }
  const flows = factory.flows || [];
  const machines = Object.fromEntries((factory.machines || []).map((m) => [m.id, m]));
  const opsById = Object.fromEntries((factory.operations || []).map((o) => [o.id, o]));
  const order = operationOrder(factory, state.analysis);
  const sim = state.sim;
  const summary = sim?.summary;
  const lastRep = sim?.replications?.[sim.replications.length - 1];
  const bufferMeans = lastRep?.buffers || {};
  const cycles = lastRep?.cycles_by_operation || {};

  const inlets = flows.filter((f) => !f.from_op && f.to_op);
  const outlets = flows.filter((f) => f.from_op && !f.to_op);
  const interFlows = flows.filter((f) => f.from_op && f.to_op);
  const shipped = lastRep ? lastRep.output_units : null;

  let html = '<div class="topo-line">';
  html += `
    <div class="topo-endpoint">
      <div class="ep-title">Inlet</div>
      ${inlets.map((f) => `<div class="ep-item">${esc(f.material)}</div>`).join('') || '<div class="ep-item">—</div>'}
      <div class="ep-sub">∞ supply</div>
    </div>`;

  order.forEach((opId, idx) => {
    const op = opsById[opId];
    if (!op) return;
    const machId = (op.machines || [])[0];
    const mach = machines[machId] || {};
    const fracs = summary?.machine_state_fractions_mean?.[machId];
    const st = fracs ? dominantState(fracs) : 'idle';
    const color = STATE_COLORS[st];
    const busyPct = fracs ? (100 * (fracs.busy || 0)) : 0;
    const isBottleneck = state.bottleneck && machId === state.bottleneck;

    // connector before this stage: buffer(s) feeding it, or plain flow line
    const inBufs = interFlows.filter((f) => f.to_op === opId);
    html += '<div class="topo-conn">';
    inBufs.forEach((f) => {
      const bm = bufferMeans[f.id];
      const cap = f.buffer_capacity;
      const level = bm ? bm.mean_occupancy : null;
      const pct = (cap && level != null) ? Math.min(100, 100 * level / cap) : 0;
      const full = cap && level != null && level >= cap - 0.5;
      html += `
        <div class="topo-buf-label">${esc(f.id)} <b>${level != null ? level.toFixed(1) : '·'}</b>/${cap ?? '∞'}</div>
        <div class="topo-buf-bar"><div class="${full ? 'full' : ''}" style="width:${pct}%"></div></div>`;
    });
    html += `<div class="topo-flowline ${sim ? '' : 'paused'}"></div></div>`;

    html += `
      <div class="topo-stage">
        <div class="topo-op-label">${esc(opId)} · <b>${esc(cycleLabel(op.cycle_time))}</b></div>
        <div class="machine-card ${st === 'busy' ? 'busy' : ''} ${st === 'blocked' ? 'blocked' : ''}">
          <div class="mc-head">
            <span class="mc-led" style="background:${color}"></span>
            <span class="mc-state" style="color:${color}">${STATE_LABELS[st]}</span>
            ${isBottleneck ? '<span class="mc-btlnck">BTLNCK</span>' : ''}
          </div>
          <div class="mc-name">${esc(mach.name || machId || '?')}</div>
          <div class="mc-class">${esc(mach.machine_class || '')} · ${mach.num_stations ?? '?'} station${mach.num_stations === 1 ? '' : 's'}</div>
          <div class="mc-prog"><div style="width:${busyPct.toFixed(0)}%;background:${color}"></div></div>
          <div class="mc-stats">
            <span>cycles <b>${cycles[opId] ?? '—'}</b></span>
            <span>busy <b>${fracs ? (100 * (fracs.busy || 0)).toFixed(1) : '—'}%</b></span>
          </div>
        </div>
      </div>`;
  });

  html += `
    <div class="topo-conn"><div class="topo-flowline ${sim ? '' : 'paused'}"></div></div>
    <div class="topo-endpoint outlet">
      <div class="ep-title">Outlet</div>
      <div class="ep-big">${shipped != null ? shipped : '—'}</div>
      <div class="muted-note">units shipped${outlets.length > 1 ? ` · ${outlets.length} outlets` : ''}</div>
    </div>`;
  html += '</div>';

  // note non-serial topologies (assembly merges etc.)
  const topo = state.analysis?.topology?.analysis || state.analysis?.topology;
  if (topo && topo.is_serial_line === false) {
    html += `<div class="topo-extra">non-serial topology — ${order.length} operations shown in topological order; `
      + `merging flows: ${interFlows.map((f) => `${esc(f.from_op)}→${esc(f.to_op)} (${esc(f.material)})`).join(', ')}</div>`;
  }

  canvas.innerHTML = html;
  $('#topo-status').textContent = sim
    ? `simulated · seed ${sim.scenario?.seed} · ${sim.replications?.length ?? 0} reps`
    : (state.analysis ? 'analyzed · static view' : 'compiled · static view');
  $('#topo-clock').textContent = sim ? `T+${fmtClock(sim.scenario?.horizon_s || 0)}` : '';
}

function fmtClock(seconds) {
  const p2 = (n) => String(n).padStart(2, '0');
  const hh = Math.floor(seconds / 3600), mm = Math.floor((seconds % 3600) / 60), ss = Math.floor(seconds % 60);
  return `${p2(hh)}:${p2(mm)}:${p2(ss)}`;
}

/* ============================================================
   METRICS — right pane rendering
   ============================================================ */
function renderCapacityCard() {
  const cap = state.analysis?.capacity?.analysis || state.analysis?.capacity;
  if (!cap) return;
  const topo = state.analysis?.topology?.analysis || state.analysis?.topology;
  state.bound = cap.throughput_upper_bound_units_per_hour ?? null;
  state.bottleneck = cap.bottleneck_machine ?? null;
  $('#c-bound').textContent = state.bound != null ? `${fmt2(state.bound)} u/h` : '—';
  $('#c-bottleneck').textContent = state.bottleneck || '—';
  $('#c-serial').textContent = topo ? (topo.is_serial_line ? 'yes' : 'no') : '—';
  $('#c-exact').textContent = cap.exact != null ? (cap.exact ? 'exact (det. DAG)' : 'upper bound') : '—';
  $('#m-bound-label').textContent = state.bound != null ? `analytic bound ${fmt2(state.bound)}` : 'analytic bound —';
}

function renderSimMetrics() {
  const s = state.sim?.summary;
  if (!s) return;
  const thru = s.throughput_units_per_hour_mean;
  $('#m-throughput').textContent = fmt2(thru);
  $('#m-wip').textContent = fmt2(s.ending_wip_mean);
  const scrap = Object.values(s.scrap_by_operation_mean || {}).reduce((a, b) => a + b, 0);
  $('#m-scrap').textContent = fmt2(scrap);
  $('#m-reps').textContent = state.sim.replications?.length ?? '—';
  const pct = state.bound ? Math.min(100, 100 * thru / state.bound) : 0;
  $('#m-thru-fill').style.width = pct + '%';

  const rows = Object.entries(s.machine_state_fractions_mean || {}).map(([id, f]) => {
    const busy = 100 * (f.busy || 0), blocked = 100 * (f.blocked || 0), starved = 100 * (f.starved || 0);
    const other = Math.max(0, 100 - busy - blocked - starved);
    const st = dominantState(f);
    return `
      <div class="fraction-row">
        <div class="fr-head"><span class="fr-name">${esc(id)}</span><span style="color:${STATE_COLORS[st]}">${st}</span></div>
        <div class="fr-bar">
          <div style="width:${busy}%;background:#3ddc84"></div>
          <div style="width:${blocked}%;background:#f0a83a"></div>
          <div style="width:${starved}%;background:#4aa3ff"></div>
          <div style="width:${other}%;background:#6b7684"></div>
        </div>
      </div>`;
  });
  $('#state-fractions').innerHTML = rows.join('') || '<div class="muted-note">no machines</div>';
}

/* ============================================================
   ACTIONS — toolbar dispatch
   ============================================================ */
const ACTIONS = {
  /* ---- validate ---- */
  async validate() {
    logCmd(`mir validate ${state.filename}`);
    setChip('validate', 'active');
    const r = await postJSON('/validate', { source: currentSource() });
    renderDiagnostics(r.diagnostics);
    if (r.valid) {
      setChip('validate', 'ok');
      logLine(`valid — ${r.diagnostics.length} diagnostic(s)`, 'console-ok');
      $('#editor-dot').className = 'editor-dot ok';
    } else {
      setChip('validate', 'fail');
      logLine(`invalid factory — ${r.diagnostics.length} diagnostic(s)`, 'console-err');
      $('#editor-dot').className = 'editor-dot err';
      switchTab('diagnostics');
    }
  },

  /* ---- fmt ---- */
  async fmt() {
    logCmd(`mir fmt ${state.filename}`);
    const r = await postJSON('/fmt', { source: currentSource() });
    editor.value = r.canonical;
    refreshGutter();
    $('#editor-canonical').textContent = 'canonical ✓';
    logLine(r.changed ? 'reformatted to canonical form' : 'already canonical', r.changed ? 'console-ok' : 'console-dim');
  },

  /* ---- compile (.mir → IR JSON) ---- */
  async compile() {
    if (state.format !== 'mir') { logLine('compile expects a .mir document (toggle format)', 'console-warn'); return; }
    logCmd(`mir compile ${state.filename}`);
    setChip('compile', 'active');
    const r = await postJSON('/compile', { text: editor.value });
    state.factory = JSON.parse(r.json_text);
    setDocument(r.json_text, 'json', state.filename.replace(/\.mir$/, '.json'));
    setChip('compile', 'ok');
    logLine('compiled to canonical IR JSON', 'console-ok');
    renderTopology();
  },

  /* ---- decompile (IR JSON → .mir) ---- */
  async decompile() {
    if (state.format !== 'json') { logLine('decompile expects a .json document (toggle format)', 'console-warn'); return; }
    logCmd(`mir decompile ${state.filename}`);
    const r = await postJSON('/decompile', { text: editor.value });
    setDocument(r.mir_text, 'mir', state.filename.replace(/\.json$/, '.mir'));
    logLine('decompiled to MIR DSL', 'console-ok');
  },

  /* ---- analyze ---- */
  async analyze() {
    logCmd(`mir analyze ${state.filename}`);
    setChip('analyze', 'active');
    const src = currentSource();
    const r = await postJSON('/analyze', { source: src });
    state.analysis = r.analysis;
    renderDiagnostics(r.diagnostics);
    setChip('compile', 'ok');
    setChip('validate', 'ok');
    setChip('analyze', 'ok');
    await ensureFactory(src);
    renderCapacityCard();
    renderTopology();
    const topo = r.analysis?.topology?.analysis || r.analysis?.topology;
    const cap = r.analysis?.capacity?.analysis || r.analysis?.capacity;
    if (topo) {
      logLine(`Topology: ${Object.keys(topo.adjacency || {}).length} operations, ${topo.inlet_flows?.length ?? '?'} inlet(s), ${topo.outlet_flows?.length ?? '?'} outlet(s)`);
      logLine(`Serial line: ${topo.is_serial_line ? 'yes' : 'no'}`);
    }
    if (cap) {
      logLine(`Throughput bound: ${fmt2(cap.throughput_upper_bound_units_per_hour)} units/hour`);
      logLine(`Bottleneck: ${cap.bottleneck_machine || '—'}`, 'console-warn');
    }
  },

  /* ---- simulate ---- */
  async simulate() {
    const sc = currentScenario();
    logCmd(`mir simulate ${state.filename} --horizon-h ${sc.horizon_h} --warmup-h ${sc.warmup_h} --seed ${sc.seed} --replications ${sc.replications} --dispatch ${sc.dispatch}`);
    setChip('simulate', 'active');
    const src = currentSource();
    if (!state.analysis) { try { await ACTIONS.analyze(); } catch { /* surfaced already */ } }
    const r = await postJSON('/simulate', { source: src, scenario: sc });
    state.sim = r;
    setChip('simulate', 'ok');
    await ensureFactory(src);
    renderSimMetrics();
    renderTopology();
    const s = r.summary;
    logLine(`Throughput: ${fmt2(s.throughput_units_per_hour_mean)} ± ${fmt2(s.throughput_units_per_hour_stdev)} units/hour`, 'console-ok');
    for (const [id, f] of Object.entries(s.machine_state_fractions_mean || {})) {
      logLine(`${id}: busy ${(100 * f.busy).toFixed(1)}%, blocked ${(100 * f.blocked).toFixed(1)}%, starved ${(100 * f.starved).toFixed(1)}%, down ${(100 * (f.down || 0)).toFixed(1)}%, offshift ${(100 * (f.offshift || 0)).toFixed(1)}%`, 'console-dim');
    }
    logLine(`Ending WIP: ${fmt2(s.ending_wip_mean)}`);
  },

  /* ---- report ---- */
  async report() {
    const sc = currentScenario();
    logCmd(`mir report ${state.filename} --horizon-h ${sc.horizon_h} --warmup-h ${sc.warmup_h}`);
    const html = await postJSON('/report', { source: currentSource(), scenario: sc });
    showReport(html);
    logLine('report rendered — see report tab', 'console-ok');
  },

  /* ---- decision tools (open modal) ---- */
  sweep() { openDecide('sweep'); },
  recommend() { openDecide('recommend'); },
  sensitivity() { openDecide('sensitivity'); },

  /* ---- compare (open modal) ---- */
  compare() { openModal('#modal-compare'); },

  /* ---- emit ---- */
  async emit() {
    logCmd(`mir emit ${$('#emit-backend').value || 'st'} ${state.filename}`);
    openModal('#modal-emit');
    const r = await postJSON('/emit', { source: currentSource(), backend: $('#emit-backend').value || 'st' });
    state.emitFiles = r.files;
    const names = Object.keys(r.files);
    $('#emit-tree').innerHTML = names.map((n) =>
      `<div class="emit-file" data-file="${esc(n)}">${esc(n)}</div>`).join('');
    $$('#emit-tree .emit-file').forEach((el) => el.addEventListener('click', () => showEmitFile(el.dataset.file)));
    showEmitFile(names.find((n) => n !== 'manifest.json') || names[0]);
    logLine(`emitted ${names.length} file(s): ${names.join(', ')}`, 'console-ok');
  },

  /* ---- schema ---- */
  async schema() {
    logCmd('mir schema');
    const r = await api('/schema');
    $('#schema-content').textContent = JSON.stringify(r, null, 2);
    openModal('#modal-schema');
    logLine('factory JSON schema fetched', 'console-ok');
  },
};

/* Ensure state.factory holds the parsed IR JSON of the current doc. */
async function ensureFactory(src) {
  try {
    if (src.format === 'json') { state.factory = JSON.parse(src.text); return; }
    const r = await postJSON('/compile', { text: src.text });
    state.factory = JSON.parse(r.json_text);
  } catch { /* topology stays stale; errors surfaced by callers */ }
}

$$('.toolbar .tbtn').forEach((btn) => {
  btn.addEventListener('click', async () => {
    const action = btn.dataset.action;
    resetExit();
    btn.classList.add('busy');
    try { await ACTIONS[action](); }
    catch (err) { surfaceError(action, err, ['validate', 'compile', 'analyze', 'simulate'].includes(action) ? action : null); }
    finally { btn.classList.remove('busy'); }
  });
});

/* ============================================================
   REPORT TAB
   ============================================================ */
function showReport(html) {
  const blob = new Blob([html], { type: 'text/html' });
  if (state.lastReportUrl) URL.revokeObjectURL(state.lastReportUrl);
  state.lastReportUrl = URL.createObjectURL(blob);
  $('#report-frame').src = state.lastReportUrl;
  $('#report-open-tab').disabled = false;
  $('#report-note').textContent = '';
  switchTab('report');
}
$('#report-open-tab').addEventListener('click', () => {
  if (state.lastReportUrl) window.open(state.lastReportUrl, '_blank');
});

/* ============================================================
   MODALS — shared open/close
   ============================================================ */
function openModal(sel) { $(sel).hidden = false; }
$$('.modal-backdrop').forEach((bd) => {
  bd.addEventListener('click', (e) => { if (e.target === bd) bd.hidden = true; });
  bd.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', () => { bd.hidden = true; }));
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') $$('.modal-backdrop').forEach((bd) => { bd.hidden = true; });
});

/* ============================================================
   DECIDE — sweep / recommend / sensitivity
   ============================================================ */
function openDecide(which) {
  $('#decide-title').textContent = `Decision tools · ${which}`;
  if (!$('#space-editor').value.trim()) {
    const sp = state.examples.find((x) => x.format === 'space');
    if (sp) $('#space-editor').value = sp.text;
  }
  openModal('#modal-decide');
}

function decideSpace() {
  try { return JSON.parse($('#space-editor').value); }
  catch (e) { throw Object.assign(new Error('design space is not valid JSON: ' + e.message), { payload: { error: 'design space is not valid JSON', kind: 'invocation' } }); }
}

async function runDecide(kind) {
  const results = $('#decide-results');
  results.innerHTML = '<div class="muted-note">running…</div>';
  const sc = currentScenario();
  try {
    if (kind === 'sweep') {
      logCmd(`mir sweep ${state.filename} sweep-space.json`);
      const r = await postJSON('/sweep', { source: currentSource(), space: decideSpace(), scenario: sc, workers: null });
      renderSweep(r, results);
      logLine(`sweep evaluated ${r.points?.length ?? 0} design point(s)`, 'console-ok');
    } else if (kind === 'recommend') {
      const objective = $('#decide-objective').value || 'throughput';
      const topK = parseInt($('#decide-topk').value, 10) || 3;
      logCmd(`mir recommend ${state.filename} sweep-space.json --objective ${objective} --top-k ${topK}`);
      const r = await postJSON('/recommend', { source: currentSource(), space: decideSpace(), scenario: sc, workers: null, objective, top_k: topK });
      renderRecommend(r, results);
      logLine(r.verdict || 'recommendation complete', 'console-ok');
    } else {
      const percent = parseFloat($('#decide-percent').value) || 10;
      logCmd(`mir sensitivity ${state.filename} --percent ${percent}`);
      const r = await postJSON('/sensitivity', { source: currentSource(), scenario: sc, percent });
      renderSensitivity(r, results);
      logLine(`sensitivity ranked ${r.entries?.length ?? 0} parameter(s)`, 'console-ok');
    }
  } catch (err) {
    results.innerHTML = `<div class="console-err">${esc(err.payload?.error || err.message)}</div>`;
    surfaceError(kind, err);
  }
}
$('#run-sweep').addEventListener('click', () => runDecide('sweep'));
$('#run-recommend').addEventListener('click', () => runDecide('recommend'));
$('#run-sensitivity').addEventListener('click', () => runDecide('sensitivity'));

function paramCols(points) {
  const cols = new Set();
  points.forEach((p) => Object.keys(p.parameters || {}).forEach((k) => cols.add(k)));
  return Array.from(cols);
}

function renderSweep(r, el) {
  const cols = paramCols(r.points || []);
  const best = Math.max(...(r.points || []).map((p) => p.throughput_mean));
  el.innerHTML = `
    <div class="section-title">Sweep · ${esc(r.factory_id)} · baseline ${fmt2(r.baseline?.throughput_mean)} u/h · bottleneck ${esc(r.baseline?.bottleneck || '—')}</div>
    <table class="rtable">
      <tr><th>#</th>${cols.map((c) => `<th>${esc(c)}</th>`).join('')}<th>thru u/h</th><th>Δ%</th><th>wip</th><th>scrap</th><th>bottleneck</th></tr>
      ${(r.points || []).map((p) => `
        <tr class="${p.throughput_mean === best ? 'best' : ''}">
          <td>${p.index}</td>
          ${cols.map((c) => `<td class="num">${esc(p.parameters?.[c] ?? '—')}</td>`).join('')}
          <td class="num">${fmt2(p.throughput_mean)} ± ${fmt2(p.throughput_stdev)}</td>
          <td class="num">${fmt2(p.delta_percent)}</td>
          <td class="num">${fmt2(p.ending_wip)}</td>
          <td class="num">${fmt2(p.scrap)}</td>
          <td>${esc(p.bottleneck || '—')}</td>
        </tr>`).join('')}
    </table>`;
}

function renderRecommend(r, el) {
  el.innerHTML = `
    <div class="section-title">Recommend · objective ${esc(r.objective)} · baseline score ${fmt2(r.baseline_score)}</div>
    <table class="rtable">
      <tr><th>rank</th><th>score</th><th>parameters</th><th>thru u/h</th><th>Δ%</th><th>bottleneck</th></tr>
      ${(r.recommendations || []).map((rec) => `
        <tr class="${rec.rank === 1 ? 'best' : ''}">
          <td>#${rec.rank}</td>
          <td class="num">${fmt2(rec.score)}</td>
          <td>${esc(Object.entries(rec.point?.parameters || {}).map(([k, v]) => `${k}=${v}`).join('  '))}</td>
          <td class="num">${fmt2(rec.point?.throughput_mean)}</td>
          <td class="num">${fmt2(rec.point?.delta_percent)}</td>
          <td>${esc(rec.point?.bottleneck || '—')}</td>
        </tr>`).join('')}
    </table>
    <div class="verdict-card">${esc(r.verdict || '')}</div>`;
}

function renderSensitivity(r, el) {
  const maxImpact = Math.max(1e-9, ...(r.entries || []).map((e) => Math.abs(e.absolute_impact)));
  el.innerHTML = `
    <div class="section-title">Sensitivity · ±${esc(r.percent)}% · baseline ${fmt2(r.baseline?.throughput_mean)} u/h</div>
    ${(r.entries || []).map((e) => `
      <div class="sens-row">
        <span class="sens-path" title="${esc(e.path)}">#${e.rank} ${esc(e.path)}</span>
        <span class="sens-track"><div style="left:0;width:${(100 * Math.abs(e.absolute_impact) / maxImpact).toFixed(1)}%"></div></span>
        <span class="sens-val">${fmt2(e.absolute_impact)} u/h</span>
      </div>
      <div class="muted-note" style="margin-left:8px">kind ${esc(e.kind)} · base ${esc(e.baseline_value)} · −${esc(r.percent)}% → ${fmt2(e.lower_throughput_mean)} · +${esc(r.percent)}% → ${fmt2(e.upper_throughput_mean)}</div>
    `).join('') || '<div class="muted-note">no tunable parameters found</div>'}`;
}

/* ============================================================
   COMPARE — baseline (editor) vs variant
   ============================================================ */
$$('#variant-fmt-toggle button').forEach((b) => b.addEventListener('click', () => {
  state.variantFormat = b.dataset.fmt;
  $$('#variant-fmt-toggle button').forEach((x) => x.classList.toggle('active', x.dataset.fmt === state.variantFormat));
}));

$('#variant-example-picker').addEventListener('change', (e) => {
  const ex = state.examples.find((x) => x.name === e.target.value);
  if (ex && ex.format !== 'space') {
    $('#variant-editor').value = ex.text;
    state.variantFormat = ex.format;
    $$('#variant-fmt-toggle button').forEach((x) => x.classList.toggle('active', x.dataset.fmt === ex.format));
  }
  e.target.value = '';
});

function variantSource() {
  return { format: state.variantFormat, text: $('#variant-editor').value };
}

$('#run-compare').addEventListener('click', async () => {
  const results = $('#compare-results');
  results.innerHTML = '<div class="muted-note">comparing…</div>';
  logCmd(`mir compare ${state.filename} <variant>`);
  try {
    const r = await postJSON('/compare', { baseline: currentSource(), variant: variantSource(), scenario: currentScenario() });
    const rows = [
      ['Throughput (u/h)', `${fmt2(r.baseline_throughput_mean)} ± ${fmt2(r.baseline_throughput_stdev)}`, `${fmt2(r.variant_throughput_mean)} ± ${fmt2(r.variant_throughput_stdev)}`],
      ['Paired Δ', '—', `${fmt2(r.paired_delta_mean)} ± ${fmt2(r.paired_delta_stdev)} (${fmt2(r.delta_percent)}%)`],
      ['Bottleneck', r.bottleneck_before || '—', r.bottleneck_after || '—'],
      ['Ending WIP', fmt2(r.ending_wip_before), fmt2(r.ending_wip_after)],
      ['Scrap', fmt2(r.scrap_before), fmt2(r.scrap_after)],
    ];
    results.innerHTML = `
      <div class="section-title">${esc(r.baseline_id)} vs ${esc(r.variant_id)}</div>
      <table class="rtable">
        <tr><th>metric</th><th>baseline</th><th>variant</th></tr>
        ${rows.map(([k, a, b]) => `<tr><td>${esc(k)}</td><td class="num">${esc(a)}</td><td class="num">${esc(b)}</td></tr>`).join('')}
      </table>
      <div class="verdict-card">${esc(r.verdict || '')}</div>`;
    logLine(r.verdict || 'comparison complete', 'console-ok');
  } catch (err) {
    results.innerHTML = `<div class="console-err">${esc(err.payload?.error || err.message)}</div>`;
    surfaceError('compare', err);
  }
});

$('#run-compare-report').addEventListener('click', async () => {
  logCmd(`mir report ${state.filename} <variant> --compare`);
  try {
    const html = await postJSON('/report/compare', { baseline: currentSource(), variant: variantSource(), scenario: currentScenario() });
    $('#modal-compare').hidden = true;
    showReport(html);
    logLine('comparison report rendered — see report tab', 'console-ok');
  } catch (err) { surfaceError('report/compare', err); }
});

/* ============================================================
   EMIT — file tree, viewer, zip download
   ============================================================ */
function showEmitFile(name) {
  if (!state.emitFiles || !name) return;
  $$('#emit-tree .emit-file').forEach((el) => el.classList.toggle('active', el.dataset.file === name));
  $('#emit-content').textContent = state.emitFiles[name] ?? '';
}

$('#emit-download').addEventListener('click', async () => {
  try {
    const blob = await postJSON('/emit/zip', { source: currentSource(), backend: $('#emit-backend').value || 'st' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'emitted.zip';
    a.click();
    URL.revokeObjectURL(url);
    logLine('downloaded emitted.zip', 'console-ok');
  } catch (err) { surfaceError('emit/zip', err); }
});

/* ============================================================
   INIT — fetch meta + examples, populate pickers, load default doc
   ============================================================ */
async function init() {
  refreshGutter();
  try {
    const [meta, examples] = await Promise.all([api('/meta'), api('/examples')]);
    state.meta = meta;
    state.examples = examples;
    $('#meta-version').textContent = meta.version;

    $('#example-picker').innerHTML = '<option value="">examples…</option>'
      + examples.map((e) => `<option value="${esc(e.name)}">${esc(e.name)}</option>`).join('');
    $('#variant-example-picker').innerHTML = '<option value="">examples…</option>'
      + examples.filter((e) => e.format !== 'space').map((e) => `<option value="${esc(e.name)}">${esc(e.name)}</option>`).join('');
    $('#synth-picker').innerHTML = '<option value="">synth…</option>'
      + meta.generators.map((g) => `<option value="${esc(g)}">${esc(g)}</option>`).join('');
    $('#sc-dispatch').innerHTML = meta.dispatch_policies.map((d) => `<option value="${esc(d)}">${esc(d)}</option>`).join('');
    $('#decide-objective').innerHTML = meta.objectives.map((o) => `<option value="${esc(o)}">${esc(o)}</option>`).join('');
    $('#emit-backend').innerHTML = meta.backends.map((b) => `<option value="${esc(b)}">${esc(b)}</option>`).join('');

    const sp = examples.find((e) => e.format === 'space');
    if (sp) $('#space-editor').value = sp.text;

    const first = examples.find((e) => e.format === 'mir') || examples.find((e) => e.format === 'json');
    if (first) {
      setDocument(first.text, first.format, first.name);
      logCmd(`load examples/${first.name}`);
    }
    logLine(`MIR Workbench ready — mir v${meta.version} · backends: ${meta.backends.join(', ')}`, 'console-dim');
  } catch (err) {
    logLine('failed to reach /api — is the backend running? ' + (err.message || ''), 'console-err');
  }
}

init();
