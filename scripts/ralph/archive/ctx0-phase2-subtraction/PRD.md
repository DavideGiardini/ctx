# PRD — ctx0 Phase 2 Part A: the subtraction pass

## Goal
Make the codebase ctx0-shaped by **deleting the context-transparency reading
surfaces** ADR-0017 cut, while continuing to *write* the underlying data. Three
deletions, in order: the full-screen drill surfaces (`DiffView` + deep-dive), then
the drift `Δ` marker, then the as-of reconstruction oracles (relocating the one
keeper, `hash_context`). When all three are done the app keeps middle compaction and
the 3-split inspector, still stamps `created_seq`/`ctx_hash` on every turn, but
exposes none of the drift / diff / deep-dive surfaces. This is Part A only; the
rendering redesign (Part B) is done in-conversation, NOT in this loop.

Design authority: **`docs/decisions/0017-ctx0-rescope.md` §2–3** ("keep writing the
data, delete the reading surface"). Full spec:
`/home/giardo/.claude/plans/let-s-start-planning-phase-sleepy-hippo.md` (Part A).

## Constraints / notes
- **Order is load-bearing.** Task 1 (drill) must precede Task 2 (drift): the drill
  dispatch `_drill_selected` (`ctx/ui/app.py`) calls `_turn_has_drift`, so removing
  drift first would leave a dangling call. Task 3 (oracles) is last — it deletes
  functions only Tasks 1–2's callers referenced. The loop takes the topmost
  unchecked task; keep this order. (Between commits it is fine that the footer still
  hints "g d Drift" for one task while `g d` is already inert — transient, green,
  shippable; Task 2 removes the hint.)
- **Do NOT touch (ADR-0017 Consequences):** node kinds, `Node.goes_to_model()`, the
  compression event model (K/E), the append-only graph (`prev_id`, `rewind`,
  `E.meta.anchor`), and **`ConversationCore.current_view`** (`ctx/core/conversation.py`)
  — after Task 3 it becomes the *sole* fold implementation. "ctx0 subtracts views,
  not the graph."
- **Keep and do not break:** `created_seq` + `meta["ctx_hash"]` stamping on every
  turn (they go write-only now — intentional), the `hash_context` function (Task 3
  relocates it, never deletes it), the 3-split **detail inspector**
  (`ctx/ui/widgets/detail_inspector.py`) and its always-present left-pane
  invocation, and `tests/test_created_seq.py` (leave untouched).
- Several UI methods (`describe_state`, `_refresh_token_ui`, `_visible_nodes`,
  `_reset_transient_ui`) carry *co-located* drift AND deep-dive/diff concerns. Each
  task removes only its own lines and leaves the method green; expect to edit the
  same method in more than one task.
- `tools/agent/snapshot.py` and `tools/agent/visual.py` render these surfaces; the
  task that removes a surface also removes its rendering there and the tests that
  drive it. Tooling imports from `ctx`, never the reverse.

## Completed
- [x] 1 — Delete the full-screen drill surfaces (DiffView + deep-dive)  *(body in PRD-done.md)*
- [x] 2 — Delete the drift reading surface  *(body in PRD-done.md)*
- [x] 3 — Delete the as-of oracles; relocate `hash_context`  *(body in PRD-done.md)*

## Tasks

*(all tasks complete — Part A subtraction pass done)*

## Out of scope
- **Part B — the rendering redesign** (separator widget, retiring the four spacing
  mechanisms, truncation-map fix). Done in-conversation, not this loop.
- Anything ADR-0017 §4 dropped: ViewStack, typed meta accessors beyond
  `interrupted`/`error`, the StoragePort read collapse, fold unification *as a
  refactor* (it resolves by deletion in Task 3, not by extraction).
- Any change to the append-only graph, node kinds, compaction, `current_view`, or
  the detail inspector.
