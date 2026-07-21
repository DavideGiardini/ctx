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

## 2026-07-21 — Task 2: delete the drift reading surface

**What:** Removed the context-drift `Δ` marker and everything feeding it, per the PRD
enumeration. `ctx/ui/widgets/message_row.py`: deleted `set_drift` + the `.drift` Static
from `compose`, updated the module docstring (`drift glyph +` → `kind glyph +`) and the
`_KIND_GLYPH` comment. `ctx/ui/widgets/message_list.css`: deleted the `.drift` rule and
reworded the `.meta-slot` comment (weight is now the only right-docked cell besides the
kind glyph). `ctx/core/config.py`: removed the `ui.show_context_drift` default and its
coercion guard. `ctx/ui/app.py`: removed the `reconstruction` import (drift was its only
UI use — Task 3 deletes the module), `_drift_cache` init, the three methods
`_turn_has_drift`/`_drift_signature`/`_node_drift`, the `drifted` computation in
`_sync_footer` (now `set_selection(node_type)`), the drift zip/`set_drift` in
`_refresh_token_ui`, and the `drift` field in `describe_state`. `ctx/ui/widgets/app_footer.py`:
removed `_selected_drifted`, the `drifted` arg on `set_selection`, and the `g d Drift`
edit hint (`_edit_hint` now only advertises `x Expand` for a K). Deleted
`scripts/ralph/probes/bench_drift.py`. Removed the N1 drift render from
`tools/agent/snapshot.py`.

**Tests:** No *new* tests — behavior-preserving deletion (removing a surface), so the
floor is the green gate + `rg` clean + qa-tester, matching Task 1. Deleted whole files
`test_app_drift.py`, `test_app_drift_cache.py`, `test_message_list_meta_layout.py`.
Pruned the N1 drift cases (CS1–CS4) + the `Δ`-absence assertion in CS26 from
`test_snapshot_sprint3.py` (and its spec `tests/specs/snapshot-sprint3.md`); removed the
C25/C25b `show_context_drift` cases + the C3 default assertion from `test_config.py`
(and the spec `tests/specs/config.md`); removed the single `.drift`-cell assertion +
docstring mention from `test_message_row.py`.

**Decision:** Reworded one *unrelated* use of the word "drifted" in the `_gauge_state`
docstring (gauge staleness, not the drift surface) to "changed" so the acceptance `rg`
sweep is genuinely clean and a future grep isn't misled.

**Verification:** `bash scripts/check.sh` green (ruff + mypy + 661 pytest passed).
Acceptance sweep `rg 'set_drift|_turn_has_drift|_node_drift|_drift_cache|show_context_drift|drifted'`
over `ctx/` returns nothing; `describe_state` has no `drift` field. qa-tester
(verify-feature, single launch) built turns, compressed a middle range into a K,
generated a turn *while the K was live*, then expanded it (a genuine historically-drifted
turn) — PASS on all five: no `Δ` on any row in any state, weight `w=N%` suffixes still
render, no `drift` key, footer never shows "Drift" (shows `x Expand` on a K, expected),
no crashes / stack stayed `[Screen]`. (No visual check needed — this is a removal, not a
render.)

**Gotcha for the next iteration (Task 3, oracles):** `ctx/core/reconstruction.py` is
still fully present — `has_drift`, `diff_regions`, `context_at_generation`, `now_prefix`,
`reconstruction_warning`, `DiffRegion`, `_fold`, `_strict_ancestors`, and the keeper
`hash_context`. After Task 2 the ONLY remaining importers of `reconstruction` are
`ctx/core/conversation.py` (the `ctx_hash` stamping path → `hash_context`) and the tests
`tests/test_reconstruction.py`, `tests/test_reconstruction_hash.py`, `tests/test_ctx_hash_oracle.py`.
`app.py` no longer imports it (Task 2 removed the last UI use). The `has_drift`/`diff_regions`
tests in `test_reconstruction.py` still pass (the core oracle is intact) — Task 3 deletes
that file. `Static` is still imported and used in `message_row.py` (kind glyph + weight).

## 2026-07-21 — Task 3: delete the as-of oracles; relocate `hash_context`

**What:** Completed the ctx0 subtraction pass. Deleted `ctx/core/reconstruction.py`
entirely (`context_at_generation`, `now_prefix`, `has_drift`, `diff_regions`,
`reconstruction_warning`, `DiffRegion`, `_fold`, `_strict_ancestors`). Moved the one
keeper, `hash_context`, into `ctx/core/context.py` (added `hashlib`/`json`/`Any`
imports there) and updated its docstring to state the stamp is now *write-only* under
ADR-0017. Re-pointed the two surviving importers: `ctx/core/conversation.py` (the
`ctx_hash` stamping path — added `hash_context` to its existing `ctx.core.context`
import block) and `tests/test_reconstruction_hash.py` (`from ctx.core.context import
hash_context`). Reworded the now-stale comments in `conversation.py` that referenced a
live "reconstruction path / oracle / drift+diff" (the `streaming` docstring, the
`all_nodes` docstring, the `submit` AIDEV-NOTE, the `select_range` guard docstring, and
the `_stream_and_end` stamp AIDEV-NOTE) so the acceptance `rg` sweep is genuinely clean
and no comment implies a deleted surface still exists — the H2 invariant is unchanged,
only its rationale prose. Updated `tests/specs/reconstruction-hash.md` (Module line →
`ctx/core/context.py`; dropped the cross-ref to the deleted `reconstruction.md`).
Dropped `reconstruction` from the CLAUDE.md core-layer parenthetical.

Deleted tests `tests/test_reconstruction.py` (+ spec `tests/specs/reconstruction.md`)
and `tests/test_ctx_hash_oracle.py` (both drove the now-deleted oracle).

**Deviation (recorded per PROMPT.md rule):** the PRD enumeration did NOT mention
`scripts/ralph/probes/test_adversarial_core.py`, a throwaway S3 probe that imports and
calls the deleted `context_at_generation` at 6 sites. It is dead the moment the oracle
is gone, so I deleted it — consistent with Task 2's deletion of the throwaway
`bench_drift.py` probe when it removed the drift surface. Not in `testpaths` so it never
ran under the gate; mypy scanned it but (cache) did not flag the dangling import — deleted
regardless because it can no longer function.

**Tests:** Added ONE focused regression test, `tests/test_ctx_hash_stamp.py`
(`test_committed_turn_carries_ctx_hash`): drives a real turn (submit→drain→end_turn) and
asserts the committed assistant node carries a valid 64-char sha256-hex `ctx_hash`. The
deleted `test_ctx_hash_oracle.py` was the ONLY coverage that a *driven* turn stamps a
hash; deleting it (correct — it tested the oracle) left the acceptance keeper "a committed
turn still carries `meta["ctx_hash"]`" unguarded, and a Part-B regression dropping the
write-only stamp would otherwise pass silently. Black-box (presence + hex shape), not
implementation-coupled; a dropped stamp → `meta.get("ctx_hash")` is None → fails. `hash_context`'s
own behavior stays covered by the re-pointed `test_reconstruction_hash.py` (9 tests).

**Verification:** `bash scripts/check.sh` green (ruff + mypy + 622 pytest passed).
Acceptance sweep: `rg 'reconstruction' ctx/ tools/` returns only the concept-word inside
`hash_context`'s docstring ("verify a reconstruction against it") — the *module* is gone
with zero importers (`rg 'from ctx.core.reconstruction|import reconstruction'` over the
whole repo hits only the archived sprint3 PROGRESS log). `from ctx.core.context import
hash_context` imports and runs. Pure-core task — no qa-tester (green gate + hash tests +
the new stamp guard are the verification, per the PRD).

**Part A is complete** — all three subtraction tasks shipped. The app keeps middle
compaction, the 3-split inspector, and still stamps `created_seq`/`ctx_hash` on every
turn (now write-only), and exposes none of the drift / diff / deep-dive reading surfaces.
`ConversationCore.current_view` is now the sole fold implementation. Part B (the render
redesign) is out of scope for this loop — done in-conversation.
