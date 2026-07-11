# PRD — Shared Pilot test scaffolding (conftest extraction)

## Goal
Extract the ~420 lines of Pilot test scaffolding duplicated across the
`tests/test_app_*.py` family into shared homes, so the suite has one copy of each
helper instead of ~19 hand-synced ones (already diverging — see the inconsistent
`if mode == "edit": escape` workarounds). This is the "Test choreography helpers"
item from `docs/Code Quality Review 2026-07.md` and the first step of ctx0 Roadmap
Phase 1: the turn-lifecycle work that follows will add new Pilot tests, and they
must be written against shared helpers, not a 20th copy of the duplication.

## Constraints / notes
- **Behavior-preserving refactor only.** No product code (`ctx/**`) changes. No new
  test cases, no deleted test cases — every task's floor is: the same tests are
  collected and all pass. Capture the collected count with
  `uv run pytest --collect-only -q | tail -1` *before* migrating and compare after.
- **Placement (decided, don't relitigate):** fixtures and provider double *classes*
  go in `tests/conftest.py` (the pattern exists — `_VaryingProvider` already lives
  there); keystroke-choreography *functions* go in a new importable
  `tests/pilot_helpers.py` (plain functions don't belong in conftest, which is not
  meant to be imported from).
- Shared helpers are used by many files, so give them real docstrings; keep names
  un-prefixed (`BlockingProvider`, not `_BlockingProvider`) since they are now a
  shared surface.
- **Deadlock trap (must go in `BlockingProvider`'s docstring):** an always-blocking
  provider must never be used for setup turns that fully drain — a turn awaited to
  completion against a gate that is never set deadlocks the whole pytest run. Setup
  turns use the default scripted provider; the blocking one is only for the turn
  under test.
- Migrate mechanically; do NOT "improve" test logic while moving it. Where an
  existing copy genuinely diverges from the common shape, either parameterize the
  shared helper (preferred when the divergence is one knob, e.g. range width) or
  leave that copy in place — never force-fit.
- No qa-tester runs needed anywhere in this PRD: test-only changes have no runtime
  surface; `scripts/check.sh` green IS the verification.
- `tests/README.md` documents conventions; task 4 updates it so future sessions
  know the shared scaffolding exists.

## Tasks

- [ ] **1. Shared provider doubles in `tests/conftest.py`** — Add `BlockingProvider`
      (unify the two flavors: core tests construct `(tokens, gate)` and pass it to
      `ConversationCore`; Pilot tests construct `(before, gate)` and hot-swap it via
      `app.core._provider` — one class with one signature can serve both),
      `RecordingProvider` (captures the messages of the last `stream` call), and
      `ErroringProvider` (raises mid-stream). Include the deadlock warning in
      `BlockingProvider`'s docstring (see Constraints). Migrate all local copies:
      Pilot `_BlockingProvider` in `test_app_cancel_empty_node.py`,
      `test_app_draft_worker_lifecycle.py`, `test_app_draft_prompt_reset.py` (which
      also holds `_ErroringProvider`), `test_app_new_resume_reset.py`,
      `test_app_commit_failures.py`; core `BlockingProvider` in
      `test_conversation.py`, `test_commit_compression.py`,
      `test_expand_compression.py`, `test_draft_compression.py`;
      `_RecordingProvider` in `test_app_compress_payload.py`, `test_app_expand.py`,
      and core `RecordingProvider` in `test_draft_compression.py`.
      _Acceptance:_ `grep -rn "class _\?BlockingProvider\|class _\?RecordingProvider\|class _\?ErroringProvider" tests/ --include="test_*.py"`
      returns nothing (the classes exist only in `conftest.py`); collected test
      count identical to before; `bash scripts/check.sh` green.

- [ ] **2. Shared app factory in `tests/conftest.py`** — Add an `app_factory`
      fixture (built on the existing `repo`/`workspace` fixtures) returning a
      function that constructs `ChatApp` with a `TestProvider(["ok"])` default and
      covers the observed variations: injectable provider instance, or scripted
      tokens + usage (e.g. `test_app_draft_compression.py` uses scripted tokens with
      `Usage(12, 5, 17)`). Migrate the 19 `def _app` copies (list in
      `docs/Code Quality Review 2026-07.md` §Test choreography helpers; find them
      with `grep -rn "def _app" tests/`), the misnamed async `_four_node_app` in
      `test_app_range_selection.py`, and the inlined `ChatApp(...)` constructions in
      `test_app_gauge.py` / `test_app_weights.py` where per-test usage scripting
      maps cleanly onto the factory.
      _Acceptance:_ `grep -rn "def _app\b" tests/` returns nothing; collected test
      count identical to before; `bash scripts/check.sh` green.

- [ ] **3. Turn/submit choreography in `tests/pilot_helpers.py`** — Create the
      module with: `two_turns(app)` (submit "first"/"second" via
      `on_input_bar_submitted` + `wait_for_complete` — the shape duplicated in ~15
      files), `turn(app, text)` (single-turn variant, in `test_app_drift.py` /
      `test_app_diff_view.py`), and `wait_until_streaming(app, pilot)` replacing the
      copy-pasted bounded `pilot.pause()` spin loops (`_submit_blocked` in
      `test_app_cancel_empty_node.py`, `_start_blocked_draft` in
      `test_app_draft_worker_lifecycle.py` / `test_app_new_resume_reset.py`, inlined
      loops in `test_app_draft_prompt_reset.py` / `test_app_commit_failures.py` —
      keep the bounded-iterations shape; a wait that can hang forever is worse than
      the duplication). Migrate all users; `test_app_range_selection.py` inlines the
      two submits without a helper — migrate it too.
      _Acceptance:_ `grep -rn "def _two_turns\|def _turn\b" tests/` returns nothing;
      collected test count identical to before; `bash scripts/check.sh` green.

- [ ] **4. Compress-via-editor choreography in `tests/pilot_helpers.py`** — Add:
      `open_editor_on_range(pilot, *, downs=3)` (escape → home → `v` + `downs`×down
      → `c`; form B), `compress_range(app, pilot, summary, *, downs=3)` (form A =
      form B + set `#compress-output` text + `ctrl+s`), and
      `select_tip_in_edit(app, pilot)` (the mode-guarded double-escape that
      replaces the inconsistent `if mode == "edit": escape` workarounds). The
      `downs` knob absorbs the 2-node variants (`test_app_drift.py`,
      `test_app_diff_view.py`). Migrate the extracted helpers
      (`_compress_full_tip_range`, `_open_editor_on_full_range`,
      `_select_k_in_edit`, `_select_tip_in_edit`) and the inlined copies in
      `test_app_footer_context.py`, `test_app_transient_hints.py`,
      `test_app_reconcile.py`, `test_app_compression_editor.py`,
      `test_app_range_selection.py`, `test_app_commit_failures.py`. Leave genuinely
      divergent choreography alone (e.g. `test_app_diff_view.py`'s
      `_middle_compress_scenario` compressing a non-tip range, and
      `test_app_reconcile.py`'s trailing-range navigation) — parameterize only if
      it stays one obvious knob. Then document the shared scaffolding (conftest
      fixtures + `pilot_helpers`) in `tests/README.md` so future sessions reuse
      instead of re-declaring.
      _Acceptance:_ `grep -rn "def _compress_full_tip_range\|def _open_editor_on_full_range\|def _select_k_in_edit\|def _select_tip_in_edit" tests/`
      returns nothing; `tests/README.md` names both shared-scaffolding homes;
      collected test count identical to before; `bash scripts/check.sh` green.

## Out of scope
- Any change under `ctx/**` — this PRD touches only `tests/` (and `tests/README.md`).
- The turn-lifecycle work itself (core `end_turn`, submit refusal, UI convergence,
  cancel coverage) — that is Phase 1's main body, done in-conversation after this
  loop, NOT here.
- New test cases or coverage improvements — same tests before and after.
- `tools/agent/**` (the qa-tester harness) — untouched.
- The `HarnessApp`-based files (`test_visual_states.py`, `test_message_row.py`,
  `test_message_list_meta_layout.py`) — they don't share these shapes; leave them.
