# Ralph Progress Log

Append-only cross-iteration memory. Each fresh loop iteration reads the tail of
this file, then adds an entry describing what it did, key decisions, and any
gotcha the next iteration must know. Newest entries at the bottom.

Git history is the source of truth for *what changed*; this file captures the
*why* and the *watch-outs* that don't fit in a commit message.

---

<!-- Example entry:
## 2026-06-20 — Task: add /export command
- Added `export` handler to ConversationCore returning the rendered transcript.
- Decision: kept formatting in core (pure) so it's testable without the UI.
- Gotcha: HistoryScreen caches the conversation list; call `refresh_list()` after
  mutations or the new entry won't appear until reopen.
-->

## 2026-06-25 — Seed (pre-loop context, not a task)
- This PRD (`scripts/ralph/PRD.md`) comes from a code-reading triage recorded in
  `docs/decisions/0006`–`0014`. Every task cites its source note (e.g. "Ref:
  0014 #2"). **Read the referenced note before implementing** — it holds the *why*
  the one-line task can't.
- Cross-cutting intents to honor:
  - Failures should be *visible*, not silent (drives tasks 1 & 7).
  - The conversation's model is conversation state, not a global (task 2).
  - One source of truth for node construction/classification — **factory
    classmethods + predicates on the single `Node` dataclass, NOT subclasses**
    (tasks 4–5).
- Watch-outs: `core/` stays framework-free (zero `textual` imports); `StoragePort`
  has a second implementation, `SaveCountingStorage` in `tests/test_conversation.py`,
  that must be updated in lockstep with any interface change; the agent/QA tooling
  now lives at `tools/agent/` (outside the shipped `ctx` package).

## 2026-06-26 — Task: Harden build_context against bad/empty nodes (refs 0007 #1, #2)
- `ctx/core/context.py`: a context node whose `load_file` raises `OSError`/`ValueError`
  no longer `continue`s silently — it emits a visible `<context_import source="…"
  error="…"></context_import>` block as user material (flows through the normal
  user-merge). Empty `user`/`assistant` nodes (`content == ""`) are now skipped so no
  empty-content message reaches the provider. Missing/empty `source_path` still drops
  (nothing to import).
- Tests: added code-blind `tests/test_context_failures.py` (test-spec-author) for the
  two new behaviors — the acceptance floor. **Deliberately corrected** three existing
  tests in `tests/test_context.py` (C14/C15/C20) that encoded the OLD silent-drop
  behavior the PRD explicitly reverses; their expectations now match the visible-marker
  contract (justified change, not test-fudging — expected behavior comes from the PRD,
  not the impl). Updated `tests/specs/context.md`: rewrote C14/C15/C20, added C23
  (empty-node skip).
- Verification: `bash scripts/check.sh` green (263 passed). Pure core logic — no
  qa-tester run (no UI/runtime behavior change; the adapter calls build_context
  unchanged).
- Gotcha for next iteration: the mutmut figures in `tests/specs/context.md` are now
  marked STALE (the load-failure branch changed shape, empty-skip branches are new) —
  re-run mutmut on context.py in a future pass if you touch it.

## 2026-06-26 — Task: Persist & restore the conversation's model (ref 0014 #2)
- `ctx/core/storage.py`: added a `model` column to the `conversations` table. New DBs
  get it from `_SCHEMA`; pre-existing DBs are migrated in `init()` via a new `_migrate`
  helper that checks `PRAGMA table_info(conversations)` and `ALTER TABLE … ADD COLUMN
  model TEXT NOT NULL DEFAULT ''` only when absent (SQLite has no ADD COLUMN IF NOT
  EXISTS). `save` now writes model on both INSERT and UPDATE; new read method
  `get_model(conversation_id) -> str | None` (None when no row).
- **Interface decision:** `save` gained `model` as a **keyword-only arg with default ""**
  (`save(cid, title, nodes, *, model="")`) rather than a 4th positional. This keeps the
  ~40 existing positional `repo.save(id, title, nodes)` call sites in `test_storage.py`
  valid (no churn) and reads as "model is optional metadata with a safe default". A
  future iteration touching this can promote it if a real second caller needs it.
- `ctx/core/conversation.py`: `persist()` passes `model=self.model`; `resume_conversation`
  reads `get_model(conv_id)` and restores `self.model` **only when non-empty** — a
  pre-migration row (model "") must NOT clobber the resumer's current/default model.
- Updated the `SaveCountingStorage` double in `tests/test_conversation.py` (new `model`
  kwarg on `save`, new `get_model` passthrough) — required or the StoragePort second impl
  goes red.
- Tests: code-blind `test-spec-author` wrote `tests/specs/model-persistence.md` (MP1–MP10)
  + `tests/test_model_persistence.py` for the round-trip + backward-compat (empty model
  doesn't clobber) + get_model-None behaviors. I added 3 migration tests to
  `tests/test_storage.py` myself (legacy pre-model schema → init() adds column, preserves
  rows, idempotent) since constructing a legacy-schema DB needs raw-sqlite setup the blind
  author can't have.
- Verification: `bash scripts/check.sh` green (276 passed, was 263). qa-tester confirmed
  the UI round-trip: send msg → `/model test/distinct-model-xyz` → `/new` → `/resume` →
  footer shows the restored model, no errors.
- Gotcha: model only persists for a conversation that already has a persistable node
  (persist() is a no-op without a conversation_id). A bare `/model` before any message
  isn't saved — that's intended (nothing to attach it to). `/new` correctly resets to
  DEFAULT_MODEL.

## 2026-06-26 — Task: Source the default model from config.py (ref 0006 #3)
- `ctx/core/config.py`: added `DEFAULT_MODEL = "openrouter/google/gemma-4-26b-a4b-it"`
  constant and wired it as the top-level `_DEFAULTS["model"]` (the default model is
  now a user-overridable config key, alongside colors/ui). `_DEFAULTS` type annotation
  widened from `dict[str, dict]` to `dict` since it now holds a scalar value too.
  No special re-merge needed: a top-level scalar survives `merged.update(user_config)`
  and is overridden when the user sets `"model"`.
- `ctx/core/conversation.py`: removed the hardcoded `DEFAULT_MODEL` constant. `__init__`
  now reads the default ONCE via `get_config()["model"]` into `self._default_model`
  (no per-call file I/O — PRD requirement); both initial `self.model` and the `/new`
  reset in `new_conversation()` use `self._default_model`.
- `ctx/ui/app.py`: dropped the `DEFAULT_MODEL` import; the init log line now reads
  `self.core.model` (the resolved default). `get_config` was already imported.
- Tests: existing `DEFAULT_MODEL` import in `test_conversation.py` repointed to
  `ctx.core.config` (moved symbol; C21/C47 assertions unchanged, still green — no
  config file in CI so the default is unchanged). Added one focused test
  `test_default_model_sourced_from_config`: monkeypatches `config.CONFIG_PATH` to a
  temp config.json with a custom `"model"`, asserts a fresh core adopts it AND that
  `/new` resets to it. This earns its place — C21/C47 only compare against the default
  constant and would survive a mutation that hardcodes that same string; this test
  actually verifies config-sourcing. Chose a direct deliberate test over the blind
  test-spec-author: single observable assertion on an already-spec'd module, and the
  contract (config drives the default) is inherently behavioral, not impl-mirroring.
- Adjusted `tests/test_config.py` C3 (baseline shape) + `tests/specs/config.md` C3/A3:
  the defaults' top level is now exactly `{colors, ui, model}` (was `{colors, ui}`).
  Legitimate schema change driven by the task, not test-fudging — recorded here.
- Verification: `bash scripts/check.sh` green (277 passed, was 276). Pure core-logic
  task (acceptance is unit-only, no qa-tester line); production behavior unchanged
  (no config file → same default string), so no qa-tester run.
- Gotcha: `ConversationCore` now imports `ctx.core.config` — keep the core import
  graph acyclic (config.py has no ctx imports, so fine). A bare `/model` before any
  message still isn't persisted (unchanged from prior task).

## 2026-06-26 — Task: Add Node factory constructors and migrate ConversationCore (ref 0014 #1)
- `ctx/models/nodes.py`: added 4 classmethod factories on the `Node` dataclass —
  `Node.user(content, conversation_id)`, `Node.assistant(conversation_id, content="")`,
  `Node.system(content)`, `Node.context(source_path, conversation_id)`. Each encodes
  exactly one valid (role/node_type/content/meta/conversation_id) combination so call
  sites can't get the mix wrong. Added `from __future__ import annotations` so the
  classmethods can annotate their return type as `Node` (self-reference).
- **Load-bearing invariant:** `Node.system` deliberately carries NO `conversation_id`
  (empty default). This is what keeps system breadcrumbs out of persistence (storage
  filters nodes without a conversation_id). Documented in the docstring + AGENTS map.
  user/assistant/context all carry the conversation_id so they persist.
- `ctx/core/conversation.py`: migrated all 8 `Node(...)` constructions to the factories
  (submit user+assistant, set_model, check_connectivity ok+fail, new_conversation,
  include_files, add_system_message). Pure behavior-preserving refactor — identical field
  tuples. No other `Node(...)` construction exists in ctx/ except storage.py's
  deserialization (out of scope — it rebuilds from stored columns, not a "kind" factory).
- `AGENTS.md`: updated the models/ architecture line to document the factories + the
  no-conversation_id-on-system invariant (interface change → map must stay current).
- Tests: code-blind `test-spec-author` wrote `tests/specs/nodes.md` (N1–N10) +
  `tests/test_nodes.py` — each factory's field tuple (PRD acceptance floor), the
  system empty-conversation_id invariant, context's "Included: <path>" content +
  meta["source_path"], assistant default-empty vs explicit content, unique ids, and
  no mutable-default meta aliasing across calls. Red on NotImplementedError (clean
  collection) → green after impl.
- Verification: `bash scripts/check.sh` green (287 passed, was 277; +10 node tests).
  Pure construction refactor with identical field combos verified by unit tests + the
  unchanged test_conversation.py suite — no UI/runtime behavior change, so no qa-tester.
- Gotcha: next task (goes_to_model predicate) depends on these factories per the PRD.

## 2026-06-26 — Task: Add `goes_to_model` predicate and route `build_context` through it (ref 0014 #1)
- `ctx/models/nodes.py`: added instance method `Node.goes_to_model() -> bool` returning
  `self.role in {"user", "assistant"} or self.node_type == "context"`. This is now the
  single definition of "which nodes reach the LLM" — the derived classifier ADR 0014 #1
  calls for, alongside the existing factory constructors.
- `ctx/core/context.py`: routed the inclusion decision through it — added
  `if not node.goes_to_model(): continue` at the top of the loop. Previously system/other
  nodes were dropped *implicitly* (they fell through both the user and assistant branches);
  now the skip is explicit and single-sourced. Behavior-preserving: the predicate is True
  for exactly the kinds the old fall-through let through (context handled, user/assistant
  appended) and False for system — so the produced messages are identical. The empty-content
  skip (`content == ""`) stays separate inside the branches (kind vs. content are orthogonal).
- `AGENTS.md`: documented the predicate in the models/ line (interface addition → map stays current).
- Tests: code-blind `test-spec-author` wrote `tests/specs/nodes-goes-to-model.md` (G1–G9) +
  `tests/test_goes_to_model.py` — the PRD truth table (user/assistant/context → True, system →
  False) plus edge cases: unrecognized role → False, context recognized via node_type even with
  a non-chat role (literal-OR semantics), chat role wins regardless of node_type, empty/default
  node → False, and return is a real `bool`. Red on NotImplementedError (clean collection) →
  green after the one-line impl.
- Note on disjunctive semantics (test-spec-author flagged A1): the predicate is a literal OR,
  so `node_type == "context"` alone (G6) and a chat role alone (G7) each independently return
  True. The factories never construct such mixed nodes, but the predicate is intentionally
  permissive (matches the PRD wording "role in {...} OR node_type == context").
- Verification: `bash scripts/check.sh` green (296 passed, was 287; +9 predicate tests). Pure
  core-logic task, produced messages unchanged (verified by the unchanged test_context.py suite),
  so no UI/runtime change → no qa-tester run.
- Gotcha: the build_context docstring already said "other roles (e.g. system) are skipped" — still
  accurate, left as-is. Next PRD task (uniform persistence) is independent of this predicate.

## 2026-06-26 — Task: Make persistence uniform across all commands (ref 0006 #6)
- `ctx/models/nodes.py`: `Node.system` gained an optional `conversation_id: str = ""`
  (consistent with the user/assistant/context factories — ownership is orthogonal to
  kind). Default "" preserves the transient case. **Reverses the prior task's
  "system carries no conversation_id" invariant** — that was load-bearing only because
  breadcrumbs weren't meant to persist; this task makes them persist when raised inside
  a conversation. N4 in test_nodes.py still valid (tests the no-arg default → "").
- `ctx/core/conversation.py`: `set_model`, `check_connectivity`, `add_system_message`
  now build their breadcrumb with `self.conversation_id` and call `persist()`
  (check_connectivity & add_system_message previously didn't persist at all). Added a
  class-docstring statement of the uniform policy. `new_conversation` left as-is — it
  already persists the old conversation, and its returned "Started a new conversation"
  notice legitimately belongs to no conversation (id reset to "").
- The rule: a breadcrumb persists iff raised inside an active conversation; with no
  conversation the id is "" and `persist()` no-ops / storage filters it. So `/model`
  before any message is still not persisted (unchanged).
- Tests: code-blind `test-spec-author` wrote `tests/specs/command-persistence.md`
  (CP1–CP11) + `tests/test_command_persistence.py` — each command persists its
  breadcrumb under an active conversation (acceptance floor), the no-conversation
  transient case, the Node.system durability seam, and no-displacement of real turns.
  Fixed the two flagged import lines (`ctx.core.conversation` / `ctx.models.nodes`).
  Red on the 6 persistence cases (clean collection) → green after impl.
- **Deliberate test changes (old contract reversed, documented):** deleted stale
  tests C15 (`set_model_notice_is_transient_and_unpersisted`), C19
  (`check_connectivity_notice_is_transient`), C34 (`add_system_message_does_not_persist`)
  — superseded by CP1/CP3/CP4/CP5. Narrowed C35 to the no-conversation case
  (`..._without_conversation`). Repurposed C45 (`test_persist_excludes_idless_notices`)
  to the surviving invariant: the storage filter is keyed on conversation_id, not
  system-ness — an id-less breadcrumb is dropped even while real turns persist. Updated
  the corresponding entries in `tests/specs/conversation.md`.
- Docs: `AGENTS.md` models/ line + `storage.py` save comment updated to match.
- Verification: `bash scripts/check.sh` green (304 passed, was 296: +11 new CP, −3
  deleted, +0 net elsewhere). qa-tester verify-feature PASS — `/model
  anthropic/claude-3-opus` inside a conversation, `/new`, `/resume` → restored
  transcript contains the "Model set to: …" AND "✔ Connected to …" system breadcrumbs;
  header model also restored; no errors.
- Gotcha for next iteration: connectivity now fires its own breadcrumb persist after
  set_model's — switching model writes TWO system nodes (model + connectivity) that
  both survive resume (seen in qa snapshot). Intended. Remaining PRD tasks (provider
  timeout/ProviderError; decouple stream from node ordering) are independent of this.

## 2026-06-26 — Task: Give the provider a timeout and a domain error type (ref 0011 #1)
- `ctx/core/provider.py`: added `STREAM_TIMEOUT = 60.0` and a `ProviderError(Exception)`
  domain type. `LiteLLMProvider.stream` now wraps its body in try/except: passes
  `timeout=STREAM_TIMEOUT` to `acompletion`, and maps any `Exception` (request-time OR
  mid-stream) to `ProviderError(str(exc)) from exc`. `CancelledError`/`GeneratorExit`
  are BaseException, so they pass through unwrapped — cancellation still works.
- `ctx/core/conversation.py`: NO change. `stream` already does
  `except Exception: persist(); raise`, so `ProviderError` flows through unchanged
  (persist partial + re-raise same object). Verified by PE6.
- Why preserve `str(exc)` as the ProviderError message: the UI shows the exception
  text to the user, so keeping the message identical means no observable UI change →
  pure core-logic task, no qa-tester run (per loop rules).
- Tests: code-blind `test-spec-author` wrote `tests/specs/provider-errors.md` (PE1–PE6)
  + `tests/test_provider_errors.py` — request-time wrap (PE1), mid-stream wrap preserving
  prior tokens (PE2), timeout positive/finite + handed to backend (PE3), happy-path
  transparency (PE4), CancelledError not wrapped (PE5), ProviderError flows through
  ConversationCore.stream with partial persisted (PE6, the acceptance floor). Red on
  PE1/PE2/PE3 (clean collection) → green after impl. PE4/PE5/PE6 were already green
  (the except-Exception path + happy path pre-existed).
- **Deliberate test fix (author was blind to accessor):** PE6 used `conversation.nodes`
  on the result of `repo.load()`, but `ConversationRepository.load` returns a `list[Node]`
  directly. Corrected to `[n.content for n in loaded if n.role == "assistant"]`. Intent
  unchanged (assert partial assistant content persisted).
- Docs: `AGENTS.md` provider.py line updated (interface gained ProviderError + timeout).
- Verification: `bash scripts/check.sh` green (311 passed, was 304: +7 new PE tests).
- Gotcha: wrapping the whole stream body means a malformed-chunk `IndexError`/`AttributeError`
  (ADR 0011's chunk-shape concern) is now also surfaced as ProviderError — acceptable,
  arguably better. Remaining PRD task (decouple stream from node ordering, 0006 #1) is
  the last one and is independent of this.

## 2026-06-26 — Task: Decouple stream() from node ordering (ref 0006 #1)
- `ctx/core/conversation.py`: `stream` now builds context from
  `[n for n in self.nodes if n is not assistant_node]` instead of the positional
  `self.nodes[:-1]`. The streamed node is excluded by IDENTITY, not by being last —
  same messages in the normal submit→stream flow, but no implicit ordering contract.
- Behavior-preserving for the real call sequence (submit appends the assistant node
  last), so no UI/runtime change → no qa-tester run (per loop rules; pure core logic).
- Test: added `test_stream_excludes_streamed_node_by_identity` (C-series) directly in
  `tests/test_conversation.py` — not via the code-blind subagent, because the public
  interface of `stream` is unchanged and this asserts one new internal invariant. It
  gives the assistant node sentinel content AND appends a later user node so the
  assistant is no longer last; asserts the sentinel is NOT sent while the later node
  IS. Verified RED against the reverted `[:-1]` slice (both asserts fail) and GREEN
  with identity exclusion — the test discriminates the exact mutation.
- Verification: `bash scripts/check.sh` green (312 passed, was 311: +1 new test).
- This was the final unchecked PRD task — all tasks now `- [x]`.

## 2026-06-26 — Seed (round-2 cleanups PRD, not a task)
- PRD-1 (core hardening) is complete (entries above). `scripts/ralph/PRD.md` was
  replaced with **round-2 cleanups**: harden `list_files` (bounded text-sniff +
  traversal guard, refs 0008 #1/#2), extract a `_derive_title` helper (0006 #5),
  annotate two stale ADRs (0013 #1, 0014 #3).
- The bounded-sniff design is fully specified in `docs/decisions/0008` (the
  **Decision** block): first ~8 KB, reject on NUL byte or non-UTF-8, tolerant
  boundary decode, **no extension allowlist**. Caching the verdict is deliberately
  out of scope (deferred until the KB widens to the whole launch dir).
- Reminders: ADRs are immutable — task 3 *annotates*, never rewrites. Task 2 is a
  pure refactor — lean on existing green, don't add trivial tests. Reuse
  `read_file`'s existing `resolve()`/`is_relative_to` guard for the traversal half of
  task 1.

## 2026-06-26 — Task: Harden list_files — bounded text-sniff + traversal guard (ref 0008 #1/#2)
- `ctx/core/workspace.py`: replaced the full-file `read_text` validation in `list_files`
  with a **bounded sniff**. Added module-level `SNIFF_BYTES = 8192` and pure helper
  `_sniff_is_text(chunk: bytes) -> bool`: rejects on a NUL byte, else decodes with an
  incremental UTF-8 decoder (`codecs.getincrementaldecoder("utf-8")`, `final=False`) so a
  multi-byte char split at the 8 KB boundary is NOT a false negative. No extension
  allowlist — extensionless dev files pass. `list_files` now reads only the first 8 KB
  (`path.open("rb").read(SNIFF_BYTES)`).
- Also added the **containment guard** mirroring `read_file`: compute `context_root =
  self._context.resolve()` once, and skip any path whose `path.resolve()` is not
  `is_relative_to(context_root)`. So a symlink under context/ that escapes the sandbox is
  never listed → picker and reader agree by construction (closes 0008 #2 disagreement).
- Log messages preserved/split: out-of-bounds → "skipped out-of-bounds context file";
  OSError on open → "unreadable context file" (keeps C26 green); non-text → "skipped
  non-text context file" (keeps C15/C16 green).
- Tests: 4 new acceptance tests in `tests/test_workspace.py` (the PRD floor (a)–(d)).
  Written directly, NOT via code-blind subagent, because `list_files`' public signature
  is unchanged — these pin refined behavior of an existing method. (c) proves bounded
  reading without a spy: a >8 KB file clean for its prefix but with a NUL byte past the
  window is still listed (whole-file validation would skip it). Added a traceability
  addendum to `tests/specs/workspace.md` (the named tests, not new C-items).
- Pure core-logic task: list_files' observable output (the picker's file set) is fully
  covered by the unit tests through the public interface → no qa-tester run (per loop rules).
- Docs: updated AGENTS.md workspace.py line with the sniff + containment-guard invariant.
- Verification: `bash scripts/check.sh` green (316 passed, was 312: +4 new tests).
- Gotcha for next iter: remaining PRD tasks are 2 (extract `_derive_title` — pure refactor,
  NO new tests) and 3 (annotate two stale ADRs — docs-only, ADRs are immutable, append a
  **Correction:** pointer, never rewrite the Decision/Consequences body).

## 2026-06-26 — Task: Extract a `_derive_title` helper (ref 0006 #5)
- `ctx/core/conversation.py`: added module-level pure helper
  `_derive_title(content: str) -> str` returning
  `content[:MAX_TITLE_LENGTH].replace("\n", " ")`. Replaced the two duplicated
  inline copies — in `_ensure_conversation` (first-message title) and
  `resume_conversation` (first user node's content) — with calls to it. Single
  source of truth, so the two sites can't drift (closes 0006 #5).
- Pure refactor, no behavior change → NO new tests (per PRD task 2 / PROMPT.md
  test-strategy rule). Existing `tests/test_conversation.py` title tests are the
  red/green: suite stayed green at 316 before and after (count unchanged).
- No UI/runtime change → no qa-tester run (pure core logic).
- Verification: `bash scripts/check.sh` green (ruff + mypy + 316 passed).
- Gotcha for next iter: only PRD task 3 remains (annotate two stale ADRs —
  docs-only; ADRs are IMMUTABLE, append a one-line **Correction:** pointer to the
  observation note, never rewrite the Decision/Consequences body). Targets:
  0003 (`:memory:` claim → point to 0013) and 0004 ("no side effects" → 0014 #3).

## 2026-06-26 — Task: Annotate the two stale ADRs with a correction pointer (refs 0013 #1, 0014 #3)
- Docs-only. ADRs are immutable (`docs/decisions/README.md`: "supersede, don't
  rewrite") so I **appended** a clearly-marked `**Correction:**` block to each,
  after a `---` rule, leaving the Decision/Consequences text untouched:
  - `0003-conversation-repository.md`: the `:memory:` "supports tests" claim is
    stale under connection-per-method → points to `0013`.
  - `0004-pure-context-builder.md`: the "no side effects" claim is overstated
    (`build_context` logs) → points to `0014 #3`.
- No new tests warranted (docs-only, no behavior change); no qa-tester (no
  UI/runtime change).
- Verification: `bash scripts/check.sh` green (ruff + mypy + 316 passed, unchanged).
- This was the **last unchecked task** in `scripts/ralph/PRD.md` (round-2 cleanups).
  All three tasks now `- [x]`. PRD complete.

## 2026-06-30 — Task 1: core/tokens.py deep module + code-blind contract tests (Sprint 1)
- Seeded the new Sprint 1 PRD (token accounting & context budget) in a separate
  `docs:` commit first (the working tree carried the uncommitted replacement), then
  did Task 1.
- New framework-free module `ctx/core/tokens.py` (zero textual, no Protocol seam —
  single impl). Public surface: `count_messages` (sole home of litellm
  `token_counter`/tiktoken fallback; empty list → 0), `per_node_tokens` (renders each
  node in isolation via `build_context([node], read_file)` then counts — so a context
  node counts its resolved file body, a non-goes_to_model node → 0), `weight_pct`
  (`"context"`/`"window"` basis; provider-agnostic ratio, **no calibration arg**;
  0-token nodes → `None`; empty/0 denominator → all `None`, no ZeroDivision),
  `gauge(local_total, max_input_tokens, calibration)` → `(pct, approximate)`
  (`approximate = calibration is None`; pct **unclamped**, can exceed 100; unknown
  window → `(None, ...)`), `model_window` (wraps `get_model_info`, unknown model →
  `None` via broad `except Exception`, never raises).
- Code-blind flow per PROMPT.md step 4: wrote signatures+docstrings+`NotImplementedError`
  stubs, confirmed clean collection, spawned `test-spec-author` with ONLY the interface
  + prose intent. It produced `tests/specs/tokens.md` (C1–C25) + `tests/test_tokens.py`
  (25 tests). Verified RED (25 fail on NotImplementedError, collect clean), implemented
  to GREEN. Did NOT touch the authored tests.
- Decisions baked into the docstrings the blind author saw: 0-token node → `None` (not
  0) in `weight_pct` so the UI shows `--%`; gauge pct unclamped (>100 means over budget
  is meaningful); `approximate` keys purely off `calibration is None` (staleness is the
  UI layer's concern in Task 6, not this module's).
- Pure core-logic task, no UI/runtime change → NO qa-tester run (per loop rules); the
  code-blind tests + gate are the verification.
- Docs: added `tokens.py` to the AGENTS.md core/ architecture map.
- Verification: `bash scripts/check.sh` green (ruff + mypy + 347 passed; +25 new + the
  litellm import path is exercised by the real `gpt-4` model in tests).
- Gotcha for next iter: Task 2 (`ui.weight_basis` config flag) is next — pure config,
  extend `tests/test_config.py` + `tests/specs/config.md`. Tasks 1+2 are the deps for
  Task 3 (first Pilot test). `tokens.weight_pct` deliberately takes no calibration arg
  — calibration only ever touches `gauge`'s absolutes (Task 5/6).

## 2026-06-30 — Task 2: `ui.weight_basis` config flag
- Added `"weight_basis": "context"` under the `"ui"` section of `_DEFAULTS` in
  `ctx/core/config.py` (legal values `"context"`/`"window"`), plus a module-level
  `_WEIGHT_BASES` tuple. In `get_config()`, after the existing depth-2 `ui` merge,
  coerce an out-of-domain value back to the default:
  `if merged["ui"].get(...) not in _WEIGHT_BASES: -> "context"`. Placed AFTER the
  `ui` merge (covers both the valid-`ui`-dict branch and the fallback branch) and
  before `return`. `["context"]` (list) works with `in` on a tuple — `==` compare,
  no hashing — so a list value coerces cleanly, no TypeError.
- Code-blind flow (PROMPT.md step 4): the signature `get_config() -> dict` is
  unchanged, so the natural RED is the missing key (KeyError) rather than a stub.
  Spawned `test-spec-author` with ONLY the intent + the `get_config` docstring +
  the existing fixture conventions (`config_file`, `_baseline`); it produced C21
  (default "context"), C22 ("window" preserved), C23 (parametrized over
  "banana"/42/None/["context"] → coerced to "context", no raise, sibling
  `truncation_lines` untouched). Merged its tests into `tests/test_config.py` and
  its contract items into `tests/specs/config.md` (deleted the temp addendum +
  temp test file). Verified RED first (C21 KeyError, C23 fails on uncoerced value;
  C22 already green since the merge preserves a legal value), then GREEN.
- Pure core-config task, no UI/runtime change → NO qa-tester (per loop rules).
- Verification: `bash scripts/check.sh` green (ruff + mypy + 353 passed; +6 new).
- Gotcha for next iter: Task 3 (UI per-node weight %) is next and is the FIRST
  Pilot test (`App.run_test()`) in the repo — no Pilot infra exists yet. It reads
  `get_config()["ui"]["weight_basis"]` (now available) and needs a `read_file`
  accessor on `ConversationCore` (the same loader injected into `build_context`)
  exposed without breaking core's framework-free rule. Mandatory floor is the
  Pilot test asserting numeric `weight_pct` in `describe_state()`; qa-tester is
  confirmation and may lag one iteration (in-process cache).

## 2026-06-30 — Task 3: UI per-node weight %
- Wired the already-contract-tested `tokens.weight_pct` into the UI. Three edits:
  (1) `ctx/core/conversation.py`: added a `read_file` property returning
  `self._workspace.read_file` — the exact loader injected into `build_context` —
  so the UI renders nodes for counting the same way the model sees them without
  reaching past the core (keeps core framework-free). (2) `ctx/ui/app.py`: imported
  `from ctx.core import tokens`; added `_node_weights()` (single computation:
  `tokens.weight_pct(nodes, model, core.read_file, get_config()["ui"]["weight_basis"],
  tokens.model_window(model))`) read by BOTH `describe_state` (replaces the
  hardcoded `weight_pct: None` with `weights[i]`) and a new `_refresh_weights()`
  that pushes `set_weight_pct(...)` onto mounted `MessageWidget`s. (3) Invoked
  `_refresh_weights()` after every node-list/content change: `submit`,
  stream-complete (`on_worker_state_changed` SUCCESS/CANCELLED/ERROR),
  `/include`, `/resume`, `/new`.
- Design note: PRD listed only submit/include/resume/new for the refresh, assigning
  stream-complete to Task 6's gauge. But the assistant node is EMPTY at submit and
  only gets content when the stream finishes — so its weight (and the context-basis
  redistribution across siblings) only becomes real at stream-complete. Added the
  refresh there too; it's squarely Task 3's per-node-weight concern, not Task 6
  scaffolding. `describe_state` recomputes live regardless, so snapshots are always
  correct; the widget refresh is purely for the rendered `--%` slots.
- Tests: NO test-spec-author. The only core change is a pass-through getter
  (`read_file`), explicitly excluded from new tests per PROMPT step 3; `tokens` is
  already contract-tested (Task 1). The new observable behavior is UI wiring, whose
  mandatory floor is a deterministic Pilot test. Wrote `tests/test_app_weights.py`
  (the FIRST `App.run_test()` test in the repo, 2 tests): (a) drives a user turn +
  canned assistant reply, asserts user & assistant nodes have `int` weight_pct and
  context-basis %s sum to ~100 (±2 for integer rounding); (b) raises a system
  breadcrumb via bare `/model` and asserts its weight_pct is `None`.
- Pilot-driving gotcha for future iters: drive turns by calling the real handler
  `await app.on_input_bar_submitted(InputBar.Submitted("..."))` directly, then
  `await app.workers.wait_for_complete()` to let the `@work stream_response` worker
  finish — deterministic, no keypress/message-pump timing. Do NOT press keys to
  type a command: bare `/model` via Enter appends a space for args
  (`COMMANDS_WITH_ARGS`) instead of submitting; posting/calling the Submitted handler
  bypasses that quirk. Also: import `TestProvider as CannedProvider` in test modules
  or pytest emits a `PytestCollectionWarning` (it tries to collect the `Test*` class).
- Verification: `bash scripts/check.sh` green (ruff + mypy + 355 passed; +2 new). NO
  qa-tester this iteration — the harness runs `ctx.*` in-process/cached so it can't
  see this iteration's edits (it'd test the stale hardcoded `None`); per PROMPT step 7
  limit (a) + the PRD's explicit allowance, the Pilot test is the floor and qa-tester
  confirmation lags. A later iteration (Task 7 e2e, or any fresh `claude -p`) should
  confirm numeric per-node %s in `ctx_snapshot` and redistribution after `/include`.
- Docs: updated AGENTS.md core map (conversation.py `read_file` accessor; app.py
  per-node weight wiring via `_node_weights`/`_refresh_weights`).
- Gotcha for next iter: Task 4 (Provider `on_usage` seam + `stream_options` +
  TestProvider usage) is next — introduces a real architectural decision (the
  `usage`-off-the-stream seam shape), so it MUST add an ADR in `docs/decisions/`.
  Keep the `test_provider` fixture green: TestProvider's new `usage` arg defaults to
  `None`.

## 2026-06-30 — Task 4: Provider `on_usage` seam + `stream_options` + TestProvider usage
- Added an out-of-band usage seam to `ctx/core/provider.py`: a frozen `Usage`
  dataclass (`prompt_tokens`, `completion_tokens`, `total_tokens`) and an optional
  `on_usage: Callable[[Usage], None] | None = None` on the `Provider` protocol and
  both impls. `stream` keeps yielding plain `str`; usage rides the callback.
  - `LiteLLMProvider`: now passes `stream_options={"include_usage": True}`, GUARDS the
    chunk loop with `if chunk.choices:` (the include_usage final chunk has empty
    `choices` — the old `chunk.choices[0]` `IndexError`'d on it, a real latent crash),
    and fires `on_usage(Usage(...))` once when `getattr(chunk, "usage", None)` is set.
  - `TestProvider.__init__(tokens, usage=None)`: stores the canned usage and, after
    yielding its tokens, calls `on_usage(self._usage)` only when both usage and the
    callback are non-None. Default `None` keeps the `test_provider` conftest fixture
    (and every existing `stream(messages, model)` caller) green — backward compatible.
- ADR: recorded `docs/decisions/0015-usage-off-the-stream.md` (Accepted) — callback
  chosen over a `str | StreamChunk` union (a union would tax every consumer on every
  chunk for an at-most-once value); provider-agnostic; documents the empty-choices
  latent-crash fix. Indexed in `docs/decisions/README.md`.
- Tests (code-blind, per PRD): spawned `test-spec-author` with ONLY the interface
  (signatures + docstrings) + prose intent + the documented litellm chunk seam. It
  authored contract items C10–C17 and the pytest tests; I merged them into
  `tests/test_provider.py` (+8 tests) and `tests/specs/provider.md`. Verified RED
  first against the stubs (4 failed: the on_usage-fires cases + the empty-choices
  crash; the "never fires"/"tokens still stream" cases passed even on stubs — exactly
  the right red/green split), then implemented to green. Authored tests treated as
  fixed — not edited to pass.
- Gotchas for future iters:
  - Blind author wrote a `_drain` helper that duplicates the existing `_collect`;
    kept it as-authored (harmless, don't rewrite blind tests). Its scratch deliverables
    `tests/_task4_*.{py,md}` were merged then deleted.
  - In test_provider.py import `TestProvider as CannedProvider` (pytest would try to
    collect a bare `Test*` class otherwise) — ruff `--fix` split the import into two lines.
- Verification: `bash scripts/check.sh` green (ruff + mypy + 363 passed; +8 new). Pure
  core-logic seam (no UI/runtime change) → NO qa-tester per PROMPT step 7 (the contract
  tests + gate are the verification).
- Next: Task 5 (`conversation.py` calibration) wires this seam — `ConversationCore.stream`
  computes the local sum (`tokens.count_messages`) and passes an `on_usage` that
  sanity-checks usage and stores `last_usage` + `calibration = prompt_tokens / local_sum`.
  The extended `test_provider` fixture path: construct `TestProvider(tokens, usage=...)`
  directly (the conftest factory still builds usage-less providers).

## 2026-06-30 — Task 5: `conversation.py` calibration (wires the on_usage seam)
- `ConversationCore.stream` now anchors the header gauge: it measures the local
  token sum of the exact context it sends (`tokens.count_messages(messages, model)`)
  and hands the provider an `on_usage` callback. A reported `Usage` is adopted only
  if SANE — `prompt_tokens > 0`, `local_sum > 0`, and the ratio within
  `CALIBRATION_TOLERANCE` (= 10.0) either way. Sane → set `last_usage` +
  `calibration = prompt_tokens / local_sum`; bogus/usage-less → leave both unchanged
  (so a trusted anchor survives a later bad turn). Logic lives in a private
  `_calibrate(local_sum, usage)` helper. Added read-only `last_usage` (`Usage | None`)
  and `calibration` (`float | None`) properties, both `None` until a sane turn.
  `stream` still yields plain `str` — the app is untouched (Task 6 reads the accessors).
- Code-blind flow (changed core behavior): wrote interface stubs (the two properties
  returning None-backed attrs, `stream` left unwired) → spawned `test-spec-author` with
  ONLY the interface + prose intent (PRD + ADR 0015) → it authored contract C58–C65 and
  the pytest tests. Verified RED first: 4/8 failed (the calibration-must-be-SET cases:
  C58 sane, C59 ratio invariant, C64 survives-no-usage, C65 survives-bogus), 4/8 passed
  on the stub (C60 no-usage, C61 zero, C62 out-of-range, C63 fresh — all expect None,
  which the stub gives) — the correct red/green split, clean collection. Then
  implemented to green. Authored tests treated as fixed.
- The ratio-invariant test (C59) pins the formula `prompt_tokens / local_sum` WITHOUT
  hardcoding a tokenizer count: two identically-built cores measure the same context,
  so `local_sum` cancels and `calib_a / calib_b == pa / pb`. Clever and robust.
- New conftest fixtures (the blind author needed them; legitimate reusable test infra):
  `repo_factory`/`workspace_factory` (independent DB/workspace per call — C59 needs two
  unrelated cores) and `varying_provider` (a `_VaryingProvider` whose per-turn tokens +
  usage vary by call count — C64/C65 drive sane-then-bad on ONE core). Also extended the
  `test_provider` factory to accept optional `usage` (backward-compatible default `None`).
- GOTCHA (bit me, will bite future iters): `ConversationCore.stream` now calls
  `provider.stream(messages, model, on_usage)` with THREE args. Every in-file provider
  DOUBLE in the test suite had `stream(self, messages, model)` and `TypeError`'d. Fixed
  all of them to `stream(self, messages, model, on_usage=None)`: 5 doubles in
  `test_conversation.py` + `_FailingProvider` in `test_provider_errors.py`. If you add a
  new provider double anywhere, give it the `on_usage=None` param.
- Verification: `bash scripts/check.sh` green (ruff + mypy + 371 passed; +8 new). Pure
  core-logic seam (no UI/runtime change) → NO qa-tester per PROMPT step 7.
- Docs: updated AGENTS.md core map (conversation.py calibration/last_usage accessors).
- Next: Task 6 (UI header gauge + `~` marker) reads `self.core.calibration` and feeds
  `tokens.gauge(local_total, model_window, calibration)`; `~` rides the absolute gauge
  only (no calibration yet OR node set changed since last usage = stale). Per-node % never
  shows `~`. Needs `AppHeader.set_context_pct`/`_gauge` extended to take `approximate: bool`.

## 2026-06-30 — Task 6: UI header gauge + `~` marker (reads core calibration)
- `ctx/ui/widgets/app_header.py`: `set_context_pct`/`_gauge` now take
  `approximate: bool = False` (backward-compatible) and render a leading `~` on a
  numeric pct when true. Deliberate call: `~` rides only a real number — `--%`
  (unknown window) stays bare since there is no figure to qualify. `compose()`'s
  `self._gauge(None)` placeholder still works via the default.
- `ctx/ui/app.py`:
  - `describe_state()` emits a `context_gauge` `{pct, approximate}` from new
    `_gauge_state()` = `tokens.gauge(count_messages(build_context(full nodes)),
    model_window, core.calibration)`. Uses `count_messages` of the FULL context
    (not summed `per_node_tokens`) so `local_total` shares the core's calibration
    basis (`count_messages` of the sent context) → `local_total × calibration`
    tracks the provider's count right after a turn.
  - Staleness (decision #5): `_node_signature()` = `tuple((id, len(content)) …)`;
    `_gauge_anchor` is captured in `_stream_response` ONLY when that turn produced a
    fresh `usage` (`core.last_usage is not usage_before`) — i.e. a turn with no
    provider usage does NOT re-bless the gauge. `_gauge_state` ORs `approximate`
    (calibration is None) with `signature != anchor`, so the gauge wears `~` before
    any anchor AND again once the node set drifts (a `/include` before the next turn).
  - Renamed `_refresh_weights` → `_refresh_token_ui` (only app.py referenced it) and
    folded the gauge push into it — the per-node %s and the header gauge always
    refresh together after a node-list/content change, so one method, one call site
    set (submit/new/resume/include/stream-complete).
- Tests (UI/integration, NOT code-blind — PRD designates the Pilot test as Task 6's
  floor, not a core contract): new `tests/test_app_gauge.py` (+3):
  (1) unit test on `AppHeader._gauge` pinning the `~`-only-when-numeric marker;
  (2) Pilot test: `approximate` True before any usage → False after a streamed turn
  with sane canned `usage` → True again (stale) after `core.include_files`;
  (3) Pilot test: an unknown model degrades to `pct=None`/approximate, no crash.
  Canned `Usage(prompt_tokens=12,…)` is within ~10× of a short message's local sum so
  the core's sanity check accepts it (calibration set).
- Verification: `bash scripts/check.sh` green (ruff + mypy + 374 passed; +3 new).
  Per PROMPT step 7 (a) + PRD note: NO qa-tester this iteration — the in-process
  harness caches `ctx.*` and can't see this edit; the Pilot test is the floor.
  Task 7 is the dedicated qa-tester e2e pass (it will read the gauge via
  `textual_query` on `#hdr-context`, which holds `~12% [== …]`).
- Docs: updated AGENTS.md (AppHeader gauge no longer a placeholder; app.py gauge
  wiring + `_refresh_token_ui` rename + `context_gauge` field).
- Pre-existing uncommitted `scripts/ralph/loop.sh` (sentinel-on-own-line + all-checked
  guard) was NOT mine — left unstaged, not part of this commit.
- Next: Task 7 — end-to-end qa-tester verify-feature against `HarnessApp` (needs the
  harness's TestProvider wired with a canned `usage` so calibration is exercised;
  confirm gauge moves on `/include`, `~` clears after a turn and reappears stale).
  Task 7 makes no code changes — if it finds a defect, file a new `- [ ]` and stop.

## 2026-06-30 — Task 7: End-to-end qa-tester verify-feature (token accounting)
- Wired the QA harness's `TestProvider` with a canned `usage` so the gauge
  calibration path is exercised headlessly: `tools/agent/harness.py` now imports
  `Usage` and constructs `TestProvider(CANNED_RESPONSE, usage=CANNED_USAGE)` where
  `CANNED_USAGE = Usage(prompt_tokens=20, completion_tokens=6, total_tokens=26)`.
  `prompt_tokens=20` stays within the core's `CALIBRATION_TOLERANCE` (10×) of any
  short typed message's local estimate, so the first turn calibrates and the gauge
  sheds its `~`. This is QA-tooling setup (non-shipping, ADR 0012), not product code
  — the only edit this iteration; `scripts/check.sh` green (374 passed, unchanged).
- qa-tester (verify-feature, `tools.agent.harness:HarnessApp`) result: all observable
  PRODUCT logic PASS — numeric per-node `weight_pct` for model-bound nodes,
  `"context"`-basis %s ≈ 100 (50/50 → after `/include` 25/25/50, correct
  redistribution), system breadcrumb `weight_pct` null/0, `context_gauge.approximate`
  flips True→False after the calibrated turn and back to True (stale) after `/include`,
  `/new` returns to empty, no crashes, `textual_check_errors` clean throughout.
- Two qa-tester findings, BOTH analyzed against the code as harness artifacts, NOT
  product defects:
  * Finding A: the harness default model `openrouter/google/gemma-4-26b-a4b-it` has no
    `max_input_tokens` in litellm → `tokens.model_window` returns `None` → the header
    renders `--%` (no number to qualify, so no `~`). This is the DOCUMENTED, CORRECT
    unknown-window degradation; CP1 explicitly allows `--%`. The numeric-pct + `~`
    lifecycle is pinned by the deterministic Pilot test (`tests/test_app_gauge.py`, the
    PRD-designated floor) and spot-confirmed by qa-tester via `/model gpt-4o` → `~0%`.
    NOTE: "gauge moves up" on `/include` is sub-1% for a toy conversation against any
    real model window (rounds to 0%), so it is only checkable as the numeric
    `context_gauge.pct` field rising, never as a visibly filling bar — the Pilot test
    rightly asserts only the `approximate` flag, not pct movement.
  * Finding B (filed as new Task 8): `_stream_response` (`ctx/ui/app.py:684`) detects
    "fresh usage this turn" via `Usage` OBJECT IDENTITY (`is not usage_before`). Correct
    for `LiteLLMProvider` (fresh `Usage` per turn) but an undocumented `Provider`-seam
    invariant: the harness's module-level singleton `CANNED_USAGE` is reused every turn,
    so only turn 1 passes the identity check and `_gauge_anchor` never updates again →
    the `~` sticks permanently for turns 2+. Production unaffected; it's a fragile
    coupling + makes the harness unfaithful for MULTI-turn gauge QA. Does NOT affect the
    Task 7 checkpoint sequence (one turn before the `/include`), which is why CP2/CP3
    still verified correctly.
- Per PROMPT step + Task 7 mandate ("if it finds a defect, file a new `- [ ]` and stop;
  do not patch under a green-required commit"): filed Finding B as **Task 8** (harden
  the staleness anchor off object identity onto a turn-scoped core signal). Did NOT
  patch it under this commit.
- Decision: marked Task 7 done. Its verification intent is met — the feature is
  confirmed correct (observable logic PASS + deterministic Pilot floor + gpt-4o
  spot-check). The CP2/CP3 "PARTIAL" marks were the realistic-default-model `--%`
  (correct behavior), not failures.
- GOTCHA for the Task 8 iteration: do NOT switch to value-equality (`!=`) for the
  anchor — two consecutive turns with identical token counts would then falsely read
  as "no fresh usage." Use a monotonic usage-generation counter or a per-turn flag set
  in `_calibrate`, kept framework-free on `ConversationCore`. Also: the in-process MCP
  harness caches `ctx.*`, but it DID pick up this iteration's `harness.py` edit (the
  qa-tester saw calibration fire), so a fresh `textual_launch` reloads the harness
  module — the staleness caveat is about `ctx.*`, not a same-session edit to harness.py
  before first launch.

## 2026-06-30 — Task 8: Gauge staleness anchor off Usage object identity
- Root cause (Task 7 Finding B): `_stream_response` (`ctx/ui/app.py`) detected
  "fresh provider anchor this turn" via `self.core.last_usage is not usage_before`
  — `Usage` OBJECT IDENTITY. Correct for `LiteLLMProvider` (new `Usage` per chunk)
  but an undocumented `Provider`-seam invariant. A provider reusing one `Usage`
  object (harness `CANNED_USAGE` singleton) → only turn 1 trips the check, anchor
  never updates, `~` sticks for turns 2+.
- Fix: `ConversationCore` now owns a private monotonic `_usage_generation` (int),
  bumped inside `_calibrate` ONLY when a usage is adopted (after the sanity check
  passes — so no-usage and bogus-usage turns do NOT bump). Exposed read-only as
  `usage_generation`. `_stream_response` samples `usage_generation` before/after the
  turn (`gen_before`) and updates `_gauge_anchor` when it changed. Core stays
  framework-free; no new seam. Identity- AND value-independent — per the prior
  iteration's GOTCHA, value-equality (`!=`) was the wrong fix (two consecutive turns
  with identical token counts would falsely read as "no fresh usage").
- ADR: recorded as Amendment #2 in `docs/decisions/0015-usage-off-the-stream.md`.
  Updated AGENTS.md (conversation.py + app.py `_gauge_anchor` notes).
- Tests added (2):
  * `tests/test_app_gauge.py::test_gauge_clears_tilde_on_second_turn_with_reused_usage_object`
    — the PRD acceptance FLOOR. Pilot test: `CannedProvider(usage=_SANE_USAGE)` reuses
    one `Usage` object; two consecutive turns → `context_gauge.approximate` is `False`
    after the SECOND turn. Fails under the old identity check (stayed `True`), passes now.
  * `tests/test_conversation.py::C66 test_usage_generation_bumps_only_on_adoption`
    — pins increment semantics the Pilot test can't (it only drives sane turns):
    fresh core = 0; sane turn → 1; no-usage turn stays 1; bogus-usage turn stays 1;
    a 4th turn feeding the SAME `fed` object as turn 1 → 2 (identity must not matter).
    Catches the mutation "bump unconditionally / on every turn".
- `scripts/check.sh` green (376 passed, was 374; +2). ruff + mypy clean.
- qa-tester NOT run this iteration: the in-process MCP harness caches `ctx.*` at
  session start, so it cannot see this iteration's `ctx/core/conversation.py` +
  `ctx/ui/app.py` edits — it would test STALE code and falsely reproduce the bug.
  The deterministic Pilot test is the PRD-designated floor and directly encodes the
  acceptance, so the fix IS verified. For belt-and-suspenders confirmation in a future
  fresh session (fresh server), run qa-tester verify-feature against
  `tools.agent.harness:HarnessApp` with `/model gpt-4o` (known window so a numeric % +
  `~` are visible): `~` before usage → cleared after EACH of two turns (the multi-turn
  lifecycle that was broken) → reappears stale after a following `/include`; no
  `textual_check_errors`. Harness already wires `CANNED_USAGE` (reused singleton), so
  it now faithfully exercises the multi-turn gauge.
- Pre-existing uncommitted `scripts/ralph/loop.sh` (not mine) left unstaged again.
- ALL PRD TASKS NOW CHECKED — Sprint 1 (token accounting & context budget) complete.

## 2026-07-03 — Task 1 (Sprint 3): compression node type + build_context rendering
- Added `Node.compression(summary, conversation_id, range_ids, prompt="")` factory
  (`ctx/models/nodes.py`): role/node_type both "compression", content=summary,
  meta={"prompt": prompt, "range": list(range_ids)} (canonical H1 keys; copies
  range_ids so callers can't alias the stored list). prev_id/compressed_into left None
  (off-line node; core adds it straight to `_graph` — task 3).
- Extended `goes_to_model()`: node_type in {"context","compression"} → True (H6).
- `build_context` (`ctx/core/context.py`) renders a compression node as user-role
  `<conversation_summary>\n{content}\n</conversation_summary>` (exact wrapper, NO
  preamble — Q2/Q2b), coalescing with adjacent user material like an import.
- BEHAVIOR CHANGE to build_context coalescing: a dropped node (system, or any
  !goes_to_model node) is now a **coalescing boundary** — the PRD acceptance criterion
  "a system node between user content still splits coalescing". Implemented with a
  `coalescing` flag reset to False on any dropped node and on assistant turns; user
  runs merge only while it's True. Previously a skipped node was invisible to merging
  (two users around a system node merged). Empty user/assistant nodes (goes_to_model
  True, skipped for empty content) do NOT reset the flag → their merge behavior is
  unchanged. No existing test relied on merge-across-system, so all 432 pass.
- Tests: code-blind flow. Stubbed `Node.compression` (NotImplementedError) + updated
  docstrings → spawned test-spec-author with interface + prose → 12 red / 1 pass
  (collected cleanly) → implemented to green. New files:
  `tests/specs/compression_node.md` (C1–C13) + `tests/test_compression_node.py` (13
  tests: factory fields/meta/order/aliasing, goes_to_model, wrapping, coalescing both
  directions, assistant & system boundaries, ordering, child-content-doesn't-leak).
  Added C24 to `tests/specs/context.md` documenting the system-boundary change (the
  existing build_context oracle).
- Verification: pure core logic (no UI/runtime surface), so tests + `scripts/check.sh`
  (432 passed, ruff+mypy clean) are the verification; qa-tester not applicable.
- Updated AGENTS.md architecture map (nodes.py factory list + goes_to_model set +
  context.py compression rendering / coalescing-boundary note).
- GOTCHA for task 2 (`current_view()` folds): the compression factory stores the range
  as a COPY (`list(range_ids)`); K is meant to be added straight to `_graph`, never via
  `_append_to_line`. Rendering wraps content only — folded children never contribute
  their body to K (task 5's draft is where the summary text comes from).

## 2026-07-03 — Task 2 (Sprint 3): current_view() resolves compression folds
- `ctx/core/conversation.py` `current_view()`: after the existing `prev_id` walk (root-
  first view), a second pass collapses each **maximal contiguous run** of view nodes
  sharing the same non-None `compressed_into = K` into the single `K` node from `_graph`
  (Q1 pointer-based 3a resolution). Loop: at each position, if the node's
  `compressed_into` is set AND that K exists in `_graph`, append K once and skip the whole
  run of same-K children; else pass the node through. A `compressed_into` pointing at a
  missing id → treated as unfolded (defensive, mirrors the walk's missing-id tolerance).
  K appears despite `prev_id=None`; `_append_to_line` still chains from the real
  `_active_leaf_id`, so append-after-folded-tip yields `[..., K, new]`.
- Tests: code-blind flow. Updated `current_view()` docstring (interface) → spawned
  test-spec-author with interface + prose → 7 red / 3 pass (collected cleanly) →
  implemented to green. New: `tests/specs/conversation.md` C81–C90 + 10 tests
  `tests/test_conversation.py::test_c81..c90` (no-fold identity, tip fold, append-after-
  fold, middle fold, two independent Ks, single-node fold, dangling id, empty, save/reload
  round-trip, root fold). Helpers `_view_core`/`_chain` added.
- DELIBERATE TEST FIX (Ralph rule): the authored C85 was self-inconsistent — its setup
  folded BOTH e and f into K2 (a contiguous run → one K2, no surviving f) yet asserted
  `[a, K1, d, K2, f]` expecting f to survive. My impl is correct (both folded → single
  K2). Fixed the test to match its clear intent: only e→K2, f left unfolded as the
  surviving tail → `[a, K1, d, K2, f]`. Updated C85 spec text in lockstep. Also added
  `strict=False` to the `_chain` zip (ruff B905).
- Verification: pure core projection logic, no new UI/runtime surface (K rendering in the
  message list is task 8), so tests + `scripts/check.sh` (442 passed, was 432; +10;
  ruff+mypy clean) are the verification; qa-tester not applicable this iteration.
- GOTCHA for task 3 (`commit_compression`): folding is now purely pointer-based in
  current_view — commit must set `compressed_into=K.id` on each slice node and add K
  straight to `_graph` (never `_append_to_line`); the view then resolves automatically.
  Task 15 later swaps the resolution mechanism (event-enumeration) behind this same
  `current_view()` signature — don't bake pointer-following assumptions into callers.

## 2026-07-03 — Task 3 (Sprint 3): commit_compression + streaming flag (H2)
- `ctx/core/conversation.py`:
  - `streaming` read-only property backed by `_streaming: bool` (init False), set True at
    `stream()` body entry, cleared in a new `finally:` (kept the existing except/else
    persist branches untouched → C40/C42 cancel tests still pass).
  - `_validate_compress_range(start_id, end_id) -> list[Node]` (private, SHARED with task 5):
    order of ValueError guards — (1) streaming (H2), (2) both ids in `current_view()`,
    (3) start ≤ end, (4) Q7 flat guard (no `node_type=="compression"` in slice), (5) 3a
    tip guard `slice[-1].id == _active_leaf_id` kept a DISTINCT deletable line (task 22
    removes only that line). Returns the root-first view slice.
  - `commit_compression(start_id, end_id, summary, prompt="") -> Node`: validate → build K
    via `Node.compression(summary, conv_id, [n.id for n in slice], prompt=prompt)` (range =
    ordered slice ids, H1) → add K straight to `_graph` → set `compressed_into=K.id` on each
    slice node → `persist()` → return K. Pure, non-destructive (children preserved); the
    task-2 `current_view()` fold resolves K into place automatically.
- Tests: code-blind flow. Stubbed the three members (NotImplementedError) with docstrings →
  spawned test-spec-author with interface + prose → 12 red (clean collect) → green. New:
  `tests/specs/commit_compression.md` (C91–C103) + `tests/test_commit_compression.py` (12
  tests: tip fold, K fields, default prompt, single-node fold, prefix unchanged, save/reload
  round-trip, tip-guard/flat-guard/streaming-guard/unknown-id/reversed-order rejections, each
  rejection also asserts view-unchanged + no-K). Spec author guessed import
  `from ctx.core import ConversationCore` (wrong) → fixed to `ctx.core.conversation` (test
  infra, not the contract). ruff auto-sorted the test imports.
- Verification: pure core logic, no UI/runtime surface (K rendering/commit UI is task 8), so
  tests + `scripts/check.sh` (454 passed, was 442; +12; ruff+mypy clean) are the verification;
  qa-tester not applicable this iteration.
- GOTCHA for task 5 (`draft_compression`): reuse `_validate_compress_range` verbatim (it
  already includes the streaming + tip + flat guards). Task 22 later deletes ONLY the tip-guard
  line from it — keep that line self-contained. `_streaming` is set inside the async-generator
  body, so `streaming` is False until the consumer calls the first `__anext__()`; the streaming
  guard test drives one token through before asserting.

## 2026-07-03 — Task 4 (Sprint 3): expand_compression + Node.expand event node (H1/H5)
- Continued a previous agent's in-progress work: `ConversationCore.expand_compression` +
  `Node.expand` + `tests/test_expand_compression.py` + `tests/specs/expand_compression.md`
  were already on the tree (unstaged). Implementation was correct; the blocker was a
  deadlocking code-blind test.
- `ctx/models/nodes.py::Node.expand(target_id, anchor_id, conversation_id)`: off-line E
  event node (`role`/`node_type` both `"expand"`, empty content, `prev_id=None`,
  `goes_to_model()` stays False, `meta={"target", "anchor"}` — H5). Factories are the
  single construction seam (ADR 0014 #1).
- `ctx/core/conversation.py::expand_compression(k_id) -> None`: non-destructive inverse of
  commit. Guards (ValueError): streaming (H2) → K exists & is a compression node → K is
  **active** (some node still carries `compressed_into == k_id`; an already-expanded K
  has no child pointing at it, so this doubles as the already-expanded guard). Mutation:
  append E to `_graph`, clear `compressed_into` on each child read from `K.meta["range"]`,
  `persist()`. K is KEPT as an off-line orphan (never row-deleted, ADR-0016 A#3 §1).
- HANG BLOCKER (found + fixed): `scripts/check.sh` deadlocked. Bisected → only
  `tests/test_expand_compression.py` hung, specifically C112
  `test_expand_rejected_while_streaming`. Root cause = the exact pitfall in memory
  `write-tests-blocking-provider-reused-in-setup`: the code-blind test built the whole
  history via `_build_line(core)` (fully drains two streams) against a core constructed
  with `BlockingProvider`, which yields one token then `await gate.wait()` forever — the
  first drained stream hangs pytest indefinitely. This is a TEST-INFRA bug (bad test
  double reuse), not the behavior under test → fixed directly per PROMPT.md carve-out.
- DELIBERATE TEST FIX #1 (C112 setup): build history with the normal `test_provider`, then
  swap `core._provider = BlockingProvider(...)` for the live turn only (memory-endorsed
  pattern; mirrors the working `test_commit_compression.py::test_streaming_guard...` which
  never `_build_line`s the blocking provider).
- DELIBERATE TEST FIX #2 (C112 assertion): after fixing the hang, C112's final assertion
  `_view_ids(core) == [u1,a1,K]` failed — `core.submit("A follow-up question")`
  unavoidably appends u3/a3 to the active line, so the real view is `[u1,a1,K,u3,a3]`. The
  original assertion was never validated (it deadlocked before reaching it) and asserts an
  impossible view. Rewrote it to the true invariant the clause tests — "expand did not
  fire" → K still in view AND its children (u2,a2) still folded out. Updated spec C112 in
  lockstep. Both fixes are test-infra/wrong-assertion corrections, NOT weakening the
  contract.
- Verification: pure core logic, no UI/runtime surface (the `/expand` UI command is task
  11), so tests + `scripts/check.sh` (467 passed, was 454; +13; ruff+mypy clean) are the
  verification; qa-tester not applicable this iteration.
- Also on the tree from the prior iteration: Ralph-infra hardening (loop.sh adds `Monitor`
  to ALLOWED_TOOLS; PROMPT.md adds gate-running / hang-bisect guidance) — committed
  separately as `chore(ralph):` since it is not part of task 4.
- GOTCHA for task 5 (`draft_compression`): reuse `_validate_compress_range` (streaming +
  tip + flat guards). For any streaming-guard test, NEVER build history via `_build_line`
  with a `BlockingProvider` — swap the provider in for the live turn only, else pytest
  deadlocks (see memory `write-tests-blocking-provider-reused-in-setup`).

## 2026-07-03 — Task 5 (Sprint 3): draft_compression (AI draft stream, Q3/Q10)
- `ConversationCore.draft_compression(start_id, end_id, prompt=None) -> AsyncIterator[str]`
  (`ctx/core/conversation.py`): AI-assisted counterpart to the pure `commit_compression`.
  Reuses `_validate_compress_range` verbatim (streaming/H2 + contiguous-view-slice + flat +
  3a tip guard) — validation runs on first `__anext__`, BEFORE any provider call. Renders
  ONLY the range via `build_context(range_nodes, self._workspace.read_file)` (Q10c: each node
  in model-facing form — import → file body, summary → its summary). Streams via
  `self._provider.stream(messages, self.model, <no-op on_usage>)`. Mutates no state, commits
  nothing (cancellation-safe by construction — it only reads + streams).
- INSTRUCTION FRAMING DECISION (implementer's choice, PRD said record it): the instruction is
  appended as a single trailing `{"role": "user", "content": <prompt-or-default>}` message
  after the build_context-rendered range — no extra XML/preamble wrapper. Q2b (no preamble)
  applies to the *committed K's* `<conversation_summary>` rendering, not to this draft input;
  the draft is just "here is the range, now summarize it per this instruction".
- Added `DEFAULT_COMPRESSION_PROMPT` module constant in `conversation.py` with the exact
  ADR-0016 A#1 text ("Preserve the facts, decisions, entities, and open threads needed for
  the conversation to continue coherently."). Task 18 later makes this a read of
  `compression.default_prompt` config — keep it a single named constant so that swap is local.
- GAUGE UNTOUCHED (Q10b): passes a local no-op `_ignore_usage` to the provider so
  `_calibrate` is never invoked — `last_usage`/`calibration`/`usage_generation` survive a
  draft even when the provider reports a sane `Usage` (C122 asserts this).
- Tests: code-blind `test-spec-author` wrote `tests/specs/draft_compression.md` (C121–C133)
  + `tests/test_draft_compression.py` (12 tests: token order, gauge-untouched-with-usage,
  custom prompt reaches provider msgs, default prompt fallback, range content rendered,
  unknown-start/unknown-end/reversed/non-tip-guard rejections each asserting provider never
  called, streaming guard via fresh-core+BlockingProvider one live turn, full-draft/cancelled
  leave view ids unchanged). Author flagged C133 (flat guard) unwritten — intentionally NOT
  added: it shares `_validate_compress_range` with commit, whose flat guard is already tested
  (`test_commit_compression.py::test_flat_guard...`); a draft-specific dup fails the deletion
  test. ruff auto-sorted the test imports.
- The authored providers alias `stream = generate = complete = astream = _emit` defensively
  (author was blind to the Protocol method name); harmless — the real `stream` is present and
  is what the core calls. Left as-is (functional, not a bug).
- Verification: pure core logic, no UI/runtime surface (the `Ctrl+D` draft UI is task 9), so
  tests + `scripts/check.sh` (479 passed, was 467; +12; ruff+mypy clean) are the verification;
  qa-tester not applicable this iteration.
- Also updated AGENTS.md architecture map (conversation.py bullet) to describe
  `draft_compression` per the keep-the-map-current rule.
- GOTCHA for task 9 (`Ctrl+D` UI worker): the UI consumes this async iterator; re-draft must
  clear Bottom first (Q4). draft is NOT gated by `core.streaming` itself (it doesn't set the
  flag — meta-op), but the UI additionally refuses actions while `_stream_worker` runs; a
  draft worker is separate from the turn `_stream_worker`.

## 2026-07-03 — Task 6 (Sprint 3): UI range selection (`v` anchor + extend, Q5)
- `ChatApp` gains vim-style contiguous range selection (`ctx/ui/app.py`): a `v`
  Binding → `action_anchor_range` sets `_range_anchor_id = _selected_node_id`;
  `action_up`/`action_down` call `_apply_range_selection()` after moving the cursor
  when an anchor is set; `_range_ids()` returns the ordered view-slice ids between
  anchor and cursor (empty when no anchor / anchor left the view). `action_escape`
  swallows the FIRST Esc to clear the range (stays in Edit) before the mode toggle;
  `_clear_selection()` now also clears the range, so `/new`, `/resume`, and entering
  Insert all drop it uniformly.
- `MessageWidget.set_range_selected(bool)` toggles a `.range-selected` class
  (`message_list.py`), styled `background: $primary-darken-2` (`message_list.css`) —
  distinct from `.selected` (the single cursor; a range spans many widgets, the cursor
  stays within it).
- `describe_state()` gains `"range_selection": [<node ids in view order>]` (the Pilot
  floor); footer `_HINTS["edit"]` gains `v Select` (trimmed `Switch pane`→`Pane` to
  stay ≤100 cols for ruff E501 — no test pins the edit hint string).
- DECISION: used node **ids** in `range_selection` (not the index-based convention
  elsewhere in describe_state) because the PRD task 6 wording + acceptance explicitly
  say "node ids in view order" / "3 contiguous ids". Pilot maps them via
  `app.core.nodes`.
- GOTCHA: `_select_relative` WRAPS (modulo len) at the list ends — so a range extended
  past the top/bottom edge wraps the cursor and `_range_ids` would then span the whole
  list. Not exercised by task 6 (acceptance uses Home then v,down,down within bounds);
  vim also doesn't wrap in visual mode. If task 7+ needs clamped extension, clamp in
  `action_up/down` when `_range_anchor_id` is set, don't change `_select_relative`
  (other callers rely on wrap).
- Tests: `tests/test_app_range_selection.py` — 3 Pilot tests via `pilot.press` (real
  binding wiring): `v,down,down` → 3 contiguous ids + `.range-selected` on those
  widgets only; `Esc` empties the range and stays in Edit; `v` alone = range-of-one.
  This is a UI task → Pilot is the mandatory floor; no core change so no code-blind
  flow. PRD task 6 does not request qa-tester (unlike tasks 8/10/11/12), and the
  in-process harness can't see uncommitted edits anyway → qa-tester not applicable.
- Verification: `scripts/check.sh` green (482 passed, was 479; +3; ruff+mypy clean).
- Did NOT commit the pre-existing dirty `CONTEXT.md` / `docs/Sprint Roadmap.md` (dirty
  at session start, not this task's work; Roadmap edits are forbidden by the PRD).
- GOTCHA for task 7 (`c` / `/compress` draft editor): it "acts on the active range
  selection" — read it from `_range_ids()` (start = ids[0], end = ids[-1]); no anchor
  → range-of-one on the selected node (Q5). The selection must survive Esc-closing the
  editor (task 7 keeps it), so do NOT call `_clear_range()`/`_clear_selection()` on
  editor cancel.

## 2026-07-03 — Task 7 (Sprint 3): compression draft editor opens/edits/cancels (Q4)
- New `CompressionEditor` widget (`ctx/ui/widgets/compression_editor.py`): a left-pane
  **2-split** (Q4) `Container` — Top editable prompt `TextArea` (prefilled with
  `DEFAULT_COMPRESSION_PROMPT`), Bottom editable summary `TextArea` (empty on open),
  **no Center** (the originals stay highlighted on the right as the selection). Interface:
  `open(prompt)` / `close()` / `is_open` / `prompt` / `output`. Hidden by default
  (`display: none`); its DEFAULT_CSS mirrors `#detail`'s `width:1fr; border-right` so it
  sits exactly in the inspector's slot when shown.
- DECISION: **sibling widget, not an inspector mode** (PRD left it to the implementer).
  The editor has editable `TextArea`s; the committed-K inspector (task 10) is a read-only
  3-split. Keeping them separate keeps each deep+simple; opening toggles
  `DetailInspector.display=False` + `CompressionEditor.display=True`, closing reverses it.
- `ChatApp` wiring (`ctx/ui/app.py`): composed as the 2nd child of `#body`. New `c` Binding
  → `action_compress` (Edit mode only, no-op in detail pane / with no selection);
  `_compression_range()` = active range (`_range_ids()`) or **range-of-one** on the selected
  node when no anchor (Q5); `_open/_close_compression_editor()`. `action_escape` closes the
  editor FIRST (before the detail/range/mode-toggle chain) — cancels for free, restores the
  inspector, refocuses `MessageList`, and **preserves the selection** (never clears
  `_selected_node_id`/`_range_anchor_id`). `/compress` added to `InputBar.COMMANDS` + an
  `on_input_bar_submitted` branch → `_handle_compress_command`: opens on an active selection,
  else a system breadcrumb "Select a range first: v in Edit mode".
- `describe_state()` gains `"compression_editor": {"open": bool, "prompt": str, "output": str}`
  (the Pilot floor). Footer `_HINTS["edit"]` gains `c Compress` (trimmed `Navigate`→`Nav` and
  dropped the cosmetic `Home Top` to stay ≤100 cols for ruff E501 — no test pins the hint; Home
  binding itself is unchanged).
- On open the prompt `TextArea` is focused so editing works immediately; TextArea has no
  `escape` binding (verified) so Esc bubbles to the app's `escape` action and closes cleanly.
- NO CORE CHANGE this task — `draft_compression` (task 5) already exists; task 7 is pure
  UI open/edit/cancel with **no graph mutation** (Commit/Draft keys are tasks 8/9). So per the
  task-6 precedent this is a UI task: Pilot is the mandatory floor, no code-blind test-spec flow.
- Tests: `tests/test_app_compression_editor.py` — 4 Pilot tests via `pilot.press` (real binding
  wiring): `c` on a 2-node range → editor open w/ default prompt + empty output, inspector
  hidden; `c` with no anchor → range-of-one opens; `/compress` with no selection → breadcrumb +
  editor stays closed; `Esc` closes, keeps range_selection, stays in Edit, restores inspector.
- Verification: `scripts/check.sh` green (486 passed, was 482; +4; ruff+mypy clean). qa-tester
  NOT applicable — task 7 doesn't request it and the in-process harness can't see this
  iteration's uncommitted edits anyway.
- Did NOT commit the pre-existing dirty `CONTEXT.md` / `docs/Sprint Roadmap.md` (dirty at
  session start; Roadmap edits are forbidden by the PRD).
- GOTCHA for task 8 (`Ctrl+S` commit): read the range from `_compression_range()` (start=ids[0],
  end=ids[-1]); the summary is `CompressionEditor.output`; commit with `prompt=""` for now (task 9
  switches it to the drafted Top). On commit, `_close_compression_editor()` then clear the
  selection + rebuild the list. `Ctrl+S`/`Ctrl+D` bindings must live on the editor (or be gated to
  when it's open) so they don't fire in normal Edit mode — the editor currently owns no bindings.

## 2026-07-03 — Task 8 (Sprint 3): commit (`Ctrl+S`) + K rendering in the list (Q3/Q9)
- `ChatApp.action_commit_compression` (`ctx/ui/app.py`, new `ctrl+s` Binding, gated on
  `CompressionEditor.is_open` → inert in normal Edit mode). Non-empty Bottom →
  `core.commit_compression(ids[0], ids[-1], summary=editor.output, prompt="")` (`""` =
  manual, task 9 switches it to the drafted prompt), then `_close_compression_editor()`,
  `_clear_selection()`, `await _rebuild_message_list()`, `_refresh_token_ui()`. Empty
  Bottom → `_breadcrumb("Write a summary before committing (Ctrl+S).")`, NO commit,
  editor STAYS OPEN. Range read from `_compression_range()` (task 7 helper).
- New helpers: `_rebuild_message_list()` (tear down + re-mount from `core.nodes` — the
  resume rebuild path generalized) and `_breadcrumb(text)` (append a system message +
  refresh; used by the empty-summary guard).
- `ctrl+s` verified to bubble from the focused prompt/summary `TextArea` to the app
  (TextArea binds `ctrl+d`→delete_right but NOT `ctrl+s`); GOTCHA for task 9: `Ctrl+D`
  IS a TextArea binding, so the task-9 draft key must be a priority app binding or live
  on the editor, else it deletes text instead of drafting.
- K rendering: added `"compression": "#a855f7"` to `_DEFAULTS["colors"]`
  (`ctx/core/config.py`); added `"compression"` to `_TRUNCATION_KEY` (→ "assistant",
  2-line cap) and `_SIDE` (→ "assistant" side for pass margins) in `message_list.py`,
  and introduced a `_TALL_ROLES` constant (user/assistant/context/compression) so a K
  widget gets the tall/thick left border like a first-class turn. K is Markdown-rendered
  (not in the system/context Static branch). weight_pct is numeric automatically (K
  `goes_to_model()`; folded children leave the view, Q9).
- DELIBERATE test change (recorded per PROMPT step 5): `tests/test_config.py::
  test_c3_baseline_shape` + `tests/specs/config.md` C3 pinned the color-key set to 4
  keys; task 8 requires the 5th (`compression`), so I updated both to include it. This
  is the new-behavior floor, not weakening a check.
- EXTRA FIX folded into task 8 (qa-tester surfaced it): the editor had NO keyboard path
  to the Bottom "Summary" split — the app's priority `tab` binding hijacked focus into
  the hidden inspector, so a real user could not "type a summary in Bottom" (the PRD
  acceptance). Added `CompressionEditor.focus_next_split()` (prompt↔summary toggle) and
  gated `action_switch_focus` to route Tab there while the editor is open. Without this
  the manual-commit acceptance was only satisfiable by a Pilot test reaching in and
  setting `.text` — hollow. Now `tab` reaches it end-to-end.
- Tests: `tests/test_app_commit_compression.py` (5 Pilot tests via `pilot.press` = real
  binding wiring): full-range `c`→type→`Ctrl+S` folds 4 children into one K (numeric
  weight, `K.meta["prompt"]==""`, `range` len 4); keyboard-only `tab`→type→`Ctrl+S`;
  empty summary → breadcrumb + editor stays open + no K; `Ctrl+S` inert when editor
  closed; K round-trips across a second app instance on the same DB (resume shows [K]).
  UI task → Pilot is the mandatory floor; core `commit_compression` already exists+tested
  (task 3) so no code-blind flow.
- Verification: `scripts/check.sh` green (491 passed, was 486; +5 new −0; +1 was already
  in the 486 baseline for config; ruff+mypy clean). qa-tester (verify-feature) confirmed
  on the LIVE harness (app NOT stale, task-8 code active): the empty-summary guard passes
  end-to-end (4→5 nodes, exact breadcrumb, no K, editor open, `textual_check_errors`
  clean). It could NOT reach the happy path because `textual_query`/`textual_snapshot`
  were permission-blocked THIS session (env limitation, not a defect) — that path is
  covered by the two commit Pilot tests. It also noted `tools/agent/snapshot.py::render`
  does not surface `range_selection`/`compression_editor` in the compact text snapshot
  (only visual/`describe_state` do) — a headless-QA nicety, not a task-8 defect.
- Did NOT commit the pre-existing dirty `CONTEXT.md` / `docs/Sprint Roadmap.md` (dirty at
  session start; Roadmap edits forbidden by the PRD).
- GOTCHA for task 9 (`Ctrl+D` draft): (1) `Ctrl+D` is a TextArea binding (delete_right) —
  make the draft key a priority app binding or an editor binding. (2) On `Ctrl+S`, task 9
  must pass the LAST-DRAFTED prompt as `prompt=` (still `""` if never drafted); currently
  hard-coded `prompt=""`. (3) Re-draft OVERWRITES Bottom (clear first, Q4).

## 2026-07-03 — Task 9 (Sprint 3): draft streaming (`Ctrl+D`) + drafted-prompt commit (Q4/Q10b)
- `ChatApp.action_draft_compression` (new `ctrl+d` Binding, **priority=True** so it beats
  the focused TextArea's `delete_right`; inert unless `CompressionEditor.is_open`). Reads
  the range via `_compression_range()`, captures `editor.prompt` into `self._last_drafted_prompt`,
  and launches `@work _draft_compression_worker(start, end, prompt)`.
- Worker consumes `core.draft_compression(...)`, `editor.set_output("")` first (clear → re-draft
  overwrites, Q4), accumulates tokens and re-sets the Bottom split each token. `CancelledError`
  re-raises (keeps partial text, no graph mutation); other exceptions render `Draft failed: …`.
- New editor method `CompressionEditor.set_output(text)` (deep widget owns its TextArea).
- Ignore-while-streaming: `action_draft_compression` returns early if `_draft_worker` is RUNNING.
- Esc during a draft: `action_escape` now cancels a RUNNING `_draft_worker` and returns (editor
  stays open); a second Esc (no running draft) closes as before.
- `action_commit_compression` now passes `prompt=self._last_drafted_prompt` (was hard-coded `""`);
  `_open_compression_editor` resets `_last_drafted_prompt=""` (fresh open = manual until a draft
  runs); `_close_compression_editor` clears `_draft_worker`.
- Tests: `tests/test_app_draft_compression.py` (4 Pilot tests via `pilot.press` = real binding
  wiring): `Ctrl+D` fills Bottom with canned tokens AND leaves `usage_generation`/`calibration`
  unchanged (Q10b — provider reports a valid `Usage` so a wrongly-anchoring draft would trip);
  re-draft after a stale hand-edit + edited Top overwrites (not doubled); `Ctrl+D`→`Ctrl+S`
  stamps the drafted Top as `K.meta["prompt"]` (not `""`); `Ctrl+D` inert when editor closed.
  UI task → Pilot is the mandatory floor; core `draft_compression` already exists+tested (task 5).
- Did NOT write an Esc-cancels-draft test: with a canned provider the draft completes instantly,
  so mid-stream cancel isn't deterministic; the cancel path isn't in the task-9 acceptance floor
  (deletion test → skip). The RUNNING-guard + Esc-cancel wiring is exercised by code inspection.
- Verification: `scripts/check.sh` green (495 passed, was 491; +4; ruff+mypy clean). qa-tester
  NOT applicable — task-9 acceptance lists only Pilot (no "then qa-tester" clause, unlike tasks
  8/10/11/12), and the in-process harness can't see this iteration's uncommitted/cached edits.
- Did NOT commit the pre-existing dirty `CONTEXT.md` / `docs/Sprint Roadmap.md` (dirty at session
  start; Roadmap edits forbidden by the PRD).
- GOTCHA for task 10 (committed-K inspector 3-split): the drafted prompt now survives onto K via
  `K.meta["prompt"]` — task 10's Top split reads exactly that (empty prompt → hide Top). Add the
  `folded_children(k_id)` core accessor first (children are NOT in `current_view()`).
