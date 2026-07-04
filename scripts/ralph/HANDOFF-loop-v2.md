# Handoff — Give the Ralph loop *eyes* before resuming the feature loop

**Audience:** a fresh Claude Code conversation in the `ctx` repo, no prior context.
**Goal:** close the one structural blind spot that let ~30 Ralph iterations ship a
compression UI with visual bugs — the loop **cannot see the rendered app** — then hand
back to the feature loop (Phase 3e tasks 33–45 in `scripts/ralph/PRD.md`). Do **not**
start the Phase 3e feature tasks yet; this handoff is about the loop that builds them.

> **This handoff has already been validated by experiment.** The findings in §2 are not
> hypotheses — they were reproduced live in a review session (caching test, working
> rasterize pipeline, reachability trace). Trust them, but re-run the one-liners in §2 if
> you want to see for yourself before building on them.

---

## 1. The post-mortem, corrected

Sprint 3 (compression + context transparency) was built by an attended Ralph loop.
Design was heavily grilled (ADR-0016). Despite that, review + qa + hands-on testing
found a batch of UI bugs, filed as **Phase 3e (33–45)** — read them; they are the
symptom catalog. They cluster perfectly: **framework-free core held up** (code-blind
tests + mutmut behind it), **everything only judgable by looking at the screen was
broken** — diff view is a single-pane text dump, the K node is violet not green, no
blank line before a K, range selection is the wrong style, inspector splits dump plain
text, transient hints persist as graph nodes.

The original handoff blamed **two** limits. Testing showed only **one** is real:

- **Limit (b) — no visual perception. REAL and the root cause.** The qa-tester couldn't
  see the screen, so tasks encoded appearance as *snapshot-state* proxies. The diff task
  passed because `describe_state()` honestly reported `diff: N regions` (true!) while the
  render was broken. The check verified the wrong property *by design*.
- **Limit (a) — "stale code this iteration." MOSTLY A PHANTOM.** See §2.1. A fresh
  per-iteration MCP server means the qa-tester's launch is the *first* import and it
  *does* see your just-edited code. Staleness only bites a *second* launch in one
  process. This is a caveat wording + policy fix, not an engineering workstream.

So the fix is narrow: **give the loop a way to look at the rendered app, and let the
agent decide when looking (vs a queryable assertion) is warranted** — mirroring how
PROMPT.md step 3 already delegates the "do I need a test?" judgment.

---

## 2. Verified findings (reproduce these if you doubt them)

### 2.1 The stale-code limit is a phantom for the normal flow

Mechanism: `HarnessApp` loads via module path, so `app_loader.load_app` uses
`importlib.import_module` (`app_loader.py:35`) — it honors the `sys.modules` cache. The
MCP server is a **stdio subprocess of each `claude -p` iteration** (`loop.sh:67`) and
imports **no** `ctx.*` at startup (`mcp_server.py` only imports `textual_mcp` +
`snapshot`, which is Textual-free). So `ctx.*` is first imported at the **first
`textual_launch`** of the process.

Test run (reproducible): edit a visible constant *before any launch this session*, then
launch → the change **appears**. Edit again, relaunch in the *same* process → the second
change **does not** appear (still shows the first). Conclusion: fresh process = current
disk; only a relaunch-in-process is stale. In Ralph each iteration is a fresh process and
qa-tester launches once, so it drives current code. The residual risk is narrow: the main
agent drives the app itself, *then* edits, *then* delegates → qa's launch is the second.

**Kill the risk by construction, don't try to answer "does that happen?":** capture
visual checks via **Pilot in a fresh subprocess** (each `uv run python …` is a new
process reading current disk — proven below). Leave the live MCP server for behavioral
QA, where single-launch-per-iteration already sees current code.

### 2.2 The rasterize pipeline works and a vision model reads it cleanly

- `textual_screenshot(format="svg")` → `App.export_screenshot()` (public API,
  `.venv/.../textual_mcp/server.py:221`) returns SVG. The **default `format="text"`** is a
  colorless Rich grid; SVG is the one with color. Neither is a PNG, which is why the
  review resorted to grepping `<rect>` fills — that was the missing capability, not a fix.
- **SVG→PNG:** `uv run --with cairosvg python -c "import cairosvg; cairosvg.svg2png(...)"`
  works **offline** (ephemeral install, no permanent dep). (Snap-confined `inkscape`
  **cannot** read `/tmp` — its sandbox has a private `/tmp`; avoid it. Use cairosvg.)
- **The role colors survive** as `<rect>` fills: `#3b82f6` (user), `#f97316` (assistant),
  and the compression bar as its palette color. A vision model reading the PNG sees the
  bar colors, the two-line row layout, the pane split, and vertical spacing — i.e. every
  property tasks 37–41 are about. Proven by rendering `HarnessApp` via Pilot, exporting
  SVG, rasterizing, and reading the PNG back.
- **Strip `@font-face` remote-url blocks** from the SVG before rasterizing so cairosvg
  falls back to a local monospace font (no network). One `re.sub` does it.

### 2.3 The buggy states are reachable headlessly (no harness seeding needed)

- **Compression K node:** Edit mode (`esc`) → select a node → `c` (`app.py:56` →
  `action_compress`, `app.py:588`) → either `ctrl+d` to draft (TestProvider returns the
  canned summary) or type a summary → `ctrl+s` (`app.py:724` → `core.commit_compression`,
  `conversation.py:503`, builds `Node.compression`). No long conversation required.
- **Full-screen diff view:** the `g d` chord (`app.py:412` `on_key`) on a **drifted
  assistant** node. Drift is structural — it only exists *after* a compression/expand
  changes what a turn's prefix folds to. Minimal path: one canned turn → compress a node
  in that turn's context → the assistant turn now drifts → `g d` opens the two-pane diff.
  Requires `ui.show_context_drift` on (default True, `config.py:56`).

### 2.4 Color/structure are already partly queryable (so the VLM isn't always needed)

`ctx_snapshot` already emits a `colors:` line, e.g.
`context=#22c55e compression=#a855f7`. **Task 39 ("compression color = context color") is
a one-line assertion**, no vision. Pane count / split presence (37, 38) are discrete
structure, checkable via `describe_state()` fields or a small widget-geometry accessor.
The genuinely pixel-level bugs (40 blank line, 41 contiguous highlight, "reads as one
block") are what actually need a rendered image. **Do not force everything through a
VLM** — see §3.

---

## 3. The plan (converged, smaller than the original)

The loop already trusts the agent to judge whether a task needs a *test* (PROMPT.md
step 3). Visual verification mirrors that: **give the capability + one judgment prompt,
don't prescribe a taxonomy.**

### WS-A — Visual-acceptance capability (do first; this is the whole fix)

Build a small, reusable path the agent (or qa-tester) can invoke:

1. **Drive → SVG via Pilot in a fresh subprocess** (immune to §2.1 caching). A helper
   that instantiates `HarnessApp`, runs a short keystroke script to reach a **named
   state** (`fresh`, `committed-K`, `drift-diff` — see §2.3), and returns/writes the SVG.
2. **Rasterize** SVG→PNG with cairosvg (strip `@font-face` first). Write the PNG to a
   path the agent can `Read` (the `Read` tool renders PNG/JPG visually; SVG it does not).
3. **Judge** — the agent/qa-tester `Read`s the PNG and judges it against the task's
   **one-line visual intent**. No new model-calling MCP tool, no separate judge to
   calibrate — reuse the agent's own vision.

Keep it thin and in `tools/agent/*` / `scripts/ralph/*`; no framework deps in
`ctx/core/*` or `ctx/models/*`.

**Optional floor:** `pytest-textual-snapshot` (Textualize's SVG-regression tool; **not
installed**, no baselines yet) gives deterministic "did anything visually change vs a
blessed baseline" in `check.sh`. Adopt it if you want a cheap regression net; it detects
*change*, not *correctness*, so it complements the VLM, not replaces it.

**Acceptance:** on a deliberately-broken render (e.g. force the K bar violet) the judge
**FAILs** with a clear reason; on the fix it **PASSes** — same intent string, both
directions. A judge that only ever says "pass" is worse than none.

### WS-B — Step-7 judgment prompt + spec-the-visible-outcome habit

- **PROMPT.md step 7**, symmetric to step 3: *"Decide your verification strategy. If the
  task's acceptance is about appearance (color, layout, spacing, alignment), ask whether a
  queryable assertion truly captures it or whether you need to look at the rendered
  result. If you look, keep a deterministic assertion as the floor."* Then trust the
  agent. Replace the false limit-(a) caveat with the §2.1 truth; replace the limit-(b)
  "assert queryable state" instruction with the above.
- **`.claude/skills/ralph-tasks/` + `PRD.template.md`:** a UI task's acceptance must state
  the **visible outcome** (reference widget / mock / VLM-checkable sentence). The decision
  of *what right looks like* lives in the spec; the decision of *how to check it* lives
  with the agent. This is the guard against the original failure — the implementing agent
  that also picks its own success proxy is the party motivated to pass.
- Tasks 37–41 already lean this way; use them as the template.

### WS-C — §5 meta-validation as a standing fixture

Validate the improved gate against a **known miss** — but pick a **pixel-level** bug
(**task 40** blank-line, or **task 41** contiguous highlight), **not task 39** (that's a
one-line assertion per §2.4 and proves nothing about the new capability). Reconstruct the
broken state, run one iteration through the improved loop, confirm the visual judge
**FAILs** with a clear reason, then confirm the fix **PASSes**. Keep this as a **standing
regression fixture** of known-missed bugs, re-run whenever the loop changes — so the blind
spot can't silently reopen. This *is* WS-A's definition of done.

### WS-D — WS1 downgraded to caveat + policy

- Fix the false "cannot see code you edited this iteration" caveat in PROMPT.md step 7 and
  the qa-tester def to the §2.1 truth.
- One-line policy: the main agent leaves app launches to the qa step (so qa's launch is
  always the first), and if stale is ever suspected, the fix is a server restart, not
  another relaunch. Reserve subprocess-launch-inside-MCP only if the main agent turns out
  to genuinely need to drive mid-iteration.

### WS-E (secondary, opportunistic) — reduce duplication/bandaids

Reuse inventory injected at PROMPT.md step 1 (canonical helpers not to re-implement — the
task-36 shared row renderer, `reconstruction._fold`, `core.streaming`); periodic in-loop
mini-review after UI tasks; an anti-bandaid "generalize, don't special-case" acceptance
flag (per the task-27–31 per-key whack-a-mole).

---

## 4. Where the pieces live (grounded)

| File | Role |
|---|---|
| `scripts/ralph/loop.sh` | The loop; each iteration a fresh `claude -p` (MCP respawns per iteration). |
| `scripts/ralph/PROMPT.md` | Per-iteration instructions. **Step 3** = test-strategy judgment (the model for WS-B). **Step 7** = qa step + the two limits to rewrite. |
| `scripts/check.sh` | The mandatory gate (ruff + mypy + pytest); stays green, always. |
| `tools/agent/mcp_server.py` | `ctx-agent` MCP server; registers `ctx_snapshot`. Imports no `ctx.*` at startup (why §2.1 holds). |
| `tools/agent/harness.py` | `HarnessApp` — no-arg ChatApp + `TestProvider` + temp workspace seeded with `sample.txt`. The thing WS-A drives via Pilot. |
| `tools/agent/snapshot.py` | `render(describe_state())` — the semantic text snapshot; already carries the `colors:` line (§2.4). |
| `.claude/agents/qa-tester*` | qa-tester subagent (Sonnet) + its `mcp__ctx-agent__*` tools incl. `textual_screenshot` and `Read`. |
| `.claude/skills/ralph-tasks/`, `PRD.template.md` | Where the "spec the visible outcome" habit (WS-B) is encoded. |
| `.venv/.../textual_mcp/server.py:214` | `textual_screenshot`: `format="svg"` → `export_screenshot()`; default `format="text"` is colorless. |
| `scripts/ralph/PRD.md` — Phase 3e (33–45) | Bug catalog + validation targets. 37–41 are the visual ones. |

---

## 5. Constraints & gotchas

- **Architecture (`AGENTS.md`):** `ctx/core/*` and `ctx/models/*` stay framework-free
  (zero Textual). All this work lives in `tools/agent/*`, `scripts/ralph/*`, `.claude/*`.
- **Never run the loop on `main`/`develop`** (`loop.sh` refuses). We're on `feat/compression`.
- **Subagent deadlock rule:** spawn **at most one** qa-tester at a time and let it return;
  the MCP-driven TUI can wedge. Never background a command/subagent and end the turn
  expecting a wake-up — a headless iteration gets no follow-up turn.
- **`TestProvider` streams with zero delay** — great for determinism, but true mid-stream
  races (the task-33 soft-lock) can't be reproduced headlessly. A slow/blocking test
  provider is a separate worthwhile task; don't design the visual judge around timing.
- **cairosvg, not inkscape.** Snap inkscape can't read `/tmp`; write PNGs somewhere the
  `Read` tool can reach, or use the scratchpad. cairosvg via `uv run --with` needs no
  permanent dep.
- **Don't edit `docs/Sprint Roadmap.md`, `uv.lock` by hand, `main`/`develop`, or the
  `mutants/` tree.** ADR-worthy decisions → `docs/decisions/`.

---

## 6. Suggested first move

1. Read: PROMPT.md (steps 3 + 7), `tools/agent/harness.py`, and Phase 3e tasks 37–41.
2. Build **WS-A** by hand (attended): the Pilot→SVG→cairosvg→PNG helper + a `Read`-the-PNG
   judge, driving to the `committed-K` state (§2.3). Prove both directions on the K-bar
   color (force violet → FAIL; green → PASS).
3. Then **WS-C**: validate against task 40 or 41 (a pixel-level bug) and freeze it as the
   standing fixture.
4. Then **WS-B** (PROMPT.md + skill wording) and **WS-D** (caveat/policy). **WS-E** is
   opportunistic.

Build WS-A/WS-C attended (they change the loop). Once the visual gate is proven, the loop
itself can drive WS-B/WS-D and Phase 3e.

**Execution model (decided, don't re-litigate):** do the whole loop-repair
(WS-A→WS-C→WS-B→WS-D) in **one attended main conversation**, *not* a `PRD-loop-v2` handed
to Ralph. You can't loop-verify the verifier before it exists — a Ralph iteration's
back-pressure is `check.sh` + qa-tester, so a loop building WS-A would validate the new
gate with the old *blind* one (circular); and WS-C ("confirm the judge FAILs a known
bug") is attended by definition. WS-A is also an exploratory spike, not a clean
independent single-session task, and WS-B/WS-D are small coupled edits that depend on
WS-A's shape. Reserve the Ralph loop for **Phase 3e (33–45)** — an already-decomposed
task list, and the real dogfood: the *now-sighted* gate catching visual regressions while
fixing 37–41. Fold WS-E in opportunistically there.
