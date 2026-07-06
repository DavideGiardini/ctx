# PRD — Sprint 3: Compression & spatial navigation (3a + 3b)

## Goal
Build ctx's primary differentiator (Product Concept §4): select a contiguous range of
nodes, AI-draft (or hand-write) a compression node `K` that the model sees *instead of*
the folded originals, navigate compression depth (deep-dive), and — in the 3b half —
compress **any** range (including the middle) made honest by per-turn context
reconstruction and a git-diff-style context view on drifted AI nodes. The design is
fully settled: **ADR-0016 Amendments #1–#3** (`docs/decisions/0016-…md`) and the
roadmap's S3 decisions Q1–Q14 + H1–H6 (`docs/Sprint Roadmap.md`). `CONTEXT.md:20-70`
holds the domain glossary (K, folded children, event nodes, deep-dive, drift). Phase
3a (tasks 1–13) ships safe tip-suffix compression; phase 3b (tasks 14–23) adds
`created_seq`, event-enumeration resolution, reconstruction, the diff view, and
finally removes the tip guard. **Middle compression must never be live before the
diff view exists** — the task order enforces this; do not reorder.

## Constraints / notes
- **Read ADR-0016 (all three amendments) in any iteration touching compression
  semantics.** It is the rationale the one-line tasks can't carry. Roadmap S3 bullets
  Q1–Q14/H1–H6 are the decision record; do not re-litigate settled points.
- **Architecture** (`AGENTS.md` "Designing new modules"): `ctx/core/*` stays
  framework-free (zero `textual`); UI is a thin adapter; deep modules; no new Protocol
  seams (single implementations). `mutants/` is a mutmut mirror — never edit it.
- **K and E are OFF-LINE nodes**: `prev_id=None`, added straight to
  `ConversationCore._graph`, **never** via `_append_to_line`
  (`ctx/core/conversation.py:161`). The `prev_id` chain is never mutated.
- **Canonical meta keys** (H1/H5 — do not improvise):
  `K.meta = {"prompt": <str, "" for manual>, "range": [<ordered folded child ids>]}`;
  `E.meta = {"target": <K.id>, "anchor": <active_leaf_id at expand time>}`;
  assistant nodes gain `meta["ctx_hash"]` in 3b (task 17).
- **Default compression prompt (exact text, ADR-0016 A#1):** "Preserve the facts,
  decisions, entities, and open threads needed for the conversation to continue
  coherently." Core constant in 3a; becomes `compression.default_prompt` config in
  task 18.
- **H2 invariant:** `commit_compression` / `expand_compression` / `draft_compression`
  must raise while a turn is streaming (`ConversationCore.streaming`, task 3); the UI
  additionally refuses the actions while `_stream_worker` runs (`ctx/ui/app.py:75`).
- **Keys (settled, revised 2026-07-03):** `v` anchor+extend selection (Edit mode) ·
  `c` opens the draft editor · `Ctrl+D` draft/re-draft · `Ctrl+S` commit · `Esc`
  cancel · `x` expands the selected K (Edit mode, task 13b) · `g d` deep-dive / diff
  view · `Ctrl+o` pop one level · `i` exits any full-screen inspection to Insert at
  the live tip. **Selection-dependent actions are Edit-mode keys ONLY, never slash
  commands** (user decision 2026-07-03): the InputBar needs Insert mode and entering
  Insert clears the selection, so a command can never act on a selected node. The
  3a-shipped `/compress`/`/expand` commands are removed by task 13b — this supersedes
  the earlier ":compress/:expand map to slash commands" note (record in ADR-0016).
  Update footer hints (`ctx/ui/widgets/app_footer.py:9` `_HINTS`) whenever keys are
  added.
- **Code-blind test flow** (PROMPT.md step 4) for new/changed core behavior:
  signatures + docstrings + stubs → `test-spec-author` with interface + prose intent →
  red → implement to green. Authored tests are fixed. Reuse `tests/conftest.py`
  fixtures (`make_node`, `stub_loader`, `test_provider`, `varying_provider`, `repo`,
  `workspace`). Async-cancel tests: never `athrow` into the generator — use a blocking
  provider and cancel the consuming task (see `tests/specs/conversation.md` precedent).
- **UI tasks: a deterministic Pilot test is the mandatory acceptance floor**
  (`App.run_test()` asserting `describe_state()` fields — template:
  `tests/test_app_gauge.py`). The qa-tester harness runs in-process with `ctx.*`
  cached (cannot see this iteration's edits) and cannot perceive layout/spacing —
  it confirms committed behavior and asserts on snapshot state only.
- **`StoragePort` rule:** if `save`/`load` signatures shift, the `SaveCountingStorage`
  double (`tests/test_conversation.py:70`) moves in lockstep. Task 14 only adds a
  column riding `Node` — signatures should not change.
- **Do not edit** `docs/Sprint Roadmap.md`; ADR edits only where a task says so.
  Never touch `main`/`develop`, never hand-edit `uv.lock`, never commit `.ctx/`/`.env`.

## Tasks
Top-to-bottom by priority; the loop always takes the topmost unchecked task.
Dependencies noted; every prerequisite sits above its dependent.

### Completed — phases 3a–3d (tasks 1–32, full specs in `PRD-done.md`)

Compression, context-transparency, and post-sprint hardening are shipped. The
**full original task text + acceptance criteria** are archived in
[`PRD-done.md`](PRD-done.md); the per-task narrative is in `PROGRESS.md` and the
diffs in git history. One line each below so open tasks can still resolve their
`deps:` / "task-N" references — look up the number in `PRD-done.md` for detail.

**Phase 3a — safe tip compression + spatial navigation**
- [x] 1 — Core: compression node type + `build_context` rendering
- [x] 2 — Core: `current_view()` resolves compression folds
- [x] 3 — Core: `commit_compression` + the `streaming` flag (H2)
- [x] 4 — Core: `expand_compression`
- [x] 5 — Core: `draft_compression`
- [x] 6 — UI: range selection (`v` anchor + extend)
- [x] 7 — UI: draft editor opens/edits/cancels
- [x] 8 — UI: Commit (`Ctrl+S`) + K rendering in the message list
- [x] 9 — UI: draft streaming (`Ctrl+D`)
- [x] 10 — UI: committed-K inspector 3-split
- [x] 11 — UI: `/expand`
- [x] 12 — UI: deep-dive (`g d` / `Ctrl+o`)
- [x] 13 — Phase 3a end-to-end verification (qa-tester)
- [x] 13a — UI: commit failures breadcrumb, not crash + soft-lock
- [x] 13b — UI: expand becomes an Edit-mode key; remove selection-dependent slash cmds
- [x] 13c — Test: a committed K's summary reaches the provider on the next turn
- [x] 13d — UI: commit/close must not orphan a running draft worker
- [x] 13e — UI: range extension clamps at the list edges, not wrap
- [x] 13f — UI: `/new` and `/resume` reset compression UI state
- [x] 13g — Core: resume keeps the title; rewind rejects off-line nodes
- [x] 13h — UI: deep-dive/editor interaction hardening (Esc order, seam bypass)
- [x] 13i — Polish: editor footer hints, blank-prompt fallback, `range_selection`

**Phase 3b — middle compression + context transparency**
- [x] 14 — Core: `created_seq` column + migration
- [x] 15 — Core: event-enumeration resolution (H3)
- [x] 16 — Core: `context_at_generation` + drift predicate
- [x] 17 — Core: `ctx_hash` per-turn tripwire (H4)
- [x] 18 — Config: `compression.default_prompt` + `ui.show_context_drift` (Q13)
- [x] 19 — UI: drift indicator (`Δ`)
- [x] 20 — UI: diff view overview (full-screen)
- [x] 21 — UI: diff drill-down
- [x] 22 — Enable middle compression (delete the 3a tip guard)
- [x] 23 — Sprint 3 end-to-end verification (qa-tester)

**Phase 3c — follow-ups from the task-23 end-to-end pass**
- [x] 24 — Gate `g d` diff-view on `ui.show_context_drift`
- [x] 25 — Fix drift `Δ` marker vs. weight-% layout
- [x] 26 — QA tooling: surface Sprint 3 state in `snapshot.py::render()`

**Phase 3d — hardening from the post-sprint review**
- [x] 27 — UI: diff view inherits the deep-dive read-only gates
- [x] 28 — Core: close the H2 submit→first-tick window; add UI commit stream guard
- [x] 29 — Test: extend the ctx_hash oracle to middle compression
- [x] 30 — UI: diff/deep-dive exclusivity + cursor restore after a nested diff
- [x] 31 — UI: gate the remaining direct `add_node` appenders
- [x] 32 — Perf: cache the per-refresh drift computation

### Phase 3e — UI polish + review-verified fixes (2026-07-04)

> Filed from a second review pass (8-angle code review of `develop...feat/compression`
> + a `qa-tester` behavioral pass driving the real TUI) plus first-hand user testing of
> the compression UI. Every item was verified either by reading (correctness bugs) or by
> screenshot/snapshot in the running app (all UI items CONFIRMED-BROKEN). Two design
> decisions are settled and must not be re-litigated: **the diff view is a full-screen,
> two-pane replacement** (left = context as-of generation, right = now), both panes
> rendering **the same compact two-line node rows as the main conversation** — never
> plain-text dumps (user, 2026-07-04); and **`g d` stays overloaded** (deep-dive a K /
> diff a drifted assistant turn) — no change to its dispatch. Tasks 33–35 are
> correctness (land before merge); 36 is the keystone the diff/inspector rework builds
> on; keep the order. NOT re-filed here (already recorded above / deferred): the
> `_drift_signature` active-line collision (latent until S4 branching) and the
> `expand_compression` unguarded `k.meta["range"]` KeyError (§"NOT filed" item (d)).

- [x] 33 — Core: fix the stuck `_streaming` flag on a pre-stream failure
- [x] 34 — Core: `build_context` never emits two adjacent same-role messages

- [ ] **35. UI: reset `_last_drafted_prompt` on draft cancel/failure** _(deps: none;
      review finding, MEDIUM — code-confirmed)_ — `action_draft_compression` sets
      `self._last_drafted_prompt = prompt` (`ctx/ui/app.py:704`) *before* the worker
      runs, and nothing clears it on the Esc-cancel path (`:207-210`) or the error
      path (`:720-722`). A user who drafts, cancels/errors, then hand-writes a
      summary and commits (`Ctrl+S`) passes the **stale** prompt into
      `commit_compression` (`:756-757`) → `K.meta["prompt"]` is non-empty → the
      inspector renders it as AI-drafted (`:280-281`), corrupting the manual-vs-drafted
      distinction. Fix: clear `_last_drafted_prompt` to `""` on draft cancel and on
      draft failure (and defensively on editor close), so a manual commit stamps
      `""`. _Acceptance:_ Pilot test — draft, cancel the worker, commit a
      hand-written summary; `describe_state()`/inspector shows the K as manual
      (empty prompt). `scripts/check.sh` green.

- [ ] **36. UI: extract a shared compact message-row renderer** _(deps: none;
      keystone for 37–38; altitude/reuse finding)_ — the main conversation renders
      nodes as two-line rows with a role-colored left bar + weight slot via
      `MessageWidget` (`ctx/ui/widgets/message_list.py:55`), but the diff view
      (`ctx/ui/widgets/diff_view.py:28-32` `_column`) and the detail inspector's
      splits (`ctx/ui/widgets/detail_inspector.py`, `Static.update(view.content)`)
      each roll their own plain-text dump. Extract the compact-row rendering into a
      single reusable widget (or factory) that takes a `Node` and produces the
      standard row (bar color from the palette, truncation, weight/drift slots),
      and refactor `MessageList` to build rows through it — **no behavior change to
      the main conversation**. This is the shared surface tasks 37 and 38 consume.
      Keep it a thin UI widget; no core changes. _Acceptance:_ Pilot test — the main
      message list renders identically before/after (snapshot of
      `describe_state()`/row structure unchanged); the new renderer is unit/Pilot
      exercised on a sample node of each role (user/assistant/context/compression/
      system) producing the expected bar color + two-line layout. `scripts/check.sh`
      green.

- [ ] **37. UI: rebuild the diff view as a full-screen two-pane node diff** _(deps:
      20, 21, 36; user-verified BROKEN)_ — today `DiffView`
      (`ctx/ui/widgets/diff_view.py`) is a single `VerticalScroll` that replaces
      only the right message-list pane and lays out an *internal* was/now split of
      **full untruncated node text**; the left detail pane is unused. Rebuild it as
      a full-screen replacement with **two side-by-side panes**: left = the turn's
      context as-of generation (`reconstruction.context_at_generation`), right = the
      same ancestor prefix now (`reconstruction.now_prefix`) — both rendered as the
      standard compact two-line rows via the task-36 shared renderer (not plain
      text). Align by node id (`reconstruction.diff_regions`), visually highlight the
      changed/added/removed rows, and keep the existing region cursor: `up`/`down`
      walk changed regions, `Ctrl+o` closes, the "reconstruction may be inexact"
      banner is preserved. `g d` dispatch and the deep-dive path are unchanged.
      _Acceptance:_ **visual (primary)** — render `drift-diff` via
      `tools/agent/visual.py` (`uv run --with cairosvg==2.9.0 python -m
      tools.agent.visual state drift-diff /tmp/x.png`) and `Read` the PNG: confirm
      **two side-by-side panes**, each showing **compact two-line rows with colored
      left bars** (not a raw-transcript text dump), with the changed region visibly
      highlighted. **Behavioral floor** — qa-tester confirms the `g d`→two-pane→
      `up`/`down`→`Ctrl+o` flow (region cursor moves; `Ctrl+o` restores the live
      list + pre-diff cursor); a Pilot test asserts the `describe_state()` diff
      fields (`nav`, region count/cursor). `scripts/check.sh` green.

- [ ] **38. UI: inspector splits render compact rows + visible dividers** _(deps:
      36; user-verified BROKEN)_ — the detail inspector's central "Originals"/context
      split renders folded messages as plain markdown-bold text
      (`ctx/ui/widgets/detail_inspector.py`, `Static.update`), and
      `DetailInspector.DEFAULT_CSS` has no rule/border between the
      `#detail-prompt`/`#detail-content`/`#detail-output` sections. Render the
      message-bearing split(s) as the task-36 compact rows (colored bar, two lines),
      and add a visible divider between the three splits. _Acceptance:_ **visual
      (primary)** — render `k-inspector` via `tools/agent/visual.py` and `Read` the
      PNG: the inspector's "Originals" split shows **compact rows with colored left
      bars** (not plain markdown-bold text) and a **visible divider** sits between
      the three splits. **Floor** — a Pilot test asserts the split structure and
      snapshot `splits=prompt,content,output`. `scripts/check.sh` green.

- [ ] **39. UI: compression node color = context color** _(deps: none; user-verified
      BROKEN)_ — the palette (`ctx/core/config.py:31-32`) sets `context=#22c55e`
      (green) but `compression=#a855f7` (violet); the K's left bar renders violet.
      Change the default `compression` color to match `context` (green), and — since
      they now share a bar color — give the compression row a distinct **glyph/label**
      so a summary is still visually distinguishable from an imported file. Update any
      test asserting the old color. _Acceptance:_ **floor (deterministic, primary —
      color is queryable, §2.4)** — a unit test asserts `ctx_snapshot`'s `colors:`
      line shows `compression` == the `context` green, and the K row carries a
      distinguishing glyph/marker. **Visual confirm** — render `committed-K` via
      `tools/agent/visual.py`, `Read` the PNG, verify the K's left bar is green (not
      violet) with its marker; calibrate the eye both directions with `--variant
      k-violet`/`k-green`. `scripts/check.sh` green.

- [ ] **40. UI: blank-line separation before a compression node** _(deps: none;
      user-verified BROKEN)_ — a K mounted right after an assistant turn has ~zero
      top gap (the assistant row ends and the K begins with no blank margin row),
      so they read as produced together; other turn starts get a `.pass-start
      { margin-top: 1; }` gap (`ctx/ui/widgets/message_list.css`). Give a compression
      row the same top-margin/"pass-start" treatment so it is separated from the
      preceding assistant turn (K sits on the user side, its own pass). _Acceptance:_
      **visual (primary — pixel-level, no queryable proxy)** — render
      `k-after-assistant` via `tools/agent/visual.py` and `Read` the PNG: confirm a
      **blank margin row separates the K from the assistant row directly above it**
      (matching other turn-to-turn gaps); verify both directions against the task-40
      pair in `scripts/ralph/VISUAL-FIXTURE.md`. **Floor** — a Pilot test asserts the
      K widget carries the `pass-start` class. `scripts/check.sh` green.

- [ ] **41. UI: range selection uses hover styling, bridged across gaps** _(deps:
      none; user-verified BROKEN)_ — `MessageWidget.range-selected` is a solid dark
      blue (`background: $primary-darken-2`, `ctx/ui/widgets/message_list.css`),
      unlike the grey hover/cursor style (`.selected { background:
      $surface-lighten-1 }`), and the blank **margin** rows between two selected
      messages keep the default background (the highlight doesn't bridge the gap
      because `margin` paints outside the widget box). Restyle range selection to
      match hover: a bold role-colored left bar + light-grey background, and make the
      highlight **contiguous** across the inter-message gaps (e.g. convert the
      selected run's separators to padding, or paint the gap rows), so a multi-node
      selection reads as one continuous block. _Acceptance:_ **visual (primary —
      pixel-level)** — render `range-selection` via `tools/agent/visual.py` and
      `Read` the PNG: a multi-node `v`-selection shows **grey (hover-style)
      backgrounds with bold role-colored left bars on every selected row AND
      contiguous across the gaps between them** — not solid blue with default-color
      gaps. **Floor** — a Pilot test asserts the `range-selected` styling/class on
      the selected run. `scripts/check.sh` green.

- [ ] **42. UI: transient hints leave the conversation graph** _(deps: none;
      review + qa finding)_ — `_breadcrumb` (`ctx/ui/app.py:800-806`) calls
      `core.add_system_message`, which appends a **persistent** graph node, so
      transient UI hints ("Write a summary before committing (Ctrl+S).", "Not a
      compression node") become permanent nodes that accumulate forever (confirmed
      still present after a `/new`→`/resume` cycle). Introduce a transient,
      non-persistent surface for hints (Textual `self.notify()` toast or a footer
      status line) and route UI hints through it; **reserve** persistent
      `add_system_message` nodes for durable breadcrumbs only (e.g. `/model`
      changes). _Acceptance:_ qa-tester — triggering a hint (empty-summary commit)
      shows a transient message and adds **no** new node to `ctx_snapshot`; a
      durable `/model` breadcrumb still appears as a node. `scripts/check.sh` green.

- [ ] **43. UI: no weight on non-model nodes; silent invalid keys; contextual footer**
      _(deps: 42; user-verified BROKEN)_ — (a) system/breadcrumb nodes show a `--%`
      weight slot (`MessageWidget`, `ctx/ui/widgets/message_list.py:98-104`) though
      they never go to the model — suppress the weight slot for nodes where
      `goes_to_model()` is False and/or render durable breadcrumbs dimmed. (b) `x`
      on a non-compression node emits a "Not a compression node" breadcrumb
      (`ctx/ui/app.py:627`) — make it a **silent no-op** instead (and fold in the
      `action_expand` review finding: wrap its `core.expand_compression` call in
      `try/except ValueError` like `action_commit_compression` so a core guard never
      propagates uncaught). (c) the footer (`ctx/ui/widgets/app_footer.py:9`
      `_HINTS`) should surface only the actions valid for the current selection
      (e.g. `x` only on a K, `g d`/"view drift" only on a drifted turn). `c` opening
      a range-of-one is by-design (ADR-0016 Q5) — leave it. _Acceptance:_ qa-tester
      — pressing `x` on a plain node adds no node and shows no warning; a system
      breadcrumb shows no `--%`; the footer hint changes with the selected node type.
      `scripts/check.sh` green.

- [ ] **44. UI: incremental message-list reconcile (kill the refresh flash)** _(deps:
      36)_ — `_rebuild_message_list` (`ctx/ui/app.py:777`) tears down every child and
      re-mounts every visible node one awaited call at a time on **every** structural
      change (commit `:774`, expand `:631`, deep-dive nav `:501`), causing the
      right pane to blank and repopulate top-to-bottom. Replace the teardown+remount
      with a reconcile against `_visible_nodes()` that removes only the rows that left
      the view and inserts only those that entered (on a commit: drop the folded rows,
      insert one K), preserving unaffected widgets. This is the deep form of the
      task-27/31 "gate every appender" whack-a-mole (the list becomes a projection of
      `_visible_nodes()`). _Acceptance:_ Pilot test — after a commit, the surviving
      row widgets are the same instances as before (not all recreated) and the K
      appears in place; qa-tester confirms no full blank/repopulate on commit/expand.
      `scripts/check.sh` green.

- [ ] **45. Verify the polished compression UI end-to-end (qa-tester)** _(deps:
      33–44)_ — drive the real TUI and confirm, in one pass, the full corrected flow:
      compress a middle range (K is context-green with a distinct glyph, separated by
      a blank line from the preceding assistant turn, no full-refresh flash); a
      multi-node selection reads as one grey contiguous block; hints appear transiently
      and add no nodes; `x`/invalid keys are silent no-ops and the footer tracks the
      selection; deep-dive a K (compact rows + dividers in the inspector split); open
      the diff view on a drifted turn (two panes, compact rows, changed region marked,
      `up`/`down`/`Ctrl+o` work); and no soft-lock after a failed `/include`.
      `textual_check_errors` clean throughout. _Acceptance:_ a written qa report with
      every item WORKS, **plus a visual pass**: render `committed-K`,
      `k-after-assistant`, `k-inspector`, `range-selection`, and `drift-diff` via
      `tools/agent/visual.py`, `Read` each PNG, and confirm the corrected appearance;
      re-run `scripts/ralph/VISUAL-FIXTURE.md` and confirm both directions still
      discriminate. Any regression filed as a follow-up task.

## Out of scope
- **Nested compression** (compressing a range containing a K) — Q7: the flat guard
  stays; the breadcrumb stack is built general but depth stays 1. Post-3b follow-on.
- **Inline folding `zo`/`zc`/`zR`/`zM`** — dropped (Q8); the Center split + deep-dive
  cover it.
- **Branching UI / S4** — `rewind` stays core-only; `E.meta.anchor` is written but
  unused until S4; abandoned-tail visibility is an S4 question.
- **Import snapshots / source-file drift in the diff** (S5) — pre-S5 the diff renders
  imports live on both sides; the `ctx_hash` warning is the only drift signal. Do not
  build snapshot storage.
- **A colon-command (`:`) input mode** — the roadmap's `:compress`/`:expand` map to
  Edit-mode keys (`c` / `x`), NOT slash commands (revised 2026-07-03, task 13b).
- **In-app config editing** — `compression.default_prompt` is hand-edited JSON.
- **`Ctrl+C` copies instead of cancelling while a TextArea/Input has focus** (the
  footer's "^C Cancel" is false there — Textual's TextArea binds ctrl+c to copy).
  Pre-existing for the InputBar, more visible with the editor; known + deferred to a
  future keybinding pass (review 2026-07-03).
- **RAG/semantic anything**; `created_seq` before task 14; edits to
  `docs/Sprint Roadmap.md`; the `mutants/` tree; `main`/`develop`; `uv.lock` by hand;
  committing `.ctx/`/`.env`.
