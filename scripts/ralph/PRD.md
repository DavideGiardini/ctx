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

## Tasks

- [ ] **Delete the full-screen drill surfaces (DiffView + deep-dive)** — Remove the
      whole full-screen inspection view stack. Ref: ADR-0017 §3 ("the `g d` binding
      and the full-screen-inspection view stack go entirely"). Delete
      `ctx/ui/widgets/diff_view.py` in full. In `ctx/ui/app.py` remove: the
      `DiffView` import, `self._diff_view`, `self._deep_dive_stack`, the
      `yield DiffView(...)` in compose, the `ctrl+o` binding + `action_pop_deep_dive`,
      the `g`-chord handling in `on_key` + `_pending_chord`, `_drill_selected` (both
      branches), `_enter_deep_dive`, `_refresh_deep_dive_view`, `_enter_diff`,
      `_toggle_diff_fullscreen`, `_close_diff`, `_move_region_cursor`,
      `_drill_diff_region`, `_close_drill`, `_in_full_screen_inspection` (and drop
      its guard at its three callers), `_diff_view_state`, the diff branches in
      `action_up`/`action_down`/`action_detail_enter`, the diff-view escape/`i`
      branches, and the diff/deep-dive teardown in `_reset_transient_ui` (keep the
      editor/worker/selection reset). **Simplify `_visible_nodes` to
      `return self.core.nodes` but KEEP it** (many callers). In `describe_state`
      remove the `deep_dive` and `diff_view` blocks and drop the `in_deep_dive`
      gating of weights/drift (keep the `drift` field — Task 2 owns it). In
      `_refresh_token_ui` remove the dive branch (leaving only the live branch);
      delete now-dead `MessageRow.set_weight_not_in_context`
      (`ctx/ui/widgets/message_row.py`). In `ctx/ui/widgets/app_footer.py` remove
      `set_deep_dive` + the `deep_dive` hint (diff and dive were its only callers).
      Remove the deep_dive/diff sections from `tools/agent/snapshot.py` and the
      `_state_drift_diff*` scenarios from `tools/agent/visual.py`. Delete tests
      `tests/test_app_diff_view.py`, `tests/test_app_deep_dive.py`,
      `tests/test_app_deep_dive_hardening.py`; delete the two deep-dive tests + the
      local `_enter_deep_dive` helper in `tests/test_app_new_resume_reset.py` (keep
      the rest of that file); delete the `test_drift_diff*` cases in
      `tests/test_visual_states.py`; delete the N4 (deep_dive) and N5 (diff_view)
      sections in `tests/test_snapshot_sprint3.py`. _Acceptance:_
      `bash scripts/check.sh` green; `rg 'DiffView|_deep_dive_stack|_diff_view|_drill_selected|set_deep_dive'`
      over `ctx/` returns nothing; qa-tester confirms that on a committed K and on an
      assistant turn, pressing `g d` and `ctrl+o` does nothing and never opens a
      full-screen view (screen stack unchanged, no crash), and `describe_state()` has
      no `deep_dive`/`diff_view` keys.

- [ ] **Delete the drift reading surface** — Remove the context-drift `Δ` marker and
      everything feeding it. Ref: ADR-0017 §2. In `ctx/ui/widgets/message_row.py`
      delete `set_drift` and the `.drift` Static from `compose`; drop the "alongside
      the drift Δ" note on `_KIND_GLYPH`. In `ctx/ui/widgets/message_list.css` delete
      the `.drift` rule and simplify `.meta-slot` (only the kind glyph + weight
      remain — those must look unchanged). In `ctx/core/config.py` delete the
      `ui.show_context_drift` default and its coercion guard. In `ctx/ui/app.py`
      delete `_drift_cache`, `_drift_signature`, `_node_drift`, `_turn_has_drift`,
      their use in `_refresh_token_ui` (keep the weight-setting), the `drift` field
      in `describe_state`, and the `drifted` computation feeding `_sync_footer`. In
      `ctx/ui/widgets/app_footer.py` remove `_selected_drifted`, the `drifted` arg on
      `set_selection`, and the "g d Drift" edit hint. Delete
      `scripts/ralph/probes/bench_drift.py`. Remove the N1 drift section from
      `tools/agent/snapshot.py`. Delete tests `tests/test_app_drift.py`,
      `tests/test_app_drift_cache.py`, `tests/test_message_list_meta_layout.py`;
      remove the N1 drift tests in `tests/test_snapshot_sprint3.py`; remove the C25
      `show_context_drift` cases in `tests/test_config.py`; remove the single
      `.drift`-cell assertion (and its docstring mention) in
      `tests/test_message_row.py` (keep the rest). _Acceptance:_
      `bash scripts/check.sh` green;
      `rg 'set_drift|_turn_has_drift|_node_drift|_drift_cache|show_context_drift|drifted'`
      over `ctx/` returns nothing; `describe_state()` has no `drift` field; qa-tester
      confirms that after an expand that historically drifted a turn, no `Δ` marker
      appears in any row and weights still render.

- [ ] **Delete the as-of oracles; relocate `hash_context`** — In
      `ctx/core/reconstruction.py` delete `context_at_generation`, `now_prefix`,
      `has_drift`, `diff_regions`, `reconstruction_warning`, `DiffRegion`, and the
      now-orphaned helpers `_fold` and `_strict_ancestors`. Ref: ADR-0017 §2 (delete
      oracles) + §4 ("duplication resolved by deletion" — `current_view` becomes the
      sole fold). **Keep `hash_context`:** move it into `ctx/core/context.py` (it
      hashes a `build_context` output; add the `hashlib`/`json`/`Any` imports there)
      and delete `ctx/core/reconstruction.py` entirely. Re-point the two surviving
      importers — `ctx/core/conversation.py` (the `ctx_hash` stamping path) and
      `tests/test_reconstruction_hash.py`. Delete tests `tests/test_reconstruction.py`
      (+ `tests/specs/reconstruction.md`) and `tests/test_ctx_hash_oracle.py`. Keep
      `tests/test_reconstruction_hash.py` with its import re-pointed to
      `ctx.core.context` (update the path reference in `tests/specs/reconstruction-hash.md`
      too). Update the CLAUDE.md architecture map to drop `reconstruction.py`.
      _Acceptance:_ `bash scripts/check.sh` green;
      `rg 'reconstruction' ctx/ tools/ tests/` shows the module gone (no importers);
      `from ctx.core.context import hash_context` works and its tests pass; a
      committed assistant turn still carries `meta["ctx_hash"]` (stamping path
      intact). Pure-core task — no qa-tester needed (green gate + hash tests are the
      verification).

## Out of scope
- **Part B — the rendering redesign** (separator widget, retiring the four spacing
  mechanisms, truncation-map fix). Done in-conversation, not this loop.
- Anything ADR-0017 §4 dropped: ViewStack, typed meta accessors beyond
  `interrupted`/`error`, the StoragePort read collapse, fold unification *as a
  refactor* (it resolves by deletion in Task 3, not by extraction).
- Any change to the append-only graph, node kinds, compaction, `current_view`, or
  the detail inspector.
