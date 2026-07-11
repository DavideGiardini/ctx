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

## 2026-07-11 — Task 2: shared app factory in conftest.py

Added an `app_factory` fixture to `tests/conftest.py` (closes over the shared
`repo`/`workspace` fixtures) and deleted the 19 `def _app` copies + the async
`_four_node_app` in `test_app_range_selection.py` + the inline `ChatApp(...)`
constructions in `test_app_gauge.py` / `test_app_weights.py`. Acceptance grep
`def _app\b` returns nothing; collected count unchanged (705 → 705); gate green.

Factory shape: `app_factory(provider=None, *, tokens=None, usage=None)`. Default
builds `TestProvider(["ok"])`. `provider=` injects a specific double (expand /
compress_payload); `tokens=`/`usage=` script the default provider
(gauge/weights/draft-compression). `provider` wins over tokens/usage.

Key decisions a future iteration must know:
- **`app_factory` is a fixture, not an import** (unlike task 1's provider classes),
  because the PRD said so and because it must close over the `repo`/`workspace`
  fixtures. Tests that used to be `def test_x(repo, workspace)` are now
  `def test_x(app_factory)`; the two fixtures are still instantiated (as
  `app_factory`'s deps), so behavior/count are identical. Extra params
  (`monkeypatch`, `tmp_path`) are preserved — only the `repo, workspace` pair was
  swapped for `app_factory`.
- **`ChatApp` is imported at conftest module top**, so the fixture's return
  annotation type-checks. This pulls textual into every pytest session (incl.
  core-only runs); accepted as the simplest home since the full suite imports it
  anyway. `provider` param is typed `Provider | None` and the hand-rolled doubles
  (RecordingProvider etc.) structurally satisfy it — mypy is green.
- **Migration was scripted** (a one-off Python pass): delete the `def _app` block
  normalizing to 2 blank lines, rewrite `_app(repo, workspace[, provider=…])` →
  `app_factory([provider=…])`, then rewrite the bare `repo, workspace` param pair →
  `app_factory`. `draft_compression` maps to `app_factory(tokens=_DRAFT_TOKENS,
  usage=Usage(12, 5, 17))` (4 call sites — the centralization moved from `_app`
  into the factory's default-provider path, so the tokens/usage now recur at the
  call sites; acceptable and explicit). Then `ruff check --fix tests/` dropped the
  now-unused `ChatApp`/`CannedProvider` imports (44 F401 autofixes).
- **Gotcha:** the acceptance grep is `def _app\b` with a word boundary, so the
  string `def _app` in a *docstring* (backtick after `_app` = boundary) trips it.
  Reworded the conftest docstring to say "an ``_app`` factory copy" so the grep is
  genuinely empty.
- `test_provider.py` still aliases `TestProvider as CannedProvider` — out of scope
  (it's the provider unit test, not a Pilot app test); left untouched.

No new tests (behavior-preserving refactor). Verification = green gate.
