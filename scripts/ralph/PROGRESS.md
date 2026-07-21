# Ralph progress — ctx0 Phase 2 Part A: the subtraction pass

Append-only memory across loop iterations. The prior run (shared Pilot test
scaffolding, ctx0 Phase 1 step 1) is archived at
`scripts/ralph/archive/conftest-scaffolding/PROGRESS.md`; Sprint 3's log at
`scripts/ralph/archive/sprint3/PROGRESS.md`.

<!-- Each iteration appends a dated entry here (PROMPT.md step 8): what it did, tests
added or why none, verification run, key decisions, and any gotcha a future fresh
iteration must know. -->

## 2026-07-21 — Task 1: delete the full-screen drill surfaces (DiffView + deep-dive)

**What:** Removed the entire full-screen inspection view stack (deep-dive over a K's
folded originals + the context-diff `DiffView`). Deleted `ctx/ui/widgets/diff_view.py`
in full. In `ctx/ui/app.py` removed the `DiffView` import, `_diff_view`,
`_deep_dive_stack`, `_pending_chord`, the compose `yield DiffView(...)`, the `ctrl+o`
binding + `action_pop_deep_dive`, `on_key` (g-chord), `_drill_selected`,
`_enter_deep_dive`, `_refresh_deep_dive_view`, `_enter_diff`, `_toggle_diff_fullscreen`,
`_close_diff`, `_move_region_cursor`, `_drill_diff_region`, `_close_drill`,
`_in_full_screen_inspection` (+ its 3 caller guards), `_diff_view_state`, the diff
branches in `action_up`/`action_down`/`action_detail_enter`, the diff/dive escape/`i`
back-out branches, the deep-dive guard in `_mount_node`, and the diff/dive teardown in
`_reset_transient_ui`. `_visible_nodes` simplified to `return self.core.nodes` (kept).
`describe_state` lost the `deep_dive`/`diff_view` keys and the `in_deep_dive` gating
(the `drift` field stays — Task 2 owns it). `_refresh_token_ui` keeps only the live
branch. Also dropped the now-unused `from textual import events`. Deleted
`MessageRow.set_weight_not_in_context`; `AppFooter.set_deep_dive` + the `deep_dive`
hint. Removed the breadcrumb + diff sections from `tools/agent/snapshot.py`, and the
`_state_drift_diff*` scenarios + task-50 fixture + align-* post-variants from
`tools/agent/visual.py`.

**Tests:** No *new* tests — this is a behavior-preserving deletion (removing surfaces),
so the floor is the green gate + `rg` clean + qa-tester. Deleted whole files
`test_app_diff_view.py`, `test_app_deep_dive.py`, `test_app_deep_dive_hardening.py`;
pruned the 2 deep-dive tests + `_enter_deep_dive` helper from
`test_app_new_resume_reset.py`; removed the 2 `test_drift_diff*` cases + align-*
variants from `test_visual_states.py`; removed the N4/N5 sections from
`test_snapshot_sprint3.py` (and updated its spec `tests/specs/snapshot-sprint3.md`).

**Deviation (recorded per PROMPT.md rule):** Task 1's enumeration did NOT list
`test_gd_diff_is_noop_on_drifted_turn_when_config_disabled` in `tests/test_app_drift.py`,
but that test asserts on `describe_state()["diff_view"]` — a key Task 1 removes — so it
would KeyError. It is a diff-*surface* test (asserts `g d` opens no diff), so I deleted
it now (consistent with "remove the tests that drive the surface"). The two genuine
drift tests in that file stay for Task 2.

**Verification:** `bash scripts/check.sh` green (ruff + mypy + 677 pytest passed).
`rg 'DiffView|_deep_dive_stack|_diff_view|_drill_selected|set_deep_dive'` over `ctx/`
returns nothing. qa-tester (verify-feature, single launch) confirmed PASS on all five:
`g d` on an assistant turn is inert; `ctrl+o` is inert; `g d` on a committed K is inert;
no `deep_dive`/`diff_view` keys in `describe_state()`; no errors/crashes — screen stack
stayed `[Screen]` throughout. (No visual check needed — this is a removal, not a render.)

**Gotcha for the next iteration (Task 2, drift):** `_turn_has_drift`, `_node_drift`,
`_drift_cache`, `_drift_signature`, `MessageRow.set_drift`, the `.drift` Static/CSS, and
`AppFooter`'s `g d Drift` hint / `_selected_drifted` are all STILL PRESENT — Task 1
deliberately left the drift surface intact. The `.drift` CSS rule is at
`ctx/ui/widgets/message_list.css:49`. `describe_state` still returns `drift`.
