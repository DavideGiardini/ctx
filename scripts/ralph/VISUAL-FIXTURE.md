# Visual regression fixture — the loop's standing eye test

The Ralph loop shipped a batch of compression-UI bugs (violet K bar, no blank line
before a K, wrong range-selection style) because it **could not see the rendered
app**: the semantic `ctx_snapshot` honestly reported state while the pixels were
wrong. `tools/agent/visual.py` gives the loop eyes. This fixture proves those eyes
still work — re-run it **whenever the loop's visual gate or the row-rendering code
changes**, so the blind spot cannot silently reopen.

## What it is

A set of **known-missed visual bugs**, each rendered as a *broken/fixed pair* under
one shared, VLM-checkable intent sentence. The variants force the defect (or its
fix) **regardless of whether the real code is currently fixed**, so the fixture
keeps discriminating after the Phase 3e fixes land. The **judge is your own
vision**: `Read` each PNG and decide PASS/FAIL against its intent. There is no
model-calling tool to calibrate — you are the judge.

A gate that only ever says "pass" is worse than none. The fixture's whole point is
to catch a miscalibrated eye: **every `*__PASS.png` must judge PASS and every
`*__FAIL.png` must judge FAIL.** If any pair does not discriminate, the visual gate
is broken — fix it before trusting it on real tasks.

## How to run it

From the repo root (cairosvg is ephemeral — no permanent dependency):

```
uv run --with cairosvg==2.9.0 python -m tools.agent.visual fixture /tmp/ctx-visual-fixture
```

This writes, for each bug, `<bug>__FAIL.png` and `<bug>__PASS.png` plus a
`manifest.json` mapping every PNG to its `intent` and `expected_verdict`. Then:

1. `Read` `manifest.json`.
2. For each entry, `Read` the PNG and judge it **against its `intent` string only**
   — PASS if the render satisfies the intent, FAIL if it violates it.
3. Confirm your verdict equals `expected_verdict` for **every** PNG.

If they all match, the visual gate is calibrated. Any mismatch = a broken gate.

## The bugs in the fixture

| bug | state | what the eye must catch |
|---|---|---|
| `task-40-blank-line-before-K` | `k-after-assistant` | a blank line (a `Separator` widget the list places) separating a K from the assistant turn directly above it (pixel-level vertical spacing — `qa-tester` **cannot** see this) |
| `task-41-range-selection-contiguous-hover-style` | `range-selection` | a multi-node range reads as one block: grey hover-style background + bold role-colored left bar on every selected row, **contiguous across the inter-row gaps** (the separators between selected rows go grey) — not solid blue rows with default-colored gaps |
| `task-49-selection-bar-no-bleed-in-gap` | `range-selection` | within a multi-node range, the grey separator bridging two selected rows shows **no** colored left bar — each row's bar stops at its own content, none bleeds down through the gap (pixel-level; queryable proxy is only "the separator carries no border") |
| `task-39-K-bar-colour` (calibration only) | `committed-K` | the K's left bar is context-green, not violet (this one is *also* a one-line `ctx_snapshot` `colors:` assertion — kept only to calibrate the gate's colour discrimination, not as evidence the visual capability is needed) |

The task-40 and task-41 pairs are the load-bearing cases: genuinely pixel-level bugs
no queryable proxy captures. task-40 — the `__FAIL` render shows the K flush against
the assistant above it; the `__PASS` render keeps the blank-line separator before the
K. task-41 —
the `range-blue` (FAIL) render shows solid-blue selected rows with dark gaps between
them; the `range-grey` (PASS) render shows the grey hover-style block with role-colored
bars bridged across the gaps.

## Adding a bug

When a *visual* regression slips through, add it here so it can't recur:

1. If a new screen is needed, add a named state to `STATES` in
   `tools/agent/visual.py` (a Pilot keystroke script reaching it).
2. Add a broken/fixed variant pair to `_apply_pre_variant` / `_apply_post_variant`
   (force the defect *and* its fix, independent of the real code's current state).
3. Add a `FIXTURE` entry: `bug`, `state`, one `intent` sentence, `bad`, `good`.
4. Re-run the fixture and confirm both directions discriminate.

Prefer **pixel-level** bugs (spacing, alignment, contiguous highlight, "reads as
one block") — the ones a queryable assertion genuinely cannot express. A bug that
is really a one-line `ctx_snapshot` assertion (like the K colour) belongs in a unit
test, not here (mark it calibration-only if you keep it).
