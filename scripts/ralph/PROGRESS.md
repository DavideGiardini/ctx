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

## 2026-07-11 — Task 3: turn/submit choreography in tests/pilot_helpers.py

Created `tests/pilot_helpers.py` (the second shared-scaffolding home, importable
alongside `conftest`) with `two_turns(app)`, `turn(app, text)`, a generic
`wait_until(pilot, predicate, *, tries=200) -> bool`, and `wait_until_streaming(app,
pilot)`. Migrated the 15 identical `_two_turns` copies, the two `_turn(app, text)`
copies (drift/diff_view), the inlined two-submit blocks + single submits in
`test_app_range_selection.py`, and the spin loops in `_submit_blocked`
(cancel_empty_node), both `_start_blocked_draft` (draft_worker_lifecycle,
new_resume_reset), and the inlined loops in draft_prompt_reset + commit_failures.
Acceptance grep `def _two_turns\|def _turn\b` returns nothing; collected count
unchanged (705 → 705); gate green (ruff + mypy + 705 pytest).

Key decisions a future fresh iteration must know:

- **Two wait helpers, not one.** The PRD names `wait_until_streaming(app, pilot)`,
  but the ~6 spin-loop sites guard on genuinely different predicates (`_stream_worker`
  live + rendered node content; `_draft_worker` live; `_draft_worker` live + editor
  text; `worker.is_finished` — a *finish* wait; `core.streaming`). The one obvious
  shared knob is the predicate, so the real primitive is a generic bounded
  `wait_until(pilot, predicate, *, tries=200)` that returns whether the condition held
  within the bound (callers `assert` on it, so an exhausted bound fails loudly — a
  wait that hangs forever is worse than the duplication, per the PRD). `wait_until_streaming`
  is a thin PRD-named convenience over it for the plain `core.streaming` case
  (commit_failures) — kept because Phase-1 turn-lifecycle tests will reuse it.
- **`_submit_blocked` uses `wait_until` with its FULL predicate (incl. the
  `_streaming_node.content == want` check), NOT `wait_until_streaming`.** Dropping the
  content check to `core.streaming` would weaken the "tokens actually rendered"
  guarantee the zero/partial-token cancel tests rely on. Same for the draft helpers —
  they keep their draft-worker predicates.
- **Renamed `test_ctx_hash_oracle.py`'s `_turn(core, prompt)` → `_core_turn`.** It is
  a different, core-level helper (returns the assistant node, no Pilot app) but the
  acceptance grep `def _turn\b` catches it. A mechanical rename (behavior-preserving,
  not a move into pilot_helpers, which is Pilot-only) is the minimal way to satisfy
  the grep. All 15 call sites updated.
- **`_start_blocked_draft` left local in each of its 2 files** (not hoisted to
  pilot_helpers) — its spin loop now calls `wait_until`, but the helper itself is not
  a PRD-named deliverable; hoisting it is task-4-adjacent scope, skipped.
- Migration was scripted for the uniform `_two_turns`/`_turn` blocks (byte-identical),
  manual Edits for the nuanced spin loops. `ruff check --fix tests/` dropped the
  now-unused `InputBar` imports (36 fixes) and normalized `Callable` import.

No new tests (behavior-preserving refactor; floor is same-tests-collected-and-pass,
met at 705). No qa-tester / visual check — test-only change, no runtime surface;
green gate IS the verification.

## 2026-07-11 — Task 4: compress-via-editor choreography in tests/pilot_helpers.py

Added three helpers to `tests/pilot_helpers.py`: `open_editor_on_range(pilot, *,
downs=3)` (form B: escape → home → `v` + downs×down → `c`), `compress_range(app,
pilot, summary, *, downs=3)` (form A = form B + set `#compress-output` + `ctrl+s`;
delegates to `open_editor_on_range`), and `select_tip_in_edit(app, pilot)` (the
mode-guarded double-Esc). Removed the four hand-copied helpers across their files
and migrated the inlined copies. Acceptance grep for the four `def`s returns
nothing; collected count unchanged (705 → 705); gate green (ruff + mypy + 705
pytest, 30s). `tests/README.md` gained a "Shared Pilot scaffolding" section naming
both homes (conftest.py fixtures/doubles + pilot_helpers.py choreography) and the
BlockingProvider deadlock trap. This was the final PRD task.

Migration map (what moved where, for future audit):
- `_compress_full_tip_range` → `compress_range`: deep_dive, expand, compress_payload,
  deep_dive_hardening, new_resume_reset.
- `_open_editor_on_full_range` → `open_editor_on_range`: draft_worker_lifecycle,
  committed_k_inspector, new_resume_reset, draft_prompt_reset, draft_compression,
  commit_compression.
- `_select_k_in_edit`/`_select_tip_in_edit` → `select_tip_in_edit`: deep_dive,
  deep_dive_hardening, expand; plus the inline double-Esc in new_resume_reset's
  `_enter_deep_dive` and footer_context's `test_footer_advertises_expand...`.
- Inlined `open_editor_on_range(pilot)`: transient_hints (empty-summary test),
  commit_failures (streaming-refusal test).
- `downs=1` real callers: compression_editor's two 2-node `open_editor_on_range(pilot,
  downs=1)` opens, and drift/diff_view `_drift_scenario` → `compress_range(app, pilot,
  "SUMMARY", downs=1)`. This is what justifies the `downs` knob's existence (deletion
  test: without these callers `downs` would be speculative generality).

Decisions a future fresh iteration must know:
- **`compress_range` delegates to `open_editor_on_range`** — form A is literally form
  B + type summary + `ctrl+s`, so they share the `downs` knob and there is one copy of
  the escape/home/v/c sequence.
- **footer_context's compress block was left INLINE** (only its select-tip migrated).
  Its `home/v×3/c/settext/ctrl+s` block has NO leading `escape`: the test is already in
  Edit mode (from an earlier `escape` + assertions), so calling `compress_range` — which
  presses `escape` first — would toggle Edit→Insert and break it. Genuinely divergent
  mode-entry; not force-fit.
- **reconcile and range_selection got NO task-4 migration.** reconcile's only compress
  block is the trailing-range `home,down,down / v,down` the PRD explicitly says to leave
  alone. range_selection has no editor/compress choreography at all (pure `v`/`down`/`up`
  selection-extent tests, no `c` press); its turn choreography was already migrated in
  task 3. Both are in the PRD's file list but correctly resolve to no-op here.
- **Left alone (genuinely divergent):** diff_view's `_middle_compress_scenario`
  (non-tip range), `_two_region_drift_scenario` (per-region compress loop),
  `_double_compress_and_dive`; commit_failures' double-compress test (suffix via `v,up`,
  then a range containing a committed K); compression_editor's unanchored `escape/c`
  single-node opens (no home/v).
- `ruff check --fix tests/` dropped now-unused `TextArea` imports and fixed two E303
  blank-line issues after def removals; drift.py's `TextArea` was hand-removed
  (`Static` stays).

No new tests (behavior-preserving refactor; floor = same-tests-collected-and-pass,
met at 705). No qa-tester / visual check — test-only change, no runtime surface; the
green gate IS the verification (per PRD).
