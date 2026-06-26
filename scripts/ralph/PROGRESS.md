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
