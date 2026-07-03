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

### Phase 3a — safe tip compression + spatial navigation

- [x] **1. Core: compression node type + `build_context` rendering** — in
      `ctx/models/nodes.py`: a `Node.compression(summary, conversation_id, range_ids,
      prompt="")` factory (`role="compression"`, `node_type="compression"`,
      `content=summary`, meta per the canonical keys); extend `goes_to_model()`
      (`nodes.py:46-53`) so `node_type == "compression"` returns True (H6). In
      `ctx/core/context.py`: render a compression node as
      `<conversation_summary>\n{content}\n</conversation_summary>` with
      `node_role="user"` so it coalesces with adjacent user content exactly like
      `<context_import>` (Q2; no framing/preamble — Q2b). _Acceptance:_ code-blind
      tests (extend `tests/specs/nodes.md`/`context.md` + test files): factory fields
      and meta keys; `goes_to_model()` True for K, unchanged for others; rendering
      wraps + coalesces; a system node between user content still splits coalescing.
      `scripts/check.sh` green.

- [x] **2. Core: `current_view()` resolves compression folds** _(deps: 1)_ — in
      `ctx/core/conversation.py:119-138`, after the `prev_id` walk, replace each
      **maximal contiguous run** of view nodes sharing the same non-None
      `compressed_into = K` with the `K` node from `_graph`, in place (Q1 —
      pointer-based 3a resolution; task 15 later swaps the mechanism behind the same
      signature). Children leave the view; K appears despite `prev_id=None`. The
      active leaf may itself be folded: the view then ends with K, but
      `_append_to_line` still chains new nodes from `_active_leaf_id` (unchanged).
      A `compressed_into` pointing at a missing node → treat as unfolded (defensive,
      like the existing walk). _Acceptance:_ code-blind tests: tip run folds to K;
      middle run folds in place; two independent Ks; no-compression view identical to
      today; append-after-folded-tip chains from the real leaf and the view shows
      `[..., K, new]`. `scripts/check.sh` green.

- [x] **3. Core: `commit_compression` + the `streaming` flag (H2)** _(deps: 1, 2)_ —
      `ConversationCore.commit_compression(start_id, end_id, summary, prompt="") ->
      Node`: validate via a private `_validate_compress_range(start_id, end_id)`
      shared with task 5 — the ids delimit a contiguous slice of `current_view()`;
      **no node in the slice is `node_type=="compression"`** (Q7 flat guard); **the
      slice's last node is the active leaf** (the 3a tip guard — removed in task 22,
      keep it a distinct, deletable check); **raise while `self.streaming`**. Add the
      `streaming` read-only property: a private flag set True at `stream()` entry
      (`conversation.py:311`) and cleared in a `finally`. Mutation (pure, no AI —
      Q3): create K via `Node.compression` (meta range = the slice ids in order, H1),
      add to `_graph` directly, set `compressed_into=K.id` on each slice node,
      `persist()`, return K. `ValueError` on any validation failure. _Acceptance:_
      code-blind tests: view shows K after commit; save→reload resolves identically
      (K + pointers round-trip — storage already persists them); mid-range (non-tip)
      rejected; K-in-range rejected; commit during a blocked stream raises (blocking
      provider + task-cancel pattern); `persist` passes the full graph (children
      survive). `scripts/check.sh` green.

- [x] **4. Core: `expand_compression`** _(deps: 3)_ —
      `ConversationCore.expand_compression(k_id) -> None`: validate K exists, is
      `node_type=="compression"`, is **active** (some node has `compressed_into ==
      k_id`), and not `self.streaming`. Mutation (H1 + H5 — 3a writes the 3b-shaped
      record): append an **E event node** to `_graph`: `node_type="expand"`,
      `role="expand"` (must stay `goes_to_model() == False` and never render),
      `prev_id=None`, `conversation_id` set (it must persist), meta per canonical
      keys (`anchor` = current `_active_leaf_id`); clear `compressed_into` on K's
      children (read them from `K.meta["range"]`); `persist()`. K itself **stays**
      in the graph (invisible orphan — never row-deleted, ADR-0016 A#3 §1).
      _Acceptance:_ code-blind tests: view restores the children in place; E
      round-trips with target+anchor; K survives reload; re-compressing an
      overlapping range afterwards creates a valid new K′; expanding an already
      expanded/unknown K raises; streaming guard raises. `scripts/check.sh` green.

- [x] **5. Core: `draft_compression`** _(deps: 1, 3)_ —
      `ConversationCore.draft_compression(start_id, end_id, prompt=None) ->
      AsyncIterator[str]`: same `_validate_compress_range` (incl. streaming guard);
      render **only the range** via `build_context(range_nodes,
      self._workspace.read_file)` — the Q10c invariant: each node contributes its
      model-facing form (raw import → full file; summarized content → its summary);
      append one final user message carrying the instruction (`prompt` or the
      DEFAULT_COMPRESSION_PROMPT core constant — exact framing is implementer's
      choice, record it in PROGRESS.md); stream via `self._provider.stream(messages,
      self.model, <no-op on_usage>)` so `last_usage`/`calibration`/
      `usage_generation` are untouched (Q10b — this is a meta-operation, never a
      gauge anchor). Cancellation-safe: commits nothing, mutates no state (Q3).
      _Acceptance:_ code-blind tests: yields the provider's tokens; after a full
      draft, `usage_generation`/`calibration`/`last_usage` unchanged; custom `prompt`
      reaches the provider's messages (recording provider); range rendered via
      `build_context` (an import node in range contributes file content, not its
      "Included:" label); invalid range/streaming raises before any provider call.
      `scripts/check.sh` green.

- [x] **6. UI: range selection (`v` anchor + extend)** _(deps: none hard)_ — Edit-mode
      vim-style selection (Q5): `v` (new `ChatApp.BINDINGS` entry, `app.py:45-57`)
      anchors at the selected node; existing `action_up`/`action_down`
      (`app.py:247,259`) extend the **contiguous** selection between anchor and
      cursor while the anchor is set; `Esc` clears the anchor first (second Esc =
      existing behavior, `app.py:149`); entering Insert clears it. New
      `MessageWidget.set_range_selected(bool)` toggling a `.range-selected` CSS class
      (pattern: `set_selected`, `message_list.py:70-74`; style it in the widget CSS).
      Footer: `_HINTS["edit"]` gains the hint. `describe_state()` gains
      `"range_selection": [<node ids in view order>]` (empty when inactive) — the
      Pilot floor. _Acceptance:_ Pilot test: enter Edit, press `v`,`down`,`down` →
      `range_selection` has 3 contiguous ids and the widgets carry
      `.range-selected`; `Esc` empties it and stays in Edit; single node (`v` alone)
      = range of one. `scripts/check.sh` green.

- [x] **7. UI: draft editor opens/edits/cancels** _(deps: 5, 6)_ — new
      `CompressionEditor` (e.g. `ctx/ui/widgets/compression_editor.py`): a left-pane
      **2-split** (Q4) — Top: editable `TextArea` prefilled with
      DEFAULT_COMPRESSION_PROMPT; Bottom: editable `TextArea`, empty; **no Center**
      (the originals stay highlighted on the right). Shown in place of the
      `DetailInspector` (the inspector's hidden-subtree compose pattern,
      `detail_inspector.py:93-107`, is prior art; sibling widget or inspector mode —
      implementer's choice). Triggers: `c` in Edit mode acts on the active range
      selection (no anchor → range-of-one on the selected node, Q5); `/compress`
      (add to `InputBar.COMMANDS`, `input_bar.py:17`, + a branch in
      `on_input_bar_submitted`, `app.py:542`) requires an active selection, else a
      system breadcrumb "Select a range first: v in Edit mode". **No auto-stream**
      (Q4): opening shows prompt + empty output only. `Esc` cancels for free —
      editor closes, inspector restored, selection preserved. No commit/draft keys
      yet (tasks 8–9). `describe_state()` gains `"compression_editor": {"open":
      bool, "prompt": str, "output": str}`. _Acceptance:_ Pilot: select a range,
      press `c` → editor open with the prefilled default prompt and empty output;
      `/compress` with no selection → breadcrumb, editor closed; `Esc` restores the
      inspector and keeps the selection. `scripts/check.sh` green.

- [x] **8. UI: Commit (`Ctrl+S`) + K rendering in the message list** _(deps: 3, 7)_ —
      `Ctrl+S` in the editor with non-empty Bottom calls
      `core.commit_compression(start, end, summary=Bottom, prompt="")` (`""` because
      no draft ran yet — task 9 switches it to the last-drafted prompt), closes the
      editor, clears the selection, rebuilds the message list (children out, one K
      widget in — the `_handle_resume_command` rebuild path, `app.py:625-649`, is
      prior art), and calls `_refresh_token_ui()`. Empty Bottom → breadcrumb, no
      commit. K rendering: add a `"compression"` color to `_DEFAULTS["colors"]`
      (`ctx/core/config.py:13-38`) + the role branch in `MessageWidget.on_mount`
      (`message_list.py:55-59`), an entry in `_SIDE`/truncation keys
      (`message_list.py:21`); weight % needs nothing (S1 counts via
      `goes_to_model()`; folded children leave the view → 0 automatically, Q9).
      _Acceptance:_ Pilot end-to-end **manual** compression: select a tip range, `c`,
      type a summary in Bottom, `Ctrl+S` → `describe_state` nodes show one
      `node_type=="compression"` node replacing the range with numeric `weight_pct`,
      `K.meta["prompt"] == ""`; a second app instance on the same DB shows the same
      resolved view (round-trip). Then qa-tester (verify-feature) confirms the manual
      flow on the harness. `scripts/check.sh` green.

- [x] **9. UI: draft streaming (`Ctrl+D`)** _(deps: 5, 7, 8)_ — `Ctrl+D` in the
      editor runs a `@work` worker consuming `core.draft_compression(start, end,
      prompt=<Top text>)` into Bottom (clear first — **re-draft overwrites**, Q4);
      ignore further `Ctrl+D` while a draft streams; `Esc` during a draft cancels the
      worker and keeps the editor open (second `Esc` closes). Track the last-drafted
      prompt; `Ctrl+S` now passes it as `prompt` (still `""` if the user never
      drafted — manual mode, Q4). _Acceptance:_ Pilot with a canned provider: `c` →
      `Ctrl+D` → Bottom fills with the canned tokens; `usage_generation`/
      `calibration` unchanged (Q10b assert); edit Top, `Ctrl+D` again → Bottom
      overwritten; `Ctrl+S` → committed `K.meta["prompt"]` equals the drafted Top
      text. `scripts/check.sh` green.

- [x] **10. UI: committed-K inspector 3-split** _(deps: 8)_ — first a small core
      accessor: `ConversationCore.folded_children(k_id) -> list[Node]` (ordered per
      `K.meta["range"]`, from `_graph`; `[]` for unknown ids — children are not in
      `current_view()`, Q8). Then: cursor on a K node → the left inspector shows the
      3-split (Q4): Top = `K.meta["prompt"]` read-only, **hidden when empty** (the
      existing empty-state rule); Center = the folded originals, read-only,
      scrollable; Bottom = the summary (`K.content`). Extend `NodeView`
      (`detail_inspector.py:23-31`) + `_node_view()` (`app.py:196-205`) as needed;
      the `#detail-context` 3-split (`detail_inspector.py:47-51,93-107`) is the
      pattern. _Acceptance:_ Pilot: select a drafted K → inspector state shows
      prompt/originals/summary populated; a manual K (empty prompt) hides Top;
      `1`/`2`/`3` maximize still works on the splits. Then qa-tester confirms
      browsing. `scripts/check.sh` green.

- [x] **11. UI: `/expand`** _(deps: 4, 8)_ — add `/expand` to `InputBar.COMMANDS` +
      dispatch (`app.py:542`): acts on the currently selected node; if it's a K →
      `core.expand_compression(k.id)`, rebuild the list (children back in place,
      selection moved to the first restored child — record the choice), else a
      breadcrumb "Not a compression node". _Acceptance:_ Pilot: compress a tip range,
      `/expand` → `describe_state` shows the children back and no K in the view; the
      view survives an app restart (E + cleared pointers round-trip); a recording
      provider on the next turn receives the children verbatim and **no**
      `<conversation_summary>`. qa-tester confirms compress→expand→re-compress.
      `scripts/check.sh` green.

- [x] **12. UI: deep-dive (`g d` / `Ctrl+o`)** _(deps: 10)_ — implement a minimal
      key-chord buffer (no `on_key` exists in `app.py` yet): in Edit mode, `g` arms a
      pending chord, `d` completes it (anything else cancels). On a K node: replace
      the right-pane message list content with the folded children (**full-view
      replacement**, Q8) and show a **breadcrumb bar** ("Chat › K…") — built as a
      general **stack** (Q7: nesting-ready; 3a depth stays 1). Inside: `up`/`down`
      cursor + inspector work; **read-only** — `v`/`c`//`compress`//`expand` are
      no-ops; children weights render **"not in context"** instead of a % (Q9).
      `Ctrl+o` pops one level (top pop restores the live conversation). `i` exits
      the whole stack: live list restored, left pane back to the tip, input focused,
      appends go to the **active tip** (deep-dive never moves it). Ephemeral — no
      persistence. `describe_state()` gains `"deep_dive": {"active": bool,
      "breadcrumb": [str, ...]}`. Footer hints for the deep-dive state. _Acceptance:_
      Pilot: commit a K → `g`,`d` → `deep_dive.active` with the children as the
      visible nodes and breadcrumb of length 2; `Ctrl+o` → live view; `g`,`d` then
      `i` → Insert mode, live view, input focused. qa-tester walks the flow.
      `scripts/check.sh` green.

- [x] **13. Phase 3a end-to-end verification (qa-tester, verify-feature)** _(deps:
      1–12)_ — no code changes. Drive the harness through: (1) two turns → `v`-select
      a suffix ending at the tip → `c` → `Ctrl+D` (canned draft) → edit Bottom →
      `Ctrl+S` → K visible with numeric weight, children gone; (2) next turn → the
      recording provider's captured messages contain `<conversation_summary>` with
      K's content and none of the children's content; (3) a range NOT ending at the
      tip → `c`/`/compress` rejected with a breadcrumb (tip guard); (4) `/expand` →
      children restored, next turn's context verbatim again; (5) `g d` deep-dive →
      children + breadcrumb, `Ctrl+o` back, `i` exits to Insert; (6) restart the app
      → compressed state persists. `textual_check_errors` clean throughout.
      _Acceptance:_ qa-tester reports PASS on all checkpoints. Defects become new
      `- [ ]` tasks at the top of Phase 3b; do not patch inside this task.

### Phase 3b — middle compression + context transparency

> Tasks 13a–13b were filed by the task-13 E2E verification (2026-07-03); tasks
> 13c–13i by the post-3a review (2026-07-03 — a three-agent audit of core
> invariants, UI wiring, and test quality; findings recorded here). They sit at the
> top of Phase 3b per task 13's rule ("defects become new `- [ ]` tasks at the top
> of Phase 3b; do not patch inside task 13"). **All of 13a–13i land before task 14.**

- [x] **13a. UI: commit failures must breadcrumb, not crash + soft-lock** _(deps: 8;
      found by task 13 CP3, scope extended by the 2026-07-03 review)_ — Bug:
      `action_commit_compression` (`ctx/ui/app.py:513-539`) calls
      `self.core.commit_compression(...)` with **no** `try/except`, so any guard
      `ValueError` from `_validate_compress_range` (`ctx/core/conversation.py:358-380`)
      propagates uncaught; the editor soft-locks open and the app stops processing all
      keys/text (session unrecoverable short of restart). **Four reachable triggers**,
      not just the one CP3 hit: (1) non-tip range (3a tip guard — repro: 2 turns → Edit
      → `home`,`v`,`down` → `c` → type a summary → `Ctrl+S`); (2) commit while a real
      turn is streaming — `c` has NO streaming gate, so the editor opens fine mid-stream
      and `Ctrl+S` then hits the H2 guard; (3) a range containing an existing K (Q7 flat
      guard); (4) stale range ids after the view changed under an open editor. Fix: wrap
      the call in `try/except ValueError`, surface `str(e)` via `_breadcrumb(...)`
      (mirror the graceful `except Exception` in `_draft_compression_worker`,
      `app.py:502-510`), keep the editor open so the user can adjust (or close it —
      record the choice in PROGRESS). The catch-all stays valid after task 22 deletes
      the tip guard — the flat/streaming/stale-id guards still raise. _Acceptance:_
      Pilot tests (template `tests/test_app_*`) for at least triggers (1), (2)
      (BlockingProvider live turn, swap-provider pattern), and (3): NO exception
      escapes, a system breadcrumb is appended, the app still processes a subsequent
      `escape`/`i` (assert mode/focus change), and `describe_state` shows no new K.
      qa-tester re-runs the CP3 repro and confirms a clean breadcrumb + responsive app
      (`textual_check_errors` clean). `scripts/check.sh` green.

- [x] **13b. UI: expand becomes an Edit-mode key; REMOVE the selection-dependent slash
      commands** _(deps: 11; found by task 13 CP4 + review; user decision 2026-07-03)_ —
      Bug: a slash command can never act on a selection — the InputBar requires Insert
      mode and `_set_mode("insert")` (`ctx/ui/app.py:236-247`) unconditionally
      `_clear_selection()`s, so `_handle_expand_command` (`app.py:1059`) always sees no
      selection ("Not a compression node") and `/compress` (`app.py:1033-1041`) always
      breadcrumbs "Select a range first" — an instruction that sends the user in a
      circle (going back to Insert to type the command clears the range again). Settled
      resolution (user, 2026-07-03): **selection-dependent actions are Edit-mode keys
      only; the slash commands are removed, not repaired.** Fix: (1) add an Edit-mode
      `x` binding (or another free key — verify no conflict with existing bindings,
      record in PROGRESS) that expands the selected K via the task-11 handler logic
      (non-K selection → "Not a compression node" breadcrumb; keep the H2 mid-stream
      breadcrumb; selection lands on the first restored child); inert while deep-diving
      (read-only, Q8). (2) REMOVE `/compress` and `/expand` from `InputBar.COMMANDS`
      and their `on_input_bar_submitted` branches — `c` is the only compress path.
      (3) Update footer `_HINTS["edit"]` (≤100 cols) and append the key-map correction
      to ADR-0016 (that ADR edit is permitted here). (4) Rewrite `tests/test_app_expand.py`
      to drive the new key with REAL presses (drop the `on_input_bar_submitted("/expand")`
      back-door — it was exactly the convention that masked this defect) and remove the
      `/compress`-breadcrumb Pilot test in `tests/test_app_compression_editor.py`. Do
      NOT weaken the "Insert clears selection" invariant. _Acceptance:_ Pilot: compress
      a tip range → Edit → select the K → press the expand key → children restored, no
      K, cursor on the first restored child; a non-K selection breadcrumbs. qa-tester
      confirms compress→expand→re-compress **purely by keyboard**. `scripts/check.sh`
      green.

- [x] **13c. Test: a committed K's summary must reach the provider on the next turn**
      _(deps: 8; review finding, proven by mutant)_ — Coverage hole: NO test streams a
      turn while a fold is active and inspects the provider payload. The review built a
      scratch mutant of `ConversationCore.stream` that builds context from the raw
      un-folded `prev_id` walk (children sent, K never sent — compression saves nothing
      and the summary never reaches the model): **all 511 tests passed.** The expand
      direction has exactly the needed test (task 11's recording-provider Pilot in
      `tests/test_app_expand.py`); the compress direction — the single user-visible
      payoff of 3a — does not. Task 13's PROGRESS claim that CP2 is "covered by
      committed unit/Pilot tests" is wrong; correct the record in this task's PROGRESS
      entry. Fix: add the mirror Pilot test — two turns → compress the tip range (`c` →
      type summary → `Ctrl+S`) → next turn with a recording provider → the captured
      messages contain `<conversation_summary>` wrapping the summary text and do NOT
      contain the children's content. _Acceptance:_ verify the new test goes RED against
      a temporary local raw-walk mutation of stream's context build (do not commit the
      mutant), GREEN on real code. `scripts/check.sh` green.

- [x] **13d. UI: commit/close must not orphan a running draft worker** _(deps: 9;
      review finding, High)_ — Bug: `action_commit_compression` never checks
      `_draft_worker`, so `Ctrl+S` mid-draft commits the half-streamed summary as K;
      worse, `_close_compression_editor` (`app.py:472-476`) sets `_draft_worker = None`
      WITHOUT `.cancel()` — the orphaned worker keeps streaming into the hidden
      TextArea, overwrites a re-opened editor's Summary with the old range's draft, and
      a second `Ctrl+D` (its guard now sees None) starts a concurrent draft interleaving
      `set_output` calls. Fix: (1) `Ctrl+S` while a draft is live → breadcrumb ("Draft
      in progress — Esc cancels it first."), no commit (or cancel-then-refuse — record
      the choice); (2) `_close_compression_editor` cancels a live worker before dropping
      the reference; (3) replace the `state == WorkerState.RUNNING` liveness checks
      (`app.py:193-195, 487, 796-798, 1054-1056`) with `not worker.is_finished` — a
      just-created worker is briefly PENDING and slips every current guard. _Acceptance:_
      Pilot with a BlockingProvider draft (swap-provider pattern): `Ctrl+D` →
      `Ctrl+S` mid-stream → NO K committed, breadcrumb shown, editor still open; Esc
      cancels the draft; the close path leaves no live worker (assert via
      `app.workers`); re-opening the editor on another range shows a clean Summary.
      `scripts/check.sh` green.

- [x] **13e. UI: range extension must clamp at the list edges, not wrap** _(deps: 6;
      review finding + task-6 PROGRESS gotcha)_ — Bug: `_select_relative` (`app.py:602`)
      wraps modulo, and entering Edit puts the cursor on the LAST node — so `v`,`down`
      wraps the cursor to index 0 and `_range_ids` (`app.py:336-349`) sorts the
      endpoints: **one keystroke range-selects the entire conversation**; `c`+`Ctrl+S`
      then folds the whole conversation (the range ends at the tip so the tip guard
      passes), or hits 13a's ValueError if a K exists in history. Fix per the task-6
      note: when `_range_anchor_id` is set, clamp in `action_up`/`action_down` — do NOT
      change `_select_relative` (other callers rely on wrap). _Acceptance:_ Pilot:
      cursor on tip → `v`,`down` → range stays [tip] (range-of-one); `home` → `v`,`up`
      → range stays [first]; normal in-bounds extension unchanged (existing task-6
      tests stay green). `scripts/check.sh` green.

- [x] **13f. UI: `/new` and `/resume` must reset compression UI state** _(deps: 12,
      13d; review finding)_ — Bug: `_handle_new_command` (`app.py:971-984`) and
      `_handle_resume_command` (`app.py:986-1010`) clear only selection/range. A mouse
      click focuses the InputBar WITHOUT entering Insert or clearing state, so these
      commands can fire while a deep-dive, an open editor, or a running draft stands:
      the dead dive frame keeps feeding `_visible_nodes()` (describe_state and the next
      rebuild resurrect the OLD conversation's folded children), the footer keeps the
      dive hint, the editor stays open over dead range ids (→ 13a's ValueError site),
      and a live draft worker survives the conversation switch. Fix: both handlers
      (consider one `_reset_transient_ui()` helper any future conversation-switch path
      can reuse) must pop the whole `_deep_dive_stack` + reset the footer flag, close
      the editor without committing, cancel a live draft worker (13d's cancel helper),
      and clear `_last_drafted_prompt` + `_pending_chord`. _Acceptance:_ Pilot (invoke
      the handlers directly — the mouse path has no Pilot equivalent): dive into a K →
      `/new` → `deep_dive.active` False, visible nodes = the new conversation, footer
      back to the mode hint; editor-open variant → editor closed, no K committed;
      draft-running variant → no live worker afterwards. `scripts/check.sh` green.

- [x] **13g. Core: resume must not clobber the title; rewind must reject off-line
      nodes** _(deps: none; review findings)_ — Two `ctx/core/conversation.py` bugs.
      (1) `resume_conversation` (`conversation.py:302-305`) re-derives the title from
      the first `role=="user"` node of the VIEW: if the first user turn is folded into
      a K, the title silently becomes a later turn's text — or `""` when every user
      turn is folded — and the next `persist()` overwrites the stored title permanently.
      Fix: prefer the STORED title on resume (read it via storage; fall back to
      derivation only when the stored title is empty), and derive from the raw line,
      never the folded view. (2) `rewind(target_id)` (`conversation.py:334-336`) checks
      membership against `current_view()`, which CONTAINS off-line K nodes:
      `rewind(K.id)` sets the active leaf to a `prev_id=None` node, collapsing the view
      to `[K]`, and the next `submit()` chains `prev_id=K.id` — K lands ON the line
      permanently, violating Q1. Latent today (rewind is core-only) but S4 exposes it.
      Fix: reject any target not on the `prev_id` line (ValueError, graph unmutated);
      keep rejecting folded children for now (record: S4 revisits). _Acceptance:_ unit
      tests (small documented additions per the task-10 precedent, or code-blind —
      record the choice): compress-the-whole-tip → save → resume → stored title
      unchanged after a further persist; partly-folded resume keeps the original title;
      `rewind(K.id)` / `rewind(E.id)` raise with the graph unmutated.
      `scripts/check.sh` green.

- [x] **13h. UI: deep-dive/editor interaction hardening (Esc order, seam bypass, stale
      inspector)** _(deps: 12; review findings)_ — Three related state bugs. (1) Esc
      while diving with a pre-dive anchor is a DEAD keypress: the range-clear branch
      (`app.py:211-213`) precedes the dive pop (`app.py:216-218`), but dive widgets
      never render the range highlight (`_range_ids` reads `core.nodes` while the list
      shows frame nodes), so the first Esc visibly does nothing. Fix: clear the anchor
      on dive entry (`_enter_deep_dive`, `app.py:400-415`) — a selection can't
      meaningfully survive the view swap. (2) Async node-appenders bypass the
      `_visible_nodes()` seam: `_breadcrumb` (`app.py:551-557`), `_check_connectivity`'s
      completion (`app.py:964-969`), and `on_input_bar_submitted`'s submit path
      (`app.py:893-943`) mount widgets straight into the list — a late "✔ Connected"
      breadcrumb (repro: `/model x` → dive before the worker finishes) or a whole
      streamed turn lands INSIDE the read-only dive view, unreachable by the cursor.
      Fix: keep appending to the core but gate the widget-mount on `_deep_dive_stack`
      (exit-dive rebuilds from `_visible_nodes()` anyway — record the exact choice).
      (3) Stale inspector after commit: `_clear_selection` (`app.py:309-319`) never
      resets the DetailInspector, so after `Ctrl+S` the left pane still shows a node
      that was just folded away and Tab enters that stale pane. Route the post-commit
      clear through `_select_message(None)`. _Acceptance:_ Pilot: (a) `v` on a K →
      `g d` → a SINGLE Esc pops the dive; (b) `/model x` → dive → wait for the
      connectivity worker → dive widget count unchanged, exit dive → breadcrumb visible
      in the live view; (c) commit → inspector shows the empty/placeholder state.
      `scripts/check.sh` green.

- [x] **13i. Polish: editor footer hints, blank-prompt fallback, `range_selection`
      indices** _(deps: 7, 9; review findings)_ — Three small fixes. (1) The editor
      state has NO footer hint — while it is open the footer still shows the Edit hints
      (`v`/`c`/`i` now type into the TextArea) and the real keys (`Tab` split, `Ctrl+D`
      draft, `Ctrl+S` commit, `Esc` cancel) are unadvertised: the flagship feature is
      undiscoverable at the exact moment it's in use. Add an editor entry to `_HINTS`
      (`app_footer.py:9-15`, ≤100 cols) + a `set_editor(bool)`-style flag with
      precedence alongside deep_dive in `current_hint`. (2) `draft_compression` treats
      `""` as a real instruction (`conversation.py:488-489` — only `None` falls back),
      appending an empty user message several APIs reject; the UI passes `editor.prompt`
      verbatim and the user can blank the Top split. Fix in core: blank/whitespace
      prompt → `DEFAULT_COMPRESSION_PROMPT` (extend the draft tests; COMMIT semantics
      untouched — `K.meta["prompt"] == ""` still means manual). (3)
      `describe_state()["range_selection"]` returns raw node uuids (`app.py:835`),
      contradicting the method's own stated index convention (`app.py:764-766`); switch
      to indices into the reported `nodes` array and update the task-6 Pilot tests (a
      deliberate, recorded change — the field shipped this sprint, no external
      consumer). _Acceptance:_ Pilot: editor open → footer shows the editor hint, Esc →
      Edit hint restored; core test: `draft_compression(prompt="  ")` sends the default
      instruction to the provider; range Pilot tests assert indices.
      `scripts/check.sh` green.

- [x] **14. Core: `created_seq` column + migration** _(deps: none in 3b)_ — add
      `created_seq: int = 0` to `Node` (`ctx/models/nodes.py`); persist it: column in
      `_SCHEMA` + `_migrate` `ADD COLUMN` gated on the column being absent (the S2
      pattern, `storage.py:76-102`), with a one-time backfill assigning sequential
      ints **per conversation in rowid order** (valid: insertion order round-trips
      through the full-replace save — ADR-0016 A#3 §1); `save()`/`load()` carry it.
      `ConversationCore` assigns it at creation for **every** node entering `_graph`
      (line nodes, K, E): next = max over `_all_nodes()` + 1 (H6 — all nodes incl.
      folded children, abandoned tails, event nodes; never the view), counter
      initialized on `resume_conversation` from the loaded max, monotonic, **never
      reassigned** (A#2). `StoragePort` signatures unchanged → `SaveCountingStorage`
      untouched (verify). _Acceptance:_ code-blind tests: a raw pre-3b DB fixture
      (nodes without `created_seq`, the `conversation.md` migration-fixture pattern)
      migrates to strictly-increasing seqs in rowid order; new nodes after a rewind
      get max+1 (abandoned tail counted); K/E get seqs; round-trip preserves values;
      migration runs once (a second `init()` doesn't rewrite). `scripts/check.sh`
      green.

- [x] **15. Core: event-enumeration resolution (H3)** _(deps: 14)_ — swap
      `current_view()`'s fold step to the A#2/Q14 **now-rule** behind the same
      signature: walk `prev_id` for the raw line `L`; a compression K applies iff
      **no E targets it** (`E.meta["target"] == K.id`) **and** `K.meta["range"]` ⊆
      `L`; replace each applying K's run with K. `folded_children` reads
      `K.meta["range"]` (task 10 already does — confirm). `compressed_into` is still
      **written** (commit sets, expand clears — vestigial DB debuggability) but **no
      runtime code path reads it anymore** (ADR-0016 A#3 §3). All existing tests must
      pass unchanged — same observable behavior. _Acceptance:_ code-blind tests: a
      stale `compressed_into` pointer planted with no matching K range/event does
      NOT fold (resolution ignores pointers); after expand + re-compress of an
      overlapping range, K′ folds and the old K never reappears; `grep -rn
      "compressed_into" ctx/` shows write sites only (no reads in
      resolution/UI paths); full suite green. `scripts/check.sh` green. _Note
      (2026-07-03 review):_ the C81–C90 contract tests build graph state by assigning
      `core._graph`/`core._active_leaf_id` directly and are coupled to the pointer
      representation — if this swap breaks them, adapting them is a **deliberate,
      recorded** change (PROGRESS entry + spec in lockstep), not test-fudging.

- [ ] **16. Core: `context_at_generation` + drift predicate** _(deps: 14, 15)_ — new
      framework-free module (e.g. `ctx/core/reconstruction.py`), pure functions over
      a node list (Q11 — read-only, lazy, never on the live pipeline):
      `context_at_generation(all_nodes, node_id) -> list[Node]` — walk `prev_id` for
      T's **strict ancestors** `L`, then apply every K with `created_seq(K) <
      created_seq(T)`, range ⊆ `L`, and no E targeting K with `created_seq(E) <
      created_seq(T)` (the A#2 rule); `now_prefix(all_nodes, node_id)` — the same
      prefix under the task-15 now-rule; `has_drift(all_nodes, node_id) -> bool` —
      the two differ. _Acceptance:_ code-blind contract tests: a turn generated
      before a compression sees the range verbatim, one after sees K; a turn that
      saw K then `:expand`-ed after it drifts in the reverse direction (left K,
      right verbatim); expand→re-compress: each turn sees exactly the K active at
      its seq; a K whose range ⊄ L (abandoned-tail case) never applies; no-event
      conversations never drift. `scripts/check.sh` green.

- [ ] **17. Core: `ctx_hash` (H4)** _(deps: 16)_ — a pure canonical hasher (e.g. in
      the task-16 module): `hash_context(messages) -> str` = sha256 of
      `json.dumps(messages, sort_keys=True, ensure_ascii=False)`. In
      `ConversationCore.stream` (`conversation.py:321-323`), right after
      `build_context`, set `assistant_node.meta["ctx_hash"] = hash_context(messages)`
      — written once at the real generation moment, immutable after (ADR-0016 A#3
      §4; derivation stays the only truth — the hash is a tripwire). _Acceptance:_
      the **oracle suite** (code-blind): scripted sequences (turns → tip compress →
      turns → expand → turns → re-compress) assert, for **every** assistant node T,
      `hash_context(build_context(context_at_generation(all, T.id), read_file)) ==
      T.meta["ctx_hash"]`; a turn with no events trivially matches; if any existing
      node-equality test trips on the new meta key, adapt it as a deliberate change
      recorded in PROGRESS.md. `scripts/check.sh` green.

- [ ] **18. Config: `compression.default_prompt` + `ui.show_context_drift` (Q13)**
      _(deps: 7)_ — `ctx/core/config.py`: new top-level `"compression"` section in
      `_DEFAULTS` with `"default_prompt": <the exact preserve-info text>` plus a
      merge-guard block mirroring the `"ui"`/`"colors"` ones (`config.py:61-83`);
      `"show_context_drift": True` under `ui` with bool coercion. Single source: the
      core constant becomes a read of the config default; the editor's Top prefill
      (task 7) reads `get_config()["compression"]["default_prompt"]`. Overriding =
      editing the JSON by hand (no in-app editor — deferred). _Acceptance:_ extend
      `tests/test_config.py` + `tests/specs/config.md` (defaults present; a user
      override of `default_prompt` is preserved; invalid `show_context_drift`
      coerces to True); Pilot: with a patched user config, the editor opens
      prefilled with the override. `scripts/check.sh` green.

- [ ] **19. UI: drift indicator** _(deps: 16, 18)_ — expose the graph read-only:
      `ConversationCore.all_nodes() -> list[Node]` (public accessor over
      `_all_nodes()`). In `_refresh_token_ui()` (`app.py:402-417`) compute, for each
      **assistant** node in the view, `reconstruction.has_drift(...)`, gated by
      `get_config()["ui"]["show_context_drift"]`; new
      `MessageWidget.set_drift(bool)` renders a **subtle** marker (a single glyph
      next to the weight `Static` — many turns can legitimately drift, Q12/A#1;
      keep it quiet). `describe_state()` nodes gain `"drift": bool`. _Acceptance:_
      Pilot: U1,A1 → compress `[U1,A1]` (tip range) → U2,A2 (A2 sees K) →
      expand the K (the 13b Edit-mode key) → A2 has `drift: True`, A1 `False`;
      with `show_context_drift:
      false` all `False`. qa-tester spot-checks the marker. `scripts/check.sh`
      green.

- [ ] **20. UI: diff view overview (full-screen)** _(deps: 12, 17, 19)_ — extend the
      task-12 chord: `g d` on an **assistant node with drift** opens the context
      diff (on a K it still deep-dives — one family, one navigation stack, Q12);
      breadcrumb pushes "Diff › …". Full right-pane replacement showing **block
      alignment by node id** (H6 — shared ids are byte-identical by construction;
      never diff content): left = `context_at_generation(T)`, right =
      `now_prefix(T)`; contiguous changed regions marked (either direction: verbatim
      run ⟷ K, or many-to-many after expand+re-compress); `up`/`down` move a region
      cursor. On open, verify H4: recompute
      `hash_context(build_context(left, read_file))` vs `T.meta["ctx_hash"]` —
      mismatch (or missing hash on a pre-3b turn) shows a "reconstruction may be
      inexact" banner instead of lying (A#3 §4). `Esc`/`Ctrl+o` pop one level; `i`
      exits fully (family semantics). `describe_state()` gains `"diff_view":
      {"open": bool, "regions": [{"left": [ids], "right": [ids]}], "warning":
      bool}`. Note: pre-S5, import blocks render the live file on **both** sides —
      expected (Q12). _Acceptance:_ Pilot: build the task-19 drift → `g d` on A2 →
      `diff_view.open` with one region `left=[K.id]`, `right=[U1.id, A1.id]`
      (expand direction) and `warning: False`; tamper `ctx_hash` → `warning: True`;
      `Ctrl+o` restores the live view. qa-tester walks it. `scripts/check.sh`
      green.

- [ ] **21. UI: diff drill-down** _(deps: 20)_ — `Enter` on a marked region opens it
      full: left blocks rendered in full vs right blocks (regions are
      **many-to-many** block sequences, H6 — e.g. `[K]` ⟷ `[B, K′, E]`); pushes a
      breadcrumb level; `Ctrl+o` returns to the overview; `i` exits all the way.
      `describe_state().diff_view` gains `"drill": {"left": [...], "right": [...]}
      | None`. _Acceptance:_ Pilot: from the task-20 state, `Enter` on the region →
      drill populated with K's summary text on one side and the verbatim contents
      on the other; `Ctrl+o` → back at the overview with regions intact. qa-tester
      confirms navigation. `scripts/check.sh` green.

- [ ] **22. Enable middle compression (delete the 3a tip guard)** _(deps: 15, 16,
      17, 20)_ — remove the last-node-is-active-leaf check from
      `_validate_compress_range` (commit **and** draft; the Q7 no-K-in-range and H2
      streaming guards stay). The reconstruction path now carries the honesty the
      guard provided (Q5: "3b replaces the guard with the reconstruction path, not
      merely deletes it"). Extend the task-17 oracle suite with a middle sequence:
      U1,A1,U2,A2 → compress `[U1,A1]` → U3,A3 → oracle green for all four
      assistant turns; A2 drifts (saw verbatim, now K), A3 doesn't (born seeing K).
      _Acceptance:_ pytest: middle commit succeeds; extended oracle green; Pilot:
      middle compress → A2 `drift: True`, diff region `left=[U1,A1]` /
      `right=[K]`; the next turn's recorded context contains the summary, not the
      children. qa-tester: middle-compress a continued conversation, later turns
      read coherently, the earlier turn's diff shows what it saw.
      `scripts/check.sh` green.

- [ ] **23. Sprint 3 end-to-end verification (qa-tester, verify-feature)** _(deps:
      all)_ — no code changes. Full brief on the harness: (1) config-overridden
      default prompt reaches the editor prefill; (2) tip compress via draft→edit→
      commit; deep-dive + `Ctrl+o` + `i`; (3) middle compress on a continued
      conversation → later turns coherent; drift markers appear (and disappear with
      `show_context_drift: false`); (4) diff overview + drill-down in **both**
      directions (post-compression drift and post-expand drift), no warning banner
      on intact data; (5) expand → re-compress an overlapping range; (6) restart →
      everything persists (K, E, seqs, hashes); (7) `textual_check_errors` clean
      throughout. _Acceptance:_ qa-tester reports PASS on all checkpoints. Defects
      become new `- [ ]` tasks; do not patch inside this task.

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
