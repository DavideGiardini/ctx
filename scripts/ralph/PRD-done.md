# PRD (done) — Shared Pilot test scaffolding (conftest extraction)

Completed task bodies, cut verbatim from `PRD.md` as each finishes. See the
"Completed" ledger in `PRD.md` for the one-line index.

## Tasks

- [x] **1. Shared provider doubles in `tests/conftest.py`** — Add `BlockingProvider`
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

- [x] **2. Shared app factory in `tests/conftest.py`** — Add an `app_factory`
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
