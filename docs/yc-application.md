# YC application — "What is your company going to make?"

Drafts below are built only from what's in this repo. Anything I couldn't verify
from the code is marked `[VERIFY]` — replace or cut those before you submit.

---

## The answer (primary, ~180 words)

We're building a compiler for factories.

A production line today gets designed twice. First in spreadsheets and simulation
tools like Siemens Plant Simulation or FlexSim, which are click-driven, cost five
figures a seat `[VERIFY the pricing claim]`, and produce models nobody can diff or
code-review. Then, once the design is agreed, a controls engineer hand-writes the
PLC program from scratch. The two artifacts drift apart from day one, and the
reasoning behind the layout lives in someone's head.

Manufacturing IR makes the factory a source file. You describe a line in four
primitives: machines, operations, material flows, signals. The compiler
type-checks it and reports numbered diagnostics the way any compiler does. It
then computes the capacity ceiling in closed form, runs a deterministic
discrete-event simulation, searches a bounded space of design alternatives and
ranks them by throughput, and lowers the result to IEC 61131-3 Structured Text
for the controls team.

Same input and same seed give the same answer every run, and the whole thing is
text, so it version-controls and reviews like code.

---

## Shorter (~90 words, if you want room elsewhere)

We're building a compiler for factories. You write a production line as a source
file in four primitives, and the compiler type-checks it, computes the throughput
ceiling analytically, simulates it deterministically, ranks the design changes
worth paying for, and emits IEC 61131-3 Structured Text for the controls team.
Today that work is split between spreadsheets, five-figure GUI simulation tools,
and hand-written PLC code that immediately drifts from the design. We make it one
reviewable artifact that produces the same answer every time.

---

## Longer (if a later question asks you to expand)

**What the compiler does, in order.**

1. **Author.** A `.mir` source file describes the line. Four primitives, nothing
   else: `Machine`, `Operation`, `MaterialFlow`, `Signal`. It compiles to
   canonical JSON and decompiles back losslessly, so text and data are the same
   artifact.
2. **Check.** Structural and semantic passes emit numbered diagnostics, MIR001
   through MIR031. Dangling references, unreachable operations, impossible batch
   ratios get caught at author time.
3. **Bound.** An analytic capacity pass propagates batch quantities and yield
   backward from the outlet and finds the binding resource. On a deterministic
   DAG the bound is exact, and the pass reports whether it is rather than asking
   you to trust it.
4. **Simulate.** A discrete-event kernel models blocking, starvation, setup,
   yield loss, transport, stochastic downtime, assembly, rework, shift calendars,
   and dispatch policy. Seven machine states, integrated over the measurement
   window. Same seed, same output.
5. **Decide.** Sweep a bounded design space, rank alternatives by throughput or
   throughput per WIP, and run one-at-a-time sensitivity. Every point is
   evaluated against the baseline with paired seeds, so the comparison is a
   controlled experiment rather than two unrelated runs.
6. **Hand off.** Emit one vendor-neutral Structured Text skeleton per machine,
   plus a manifest: the state enum, counters, and function blocks a controls
   engineer fills in.

**Why an IR and not another simulator.** LLVM won because everyone agreed on the
representation in the middle, not because it had the best optimizer. Manufacturing
has no such layer. CAD, MES, ERP, simulation, and PLC code each carry a private,
partial model of the same plant, and nothing can be checked across them. The
four primitives are the bet: a semantic layer small enough to be agreed on and
expressive enough to compile from and to.

**What we've deliberately not built yet.** No PLC, SCADA, historian, CAD, MES, or
ERP connectors. No deployable control logic. No real-data calibration. The
Structured Text output is labelled non-deployable and refuses to overwrite a
non-empty directory. Getting the representation and the semantics right comes
before connecting anything to a machine that can hurt someone.

**Where it is now.** Working compiler, simulator, decision layer, HTML reports,
Structured Text backend, browser workbench, and 289 passing tests. Runs entirely
on synthetic factories, so nothing depends on customer data to demo.

---

## Notes before you submit

- Every number in these drafts is real and reproducible from this repo. The 289
  test count and the demo figures below come from an actual run, so re-run
  `pytest` before submitting in case the count moved.
- The only unverified claim is competitor seat pricing. Either check it or cut it
  — YC partners will know the market better than the draft does.
- YC asks about market, customers, and traction in separate questions. This answer
  stays on the product on purpose. Don't pull go-to-market into it.
- If you have even one design engineer or integrator who has looked at this, a
  single concrete sentence about what they said is worth more than any adjective
  in the draft.
