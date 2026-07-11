# Ralph progress — shared Pilot test scaffolding (ctx0 Phase 1, step 1)

Append-only memory across loop iterations. Sprint 3's log is archived at
`scripts/ralph/archive/sprint3/PROGRESS.md`.

## 2026-07-11 — Task 1: shared provider doubles in conftest.py

Extracted the three duplicated hand-rolled provider doubles into one canonical
copy each in `tests/conftest.py`: `BlockingProvider(before, gate)`,
`RecordingProvider(tokens)`, `ErroringProvider()`. Migrated all 13 local copies
across 11 test files; the acceptance grep now returns nothing and the collected
count is unchanged (705 → 705).

Key decisions a future iteration must know:
- **Access pattern = direct import, NOT fixtures.** Tests reference the classes
  with `from conftest import BlockingProvider, ...`. The PRD said to keep the
  names un-prefixed "since they are now a shared surface", which only makes sense
  if tests name them directly; and the module-level Pilot helpers that construct
  these providers (`_start_blocked_draft`, `_submit_blocked`) have no fixture
  access, so a fixture would have forced reshaping those helpers (that's task 3's
  job). `conftest` importability works because pytest's prepend import mode puts
  `tests/` on `sys.path`. Ruff's isort classifies `conftest` as **third-party**
  (sorts it into that group, before `ctx`) — I ran `ruff check --fix tests/` to
  normalize the new import lines; do the same in tasks 2–4.
- **Unified `stream` signature** is `(self, messages, model=None, on_usage=None)`.
  `model` gets a default so it also serves `test_draft_compression.py`'s doubles,
  which originally used `*args`/`**kwargs`. `check_connectivity` returns the
  `(True, "ok")` tuple everywhere (the old Pilot `_RecordingProvider` returned a
  bare `True`, but its `check_connectivity` is never called in those tests, so the
  tuple is strictly safer and changes no behavior).
- **`RecordingProvider` attribute unification:** standardized on `.captured`
  (messages) + `.called` (bool). The two Pilot copies used `.last_messages`; I
  renamed those 2 call sites to `.captured`. Forced by the merge, not a logic
  change.
- **`test_draft_compression.py`'s `BlockingProvider` diverged** (no-arg ctor +
  `.release()` method). Migrated it mechanically to `(["thinking"], gate)` and
  `gate.set()` in place of `blocker.release()` — same "yield a token, block,
  release" behavior, `AFTER` replaces the never-consumed `done`.
- Left untouched (not in task 1's list): `CapturingProvider`, `FailingProvider`,
  `FailingConnectivityProvider`, `ModelCapturingProvider` in `test_conversation.py`.

No new tests (behavior-preserving refactor; floor is same-tests-pass). No
qa-tester / visual check — test-only change, no runtime surface; `scripts/check.sh`
green (ruff + mypy + 705 pytest) is the verification.
