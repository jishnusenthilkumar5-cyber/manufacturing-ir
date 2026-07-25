# Demo guide

Yes, there's a demo, and it's a good one. The line in it is deliberately broken in
a way that's invisible in a spreadsheet and obvious in three seconds here.

Two ways to run it:

- **Browser workbench** with a built-in guided walkthrough. Best for a link you
  send someone, and for screen recording.
- **CLI**, eight commands. Best if you're demoing to an engineer.

---

## The story the demo tells

Three stations on a line. Cycle times 20s, 55s, 25s. Twenty-unit buffers between
them. It looks fine on paper.

It isn't. Station 2 is 2.75× slower than station 1, so:

| | machine-01 | machine-02 | machine-03 |
|---|---|---|---|
| busy | 36.4% | **100%** | 45.5% |
| blocked | **63.6%** | 0% | 0% |
| starved | 0% | 0% | **54.5%** |

Two thirds of the line is standing still waiting on one station. Throughput is
65.48 units/hour against a ceiling of 65.45 — the line is pinned to its worst
station and no amount of running it harder helps.

Then the payoff. Search the fixes:

| rank | change | throughput | Δ | new bottleneck |
|---|---|---|---|---|
| 1 | second station at machine-02, cycle −25% | 144.00 u/h | **+119.9%** | machine-03 |
| 2 | second station at machine-02 | 130.91 u/h | +99.9% | machine-02 |
| 3 | cycle −25% only | 87.26 u/h | +33.3% | machine-02 |

The best fix more than doubles output, **and the bottleneck moves to
machine-03** — which is the next decision, surfaced before anyone spent money on
the first one. That moment is the demo. Don't rush past it.

---

## Browser demo

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,web]"
.venv/bin/uvicorn webapp.server:app --port 8000
```

Open `http://localhost:8000/` and click **▶ guided demo** in the top right.

Six steps, auto-advancing, roughly 90 seconds. Every step drives the same `/api`
the toolbar drives, so the demo can't show anything the product can't do.

| # | Step | What appears |
|---|---|---|
| 1 | A factory, written as source code | The `.mir` source loads into the editor |
| 2 | The compiler checks it | Validation, numbered diagnostics |
| 3 | Analytic capacity | Bound 65.45 u/h, bottleneck machine-02 |
| 4 | Simulate | Topology lights up: blocked / running / starved |
| 5 | Decide | Ranked table, +119.9%, bottleneck moves |
| 6 | Hand off | IEC 61131-3 Structured Text, one file per machine |

Controls: `→` / `←` step, `space` pauses, `esc` button exits. Step 6 holds on
screen instead of auto-closing, so the emitted PLC code stays up at the end.

**Send `http://your-url/?demo=1` and the walkthrough autostarts.** That's the link
to put in the application if you have somewhere to deploy it. `render.yaml` and
the `Dockerfile` are already in the repo, so any container host works:

```bash
docker build -t mir-workbench .
docker run -p 8000:8000 mir-workbench
```

### Recording it

- Window at 1660×1000 or wider. The workbench has a 1640px minimum width and will
  scroll horizontally below that, which looks bad on video.
- Let the guided demo drive. Don't narrate over it on the first pass — the
  on-screen captions already say it, and talking over them competes.
- If you want manual control, hit `space` on step 4 and sit on the blocked /
  starved topology for an extra beat. That frame is the whole problem statement.
- Screen record at step 5 without cutting. Watching the ranked table populate
  live is more convincing than a still of the result.

---

## CLI demo

For an engineer audience, this lands harder than the UI.

```bash
mir synth unbalanced-line -o line.json      # a factory, generated, no customer data
mir validate line.json                       # numbered diagnostics
mir analyze line.json                        # ceiling 65.45 u/h, bottleneck machine-02
mir simulate line.json --horizon-h 24 --warmup-h 1 --seed 42
mir sensitivity line.json --percent 10       # which knob actually matters
mir recommend line.json space.json --top-k 3 # ranked fixes
mir report line.json -o line.html            # one self-contained offline file
mir emit st line.json -o generated-st        # Structured Text hand-off
```

The design space for `recommend`:

```json
{
  "machines.machine-02.num_stations": [1, 2],
  "operations.operation-02.cycle_time_scale": [1.0, 0.75]
}
```

Two things to point out while it runs:

**Determinism.** Run `mir simulate` twice with the same seed. Byte-identical
output. Then run it again with `--seed 7` and show the numbers move. Reviewable
simulation is the pitch; this is the proof.

**Sensitivity finds the one knob that matters.** Of eight tunable parameters, one
has non-zero impact:

```
1 | operations.operation-02.cycle_time_scale | cycle_time | +7.26 | -5.96 | 7.26
2 | flows.buffer-01.buffer_capacity          | buffer_capacity | +0.00 | +0.00 | 0.00
...
```

Adding buffer does nothing. Every plant manager's first instinct is to add buffer.

---

## Things that will get asked

**"Is the simulation any good, or is it a toy?"** The analytic pass and the
simulator agree to within 0.05% on this line (65.45 vs 65.48), and they're
independent implementations. `tests/test_sim_vs_analytic.py` checks that
agreement across the catalog. The bound is exact only for deterministic
single-outlet DAGs, and the pass emits `MIR100` and tells you when it isn't.

**"Where's the real factory data?"** There isn't any, on purpose. Everything runs
on synthetic factories from `mir synth`. That's a real limitation and worth saying
plainly rather than dodging — it means nothing is calibrated against a plant yet.

**"Can I run the emitted PLC code?"** No, and it says so in a comment header at
the top of every emitted file. It's a reviewable hand-off to a controls engineer,
not generated control logic.

**"Why not just use FlexSim / Plant Simulation / AnyLogic?"** They simulate. They
don't type-check, don't diff, don't version, don't produce a stable machine-readable
contract, and don't lower to controls code. Answer with the artifact: show
`mir fmt` producing canonical, byte-stable output and point out that this means a
factory design fits in a pull request.

---

## Before you send the link

```bash
.venv/bin/python -m pytest        # 289 passing as of this writing
```

Then run the guided demo once end to end on the deployed URL, not just locally.
Cold-start on a free container tier can take long enough that a partner clicking
your link gives up before the page loads.
