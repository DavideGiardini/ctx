# PRD (done) — ctx0 Phase 2 Part A: the subtraction pass

Completed task bodies, cut verbatim from `scripts/ralph/PRD.md` as each landed.
The live worklist and the one-line "Completed" ledger stay in `PRD.md`.

## Tasks

- [x] **Delete the full-screen drill surfaces (DiffView + deep-dive)** — Remove the
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
