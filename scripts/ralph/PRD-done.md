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
