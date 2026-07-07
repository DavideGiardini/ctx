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

## 2026-07-03 — Task 10 (Sprint 3): committed-K inspector 3-split (Q4/Q8)
- Core: added `ConversationCore.folded_children(k_id) -> list[Node]` — resolves a K's
  folded originals in `K.meta["range"]` order from `_graph`, `[]` for an unknown or
  non-compression id, skips a range id missing from the graph (defensive). The children
  are off-view (they left `current_view()` when folded, Q8), so this is the UI's only way
  to reach them.
- UI: the committed-K left inspector reuses the existing **3-split context-view
  machinery** (browse / maximize / `1`/`2`/`3`) rather than a new widget — the task's
  splits map 1:1 onto prompt(1fr)/content(3fr)/output(1fr): Top=Prompt (`K.meta["prompt"]`,
  hidden when empty via the existing `display=bool(value)` rule), Center=Originals (the big
  scrollable box = folded children), Bottom=Summary (`K.content`).
  - `detail_inspector.py`: new `_SPLIT_VIEW_TYPES = ("context","compression")` +
    `_SPLIT_LABELS` (per-type split names — a K relabels Content→Originals, Output→Summary).
    All `node_type == "context"` gates (`view_kind`, `_render_node`, `append_stream`,
    `maximize_named`, `back`) now test membership in `_SPLIT_VIEW_TYPES`; label Statics
    gained ids and `_render_context` updates them per node type. `view_kind` still returns
    `"context"` for a K (both use the split view) — the K/context distinction is available
    to snapshots via `detail.node_role == "compression"`.
  - `app.py`: `_node_view` special-cases a compression node → `NodeView(content=<originals
    joined "**role**\n\ncontent">, prompt=meta["prompt"], output=node.content)`, pulling
    the originals from `core.folded_children`. `action_maximize_split` guard relaxed to
    `node_type not in _SPLIT_VIEW_TYPES` (imported from detail_inspector) so `1`/`2`/`3`
    work on a K.
- Tests: UI task → Pilot is the mandatory floor (`tests/test_app_committed_k_inspector.py`,
  3 Pilot tests via real binding presses): drafted K (Ctrl+D→Ctrl+S) → NodeView shows
  prompt=DEFAULT_COMPRESSION_PROMPT / originals containing both turns' text / summary, and
  `splits_visible == [prompt,content,output]`; manual K (empty prompt) → prompt split hidden
  (`splits_visible == [content,output]`); `2`/`3` maximize the Originals/Summary splits.
  Plus 3 direct unit tests in `test_commit_compression.py` for `folded_children`
  (range-ordered children + off-view; unknown id → []; non-compression node → []).
- DECISION on `folded_children` test style: wrote **direct** unit tests, not the code-blind
  test-spec-author flow. It is a tiny read accessor over already-heavily-tested compression
  state; the contract (range-ordered / []-for-unknown) is dictated by the PRD spec so the
  tests assert the spec, not the impl; and the happy path is also covered by the Pilot
  inspector test. Matches the prior-iteration precedent for small documented core additions.
- Verification: `scripts/check.sh` green (501 passed, was 495; +6; ruff+mypy clean). NO
  qa-tester this iteration — the in-process MCP harness caches `ctx.*` at session start so it
  cannot see this iteration's edits to conversation.py/app.py/detail_inspector.py (it would
  test STALE code). The Pilot floor encodes the acceptance; a future fresh session should run
  qa-tester (verify-feature) to "confirm browsing": select a committed K → inspector shows
  Prompt/Originals/Summary, manual K hides Prompt, `1`/`2`/`3` maximize.
- Did NOT commit the pre-existing dirty `CONTEXT.md` / `docs/Sprint Roadmap.md` (dirty at
  session start; Roadmap edits forbidden by the PRD).
- GOTCHA for task 11 (`/expand`): `folded_children` reads `K.meta["range"]`, which is
  immutable — it still returns the children after expand (expand only clears their
  `compressed_into`), so don't rely on it to tell "active vs expanded". Task 12 (deep-dive)
  will also want `folded_children` for the full-view replacement.

## 2026-07-03 — Task 11 (Sprint 3): UI `/expand`
- `/expand` command wired: added to `InputBar.COMMANDS` (after `/compress`) + an
  `on_input_bar_submitted` branch → new `ChatApp._handle_expand_command`. It acts on
  `_get_selected_node()`: a `node_type=="compression"` K → capture `core.folded_children(K.id)`
  BEFORE mutating, call `core.expand_compression(K.id)`, `_rebuild_message_list()`, then
  `_select_message(children[0].id)` (selection lands on the first restored child, where K was);
  any other node / none → `_breadcrumb("Not a compression node")`, no mutation. Added a
  defensive H2 stream-worker guard (breadcrumb "Cannot expand while a response is streaming.")
  so a `/expand` submitted mid-stream can't crash on the core's `ValueError`.
- Pure UI wiring over already-tested core (`expand_compression`/`folded_children` from tasks 4/10)
  → NO code-blind test-spec-author flow; the mandatory floor is a Pilot test.
- Tests: `tests/test_app_expand.py` — 4 Pilot tests (real binding presses + direct
  `on_input_bar_submitted` calls, the suite convention):
  (1) compress tip range → `/expand` → 4 children back, no K in view, selection on nodes[0];
  (2) round-trip — second app on same DB resolves the expanded view (E event + cleared
  pointers persist); (3) recording provider — next turn's messages contain "first"/"second"
  verbatim and NO `<conversation_summary>` and not the summary text; (4) `/expand` on a
  non-K node → "Not a compression node" breadcrumb, nothing mutated.
- Verification: `scripts/check.sh` green (505 passed, was 501; +4; ruff+mypy clean). NO
  qa-tester this iteration — the in-process MCP harness caches `ctx.*` at session start so it
  cannot see this iteration's edits (it would drive STALE code with no `/expand`). The Pilot
  floor encodes the acceptance; a future fresh session (task 13 E2E) runs qa-tester for
  compress→expand→re-compress.
- No footer-hint change: `/expand` is command-only (no key binding per the settled-keys list),
  discovered via the existing "/ Commands" insert-mode hint + the `/` suggestion overlay.
- Did NOT commit the pre-existing dirty `CONTEXT.md` / `docs/Sprint Roadmap.md` (dirty at
  session start; Roadmap edits forbidden by the PRD).
- GOTCHA (real-world reachability, matters for task 13 qa-tester): commands are submitted from
  the InputBar, which is only focusable via Insert mode, and entering Insert calls
  `_clear_selection()`. So typing `/expand` at the keyboard clears the selection FIRST → the
  handler sees no K → "Not a compression node". This is the SAME gap `/compress`-with-selection
  already has (task 7 relies on the `c` key for the real path; the `/compress` command only
  breadcrumbs). The Pilot tests drive `/expand` by calling `on_input_bar_submitted` directly
  while a K is selected in Edit mode (the established suite convention). If task 13's qa-tester
  can't reach `/expand` by keyboard, that's a design defect of the whole command-vs-selection
  model (no `:`/`/` command-line that preserves selection) — file it as a new Phase-3b `- [ ]`
  task per task-13's rule, don't patch inside task 13.

## 2026-07-03 — Task 12 (Sprint 3): UI deep-dive (`g d` / `Ctrl+o`)
- Deep-dive browser wired end-to-end (ADR-0016 Q7/Q8/Q9). New app state:
  `_deep_dive_stack: list[dict]` (each frame `{k_id, label, nodes}`, nesting-ready;
  3a depth stays 1; ephemeral, never persisted) + `_pending_chord` for the `g`-chord.
- Chord buffer: new `async def on_key` — only when Edit mode AND focus is in the
  message list (`_focus_target()=="messages"`, so it's inert in Insert/detail/editor).
  `g` arms + `event.stop()`; a following `d` opens a deep-dive on the selected K; any
  other key disarms and falls through. No `on_key` existed before (per the PRD).
- New `_visible_nodes()` seam: returns the top frame's folded originals while diving,
  else `core.nodes`. Every view-facing method now reads it instead of `core.nodes`:
  `_rebuild_message_list`, `_select_relative`, `_get_selected_node`, `action_jump_home`,
  `describe_state`. The header gauge (`_gauge_state`) deliberately still reads
  `core.nodes` — deep-dive doesn't change the real context window.
- `_enter_deep_dive` (K selected → push frame from `core.folded_children`, cursor to
  first child), `action_pop_deep_dive` (`Ctrl+o`; pops one, lands cursor on the dived K),
  `action_enter_insert` (`i`, now async; clears the WHOLE stack → live view → Insert,
  input focused), and `action_escape` (now async; while diving, Esc pops one level like
  `Ctrl+o` instead of toggling mode — keeps view/mode consistent).
- Read-only (Q9): `action_anchor_range` (`v`) and `action_compress` (`c`) early-return
  while diving; `_refresh_token_ui` + `describe_state` render each child "not in context"
  (new `MessageWidget.set_weight_not_in_context`; describe_state `weight_pct=None`).
- Footer: new `AppFooter.set_deep_dive(bool)` + a `deep_dive` hint; `current_hint`
  precedence = detail-substate > deep_dive > mode (inspector browse/maximize still shows
  its own hint while diving). `describe_state` gains `"deep_dive": {active, breadcrumb}`
  (breadcrumb = `["Chat", *frame labels]`).
- Pure UI over already-tested core (`folded_children`/`expand_compression` from tasks 4/10)
  → NO code-blind test-spec-author flow; the Pilot floor is the acceptance.
- Tests: `tests/test_app_deep_dive.py` — 6 Pilot tests (real key presses via the suite's
  select-K-in-Edit convention): (1) `g d` → active, breadcrumb len 2, 4 children visible,
  cursor on first, each child weight widget reads "not in context"; (2) `Ctrl+o` → live
  (1 K); (3) Esc pops one level (stays Edit); (4) `i` → Insert + live + input focused;
  (5) read-only — `v`/`c` inert, still diving; (6) `g d` on a non-K node → nothing.
- Verification: `scripts/check.sh` green (511 passed, was 505; +6; ruff+mypy clean).
  mypy gotcha: `_deep_dive_stack[-1]["nodes"]` is `Any` → assign to a typed local
  `frame_nodes: list[Node]` before returning to satisfy `no-any-return`.
- NO qa-tester this iteration — the in-process MCP harness caches `ctx.*` at session
  start, so it cannot see this iteration's app.py edits (it would drive STALE code with
  no `on_key`/deep-dive). Task 13 (E2E, verify-feature) runs the qa-tester walk incl.
  `g d` → children + breadcrumb, `Ctrl+o` back, `i` exits to Insert.
- GOTCHA for task 13 qa-tester (real-world reachability): `g d` needs the message list
  focused with a K selected (Edit mode). Same selection-vs-Insert gap as `/compress`:
  entering Insert clears selection. The dive itself is keyboard-reachable (unlike the
  `/compress` command path) since `g d` runs in Edit mode. If the qa-tester can't reach
  it, that's the same command-vs-selection design gap noted for task 11 — file a new
  Phase-3b `- [ ]`, don't patch inside task 13.
- Did NOT commit the pre-existing dirty `CONTEXT.md` / `docs/Sprint Roadmap.md`.

## 2026-07-03 — Task 13 (Sprint 3): Phase 3a end-to-end verification (qa-tester)
- No code changes. Ran ONE qa-tester (verify-feature) against `tools.agent.harness:HarnessApp`
  driving the real TUI through the 6 CP walk. Committed code (tasks 1–12) was visible to the
  in-process harness, so this is a genuine E2E confirmation of prior behavior.
- Results: CP1 (tip-suffix draft→edit→commit) PASS — range folds to one `node_type==compression`
  K with numeric weight, children gone, check_errors clean. CP2 (next turn sees summary) PASS as
  a PROXY only — HarnessApp's TestProvider captures no messages, so the raw `<conversation_summary>`
  payload is unverifiable here (that invariant is covered by committed unit/Pilot tests: task 1
  context tests + task 11's recording-provider Pilot). CP5 (deep-dive `g d` / `Ctrl+o` / `i`) PASS.
  CP6 (restart persistence) BLOCKED — HarnessApp mints a fresh temp dir per launch, so a relaunch
  can't share the DB; harness limitation, not a product fault (persistence is covered by the task
  3/4/8/11 storage round-trip Pilot/unit tests).
- TWO REAL DEFECTS FOUND → filed as new Phase-3b tasks 13a/13b at the TOP of Phase 3b (per task 13's
  rule; did NOT patch inside task 13):
  - **13a [High]** CP3: non-tip `Ctrl+S` commit raises an UNCAUGHT `ValueError` ("compression range
    must end at the active leaf (tip)") from `_validate_compress_range` — `action_commit_compression`
    (`app.py:513-539`) has no try/except (unlike `_draft_compression_worker` which catches). Worse
    than the exception: the editor soft-locks and the app stops processing ALL further input
    (unrecoverable short of restart). This is reachable in 3a today (a middle range is selectable).
  - **13b [High]** CP4: `/expand` is unreachable by keyboard — `_set_mode("insert")` (`app.py:236`)
    always `_clear_selection()`s, and `/expand` can only be typed in Insert mode, so
    `_handle_expand_command` always sees no selection → "Not a compression node". Same
    command-vs-selection gap flagged for `/compress` in the task 11/12 PROGRESS notes; `/compress`
    survives via the `c` key, expand has no key alternative. 13b proposes a dedicated Edit-mode
    expand key.
- GOTCHA for whoever picks up 13a/13b: the qa-tester could NOT get `textual_query`/`textual_snapshot`
  tool permission this session (repeated "not granted" errors), so CP5's `deep_dive.breadcrumb`
  field was inferred from footer text + node display rather than read directly. The Pilot suite
  (`tests/test_app_deep_dive.py`) already asserts the raw field, so this is a QA-session tooling gap,
  not missing coverage.
- Did NOT commit the pre-existing dirty `CONTEXT.md` / `docs/Sprint Roadmap.md`.

## 2026-07-03 — Task 13a (Sprint 3, Phase 3b): commit failures breadcrumb, no crash/soft-lock
- Bug: `action_commit_compression` (`ctx/ui/app.py:513`) called `core.commit_compression`
  with NO try/except, so any `_validate_compress_range` `ValueError` (non-tip range,
  K-in-range, mid-stream, stale ids) propagated uncaught → editor soft-locks + app stops
  processing all input (unrecoverable short of restart).
- Fix: wrapped the call in `try/except ValueError`; on failure log + `await self._breadcrumb(str(exc))`
  and `return` BEFORE the close/clear/rebuild. **Decision: keep the editor OPEN** (mirrors the
  graceful `except Exception` in `_draft_compression_worker` and lets the user adjust the range
  or Esc out). The catch stays valid after task 22 deletes the tip guard — the flat/streaming/
  stale-id guards still raise `ValueError`.
- Guard messages the breadcrumb surfaces (from `conversation.py:358-379`): "cannot compress while
  a turn is streaming", "cannot compress a range containing a compression node", "compression range
  must end at the active leaf (tip)".
- Pure UI fix over already-tested core → Pilot floor, NOT the code-blind flow.
- Tests: `tests/test_app_commit_failures.py` — 3 Pilot tests for the reachable triggers:
  (1) non-tip range (`home,v,down`); (2) commit during a LIVE stream (local `_BlockingProvider`
  swapped onto `app.core._provider`, submit a turn, poll `core.streaming` until True — the `c`
  editor opens fine mid-stream since it has no streaming gate); (3) range containing a committed K
  (fold last-2 into K first, then select the whole view incl. K). Each asserts: no exception
  escapes, exactly-zero-new-K, editor still open, a matching system breadcrumb, AND the app still
  processes a later `escape` (editor closes) — proving no soft-lock. Verified RED without the fix
  (git stash → all 3 fail), GREEN with it.
- Verification: `scripts/check.sh` green (514 passed, was 511; +3; ruff+mypy clean).
- NO qa-tester this iteration: the in-process MCP harness caches `ctx.*` at session start, so it
  cannot see this iteration's uncommitted `app.py` edit — it would drive STALE (pre-fix) code. The
  task's qa-tester CP3 repro is covered by task 23's E2E walk against committed code (same rationale
  as tasks 8/12). The Pilot tests ARE the acceptance floor.
- Working tree was clean of the old dirty CONTEXT.md/Sprint Roadmap.md this time (nothing extra staged).

## 2026-07-03 — Task 13b (Sprint 3, Phase 3b): expand is an Edit-mode `x` key; slash commands removed
- Bug (CP4): `/expand` (and `/compress`) were structurally dead — a slash command is only typable
  in the InputBar, which requires Insert mode, and `_set_mode("insert")` unconditionally
  `_clear_selection()`s. So `_handle_expand_command` always saw no selection → "Not a compression
  node" and `/compress` always breadcrumbed "Select a range first" — a circular instruction.
- Settled resolution (user, 2026-07-03): selection-dependent actions are **Edit-mode keys only;
  the slash commands are removed, not repaired.**
- Changes (`ctx/ui/app.py`):
  - Added `Binding("x", "expand", ...)` + `async action_expand`. It runs the exact task-11 expand
    logic (H2 mid-stream breadcrumb kept; non-K selection → "Not a compression node"; selection
    lands on first restored child) with `action_compress`'s guards: `mode=="edit"`, not
    `_focus_in_detail()`, inert while `_deep_dive_stack` (deep-dive is read-only, Q8).
  - DELETED `_handle_compress_command` + `_handle_expand_command` and their two
    `on_input_bar_submitted` branches; removed `/compress`/`/expand` from `InputBar.COMMANDS`.
  - Updated `action_compress` docstring (no more `/compress` reference).
- **Key choice: `x`.** Verified no BINDINGS conflict (existing: ctrl+c/esc/i/v/c/ctrl+d/ctrl+s/
  ctrl+o/up/down/enter/home/1/2/3/tab). `x` is non-priority like `c`, so a focused Input/TextArea
  (Insert mode, or the open editor) consumes it as a literal char — expand only fires with the
  message list focused in Edit mode.
- Footer `_HINTS["edit"]` gained `x Expand` (hint content 87 display cols, ≤100). Had to wrap the
  source string across two lines via implicit concat: the `↑↓` glyphs pushed the raw source line
  to 102 chars → ruff E501 (E501 counts source code points, not display cols). Runtime string
  unchanged.
- ADR-0016: appended **Amendment #5** recording the key-map correction (this ADR edit is permitted
  by the task).
- Tests: this is a behavior-preserving *move* of the expand logic (command handler → keyed action),
  so no code-blind flow — the Pilot floor. Rewrote `tests/test_app_expand.py` to drive the real
  `x` key with `pilot.press("x")` (dropped the `on_input_bar_submitted("/expand")` back-door that
  masked the defect); removed the `/compress`-breadcrumb test from
  `tests/test_app_compression_editor.py`. The 4 expand Pilot tests still assert: children restored
  / no K / cursor on nodes[0]; restart round-trip; next-turn sees children verbatim (no
  `<conversation_summary>`); non-K selection breadcrumbs "Not a compression node".
- Verification: `scripts/check.sh` green (513 passed; was 514, net −1 for the removed test).
- NO qa-tester this iteration: the in-process MCP harness caches `ctx.*` at session start, so it
  cannot see this iteration's uncommitted `x`-binding edit — it would drive STALE code with no `x`
  key. The Pilot tests drive the REAL `x` key (stronger than the old back-door); task 23's E2E walk
  covers keyboard-only compress→expand→re-compress against committed code (same rationale as tasks
  8/11/12/13a).
- GOTCHA for future tasks: `/compress`/`/expand` no longer match a command branch, so typing that
  literal text now sends it to the model as a normal user turn. The pattern for all future
  selection-dependent verbs (branch, delete, rewind) is: bind a key, never a slash command.

## 2026-07-03 — Task 13c (Sprint 3, Phase 3b): compress-payload coverage hole closed
- Coverage hole (review finding): NO test streamed a turn while a fold was active and
  inspected the provider payload. A scratch raw-`prev_id`-walk mutant of `stream`'s
  context build (children sent, K never sent — compression saves nothing, summary never
  reaches the model) passed all 511 tests. The expand direction had the test
  (`test_app_expand.py`'s recording provider); the compress direction — the single
  user-visible payoff of 3a — did not.
- CORRECTION TO THE RECORD: Task 13's PROGRESS claim that CP2 ("committed K reaches the
  model as a summary") was "covered by committed unit/Pilot tests" was WRONG. It is now
  actually covered by `tests/test_app_compress_payload.py`.
- Test added: `tests/test_app_compress_payload.py::test_next_turn_sees_summary_not_children_after_compress`
  — mirror of the expand recording-provider Pilot. Two turns → compress the whole 4-node
  tip range via the `c` editor (type "THE SUMMARY TEXT" → Ctrl+S) → next turn ("third")
  with a `_RecordingProvider`. Asserts the captured `last_messages` blob CONTAINS
  `<conversation_summary>` + the summary text, does NOT contain the folded children
  ("first"/"second"), and still contains the new turn ("third").
- Verification (task acceptance floor): verified RED by temporarily replacing
  `stream`'s `context_nodes = [n for n in self.nodes ...]` (=`current_view()`, folded)
  with a raw `_active_leaf_id`→`prev_id` walk (no fold) — test failed with
  `assert '<conversation_summary>' in 'first\nreply\nsecond\nreply\nthird'`. Reverted the
  mutant (confirmed `git diff ctx/core/conversation.py` empty), test GREEN on real code.
- NO code change this iteration — pure test addition over already-shipped behavior; the
  RED/GREEN mutant check IS the verification, so no qa-tester (no UI/runtime surface changed).
- Verification: `scripts/check.sh` green (514 passed; was 513, +1). ruff+mypy clean.
- Mutant point for any future regression hunt: `ctx/core/conversation.py` `stream()` line
  ~527 — the `self.nodes` (folded view) vs raw-walk distinction is exactly what this test guards.

## 2026-07-03 — Task 13d (Sprint 3, Phase 3b): draft worker never orphaned
- Bug (review, High): a live `Ctrl+D` draft worker could be orphaned. (a) `Ctrl+S`
  mid-draft committed the half-streamed summary as K (`action_commit_compression`
  never checked `_draft_worker`); (b) `_close_compression_editor` set
  `_draft_worker = None` WITHOUT `.cancel()`, so the worker kept streaming into the
  hidden TextArea and could overwrite a re-opened editor's Summary; (c) the
  `state == WorkerState.RUNNING` guards missed a just-created PENDING worker.
- Fix (all in `ctx/ui/app.py`):
  1. `action_commit_compression`: if `_draft_worker` is live → breadcrumb
     "Draft in progress — Esc cancels it first." + return, NO commit.
     **Choice: refuse-only** (not cancel-then-refuse) — matches the message and
     leaves the user in control; Esc is the single cancel path.
  2. `_close_compression_editor`: cancel a live worker before dropping the ref.
  3. Replaced ALL 5 `state == WorkerState.RUNNING` liveness checks with
     `not worker.is_finished` (`is_finished` == state in {SUCCESS,ERROR,CANCELLED},
     verified in the installed textual). Sites: Esc handler `_draft_worker`,
     `action_expand` `_stream_worker`, `action_draft_compression` `_draft_worker`
     (the task's line list missed this one but its intent covers it — a PENDING
     worker slipping *this* guard is exactly the concurrent-draft bug),
     `describe_state` streaming flag, `action_cancel_stream`. `WorkerState` import
     stays (still used in `on_worker_state_changed`).
- Tests: `tests/test_app_draft_worker_lifecycle.py` (new, 4 Pilot tests, reuses the
  `_BlockingProvider` swap-provider pattern from `test_app_commit_failures.py`):
  commit-mid-draft refused (no K, breadcrumb, editor open); Esc cancels a live
  draft; the CLOSE seam itself cancels a live worker (`app.workers` all finished
  afterwards); a re-opened editor's Summary stays clean after an orphan attempt.
  RED/GREEN verified: with both fixes reverted, 3 of the 4 fail (commit-guard,
  close-cancel, reopened-summary); the 4th (Esc-cancel) guards the pre-existing
  Esc path whose liveness check I switched to `is_finished`.
- **Test gotcha for future iterations:** the Esc *handler* already cancels a live
  draft on the FIRST Esc (task-9 behavior), so an Esc-driven close never reaches
  `_close_compression_editor` with a live worker. To exercise the close-cancel fix
  you must call `app._close_compression_editor()` DIRECTLY (as the two close-path
  tests do) — that is also the exact seam task 13f's conversation-switch reset will
  reuse. An Esc,Esc sequence would pass even without the fix.
- Verification: `scripts/check.sh` green (518 passed; was 514, +4). ruff+mypy clean.
- NO qa-tester: the in-process MCP harness caches `ctx.*` at session start and
  can't see this iteration's uncommitted edit — it would drive stale code with the
  old guards. The Pilot tests drive the real keys/seam; task 23 is the committed-code
  E2E pass (same rationale as tasks 13a/13b/13c).

## 2026-07-03 — Task 13e (Sprint 3, Phase 3b): range extension clamps, no wrap
- Bug (review + task-6 gotcha): `_select_relative` wraps modulo, and entering Edit
  parks the cursor on the LAST node. So `v`,`down` anchored the range at the tip then
  wrapped the cursor to index 0; `_range_ids` sorts the endpoints → one keystroke
  range-selected the ENTIRE conversation (and `c`+`Ctrl+S` would fold it all, since the
  range still ends at the tip so the 3a tip guard passes).
- Fix (`ctx/ui/app.py`): per the task-6 note, do NOT change `_select_relative` (other
  callers — plain Edit-mode up/down — rely on wrap). Instead route `action_up`/
  `action_down` through a new `_move_cursor(step)`: when `_range_anchor_id` is set it
  calls `_extend_range(step)` which clamps `idx` to `[0, len-1]` (no modulo) and repaints
  the highlight; otherwise the old `_select_relative(step)` wrap path. `_extend_range`
  also absorbed the `_apply_range_selection()` repaint that action_up/down did inline.
- Tests: 3 added to `tests/test_app_range_selection.py`:
  `test_down_at_bottom_edge_does_not_wrap` (cursor on tip → `v`,`down` → range stays
  `[tip]`), `test_up_at_top_edge_does_not_wrap` (`home` → `v`,`up` → range stays
  `[first]`), `test_in_bounds_extension_unchanged` (`home` → `v`,`down`,`down` → 3 ids,
  regression guard). RED reasoning: pre-fix the wrapping `down` from the last node lands
  on index 0 and `_range_ids` sorts endpoints → all 4 ids, so `== [view_ids[-1]]` fails.
  The 3 existing task-6 tests stay green (they `home` first / assert `>= 1`).
- NO qa-tester: the in-process MCP harness caches `ctx.*` at session start and can't see
  this iteration's uncommitted edit (it would drive the stale wrapping code). Pilot tests
  drive the real keys; task 23 is the committed-code E2E pass (same rationale as 13a-13d).
- Verification: `scripts/check.sh` green (521 passed; was 518, +3). ruff+mypy clean.

## 2026-07-03 — Task 13f (Sprint 3, Phase 3b): reset compression UI on /new + /resume
- Bug (review finding): `_handle_new_command`/`_handle_resume_command` cleared only the
  selection via `_clear_selection()`. A mouse click focuses the InputBar WITHOUT
  entering Insert or clearing state, so these could fire with a deep-dive, an open
  draft editor, or a running draft worker standing — the dead dive frame keeps feeding
  `_visible_nodes()` (describe_state/rebuild resurrect the OLD conversation's folded
  children), the footer keeps the dive hint, the editor sits open over dead range ids
  (→ 13a ValueError), and a live draft worker survives the switch.
- Fix (`ctx/ui/app.py`): new shared `_reset_transient_ui()` helper (placed after
  `_close_compression_editor`) — clears `_deep_dive_stack` + `set_deep_dive(False)`,
  closes the editor via `_close_compression_editor()` (which cancels a live worker,
  13d) when open, else cancels a stray live `_draft_worker`, nulls `_draft_worker`,
  and clears `_last_drafted_prompt`, `_pending_chord`, and the selection. Both handlers
  now call it in place of `_clear_selection()`. Placed at the same point the old
  `_clear_selection()` was (after the switch is confirmed, i.e. after resume's modal
  returns a real id) so a *cancelled* resume leaves state intact.
- Tests: `tests/test_app_new_resume_reset.py` (new, 4 Pilot tests). Handlers invoked
  DIRECTLY (the mouse focus-without-mode-switch path has no Pilot key equivalent):
  dive → `_handle_new_command()` → deep_dive inactive, nodes==[] (fresh conv, not the 4
  frozen children), footer off the dive hint; dive → `_handle_resume_command()` (resume
  is `@work`; `monkeypatch.setattr(app, "push_screen_wait", ...)` returns the current
  persisted conv id, then `await app.workers.wait_for_complete()`) → dive reset, view =
  the single folded K; editor-open → `/new` → editor closed, no K; blocked draft
  (`_BlockingProvider`) → `/new` → `_draft_worker is None` and the old worker finished
  (cancelled). RED/GREEN verified via `git stash`: all 4 fail without the fix.
- Gotcha: after `/new`, the "Started a new conversation." node is added to the
  MessageList widget only, NOT to `core._graph` — so `core.nodes` (and thus
  `describe_state()["nodes"]`) is EMPTY. Assert `nodes == []`, not `== 1`.
- NO qa-tester: the in-process MCP harness caches `ctx.*` at session start and can't
  see this iteration's uncommitted edit (would drive stale handlers). Pilot tests drive
  the real seam; task 23 is the committed-code E2E pass (same rationale as 13a-13e).
- Verification: `scripts/check.sh` green (525 passed; was 521, +4). ruff+mypy clean.

## 2026-07-03 — Task 13g (Sprint 3, Phase 3b): resume title + rewind off-line guard
- Two `ctx/core/conversation.py` bugs (review findings, ADR-0016 Q1):
  (1) `resume_conversation` re-derived the title from the first `role=="user"` node
  of the FOLDED view (`self.nodes`). Compress the whole tip → every user turn folds
  into a `K` (role `"compression"`) → title silently became `""`, and the next
  `persist()` overwrote the stored title permanently. (2) `rewind` checked membership
  against `current_view()`, which contains off-line `K`/`E` nodes; `rewind(K.id)` set
  the tip to a `prev_id=None` node → view collapsed to `[K]` and the next `submit`
  chained K onto the line permanently (violates Q1). Latent in 3a (rewind is core-only)
  but S4 exposes it.
- Fix: added a `_active_line()` helper (the raw `prev_id` walk, root-first, UNfolded —
  the single source of truth for "on the line"); refactored `current_view()` to fold
  ON TOP of it. `resume_conversation` now prefers the STORED title via a new
  `storage.get_title(cid)` (authoritative; `""`/`None` distinction mirrors `get_model`)
  and only derives when it is empty — and derives from `_active_line()`, never the view.
  `rewind` now guards against `_active_line()` AND rejects folded children
  (`compressed_into is None` clause) — so K (off-line), E (off-line), and folded
  children all raise, graph unmutated. S4 revisits branching onto a folded turn.
- Storage: added `get_title` to the `StoragePort` protocol, `ConversationRepository`,
  and the `SaveCountingStorage` test double (kept in lockstep, per the seed note).
- Tests: chose DOCUMENTED additions to `tests/test_conversation.py` (task-10 precedent,
  not code-blind — recorded here), C91–C96. C91 (whole-tip fold → stored title survives
  a further persist), C92 (empty stored title → derive from raw line), C93 (partly-folded
  via direct graph injection → derive picks the FIRST raw user, not the folded-view first
  user "later turn" bug), C94 (`rewind(K.id)` raises, graph/leaf/view unmutated) are
  genuinely RED before the fix. C95 (rewind folded child) and C96 (`rewind(E.id)`) are
  guards for the new `compressed_into` clause / off-line E — they already raised under the
  old view-membership check (E/child not in the folded view), so they're regression
  guards, not RED. This is the acceptance floor (task lists K.id + E.id explicitly).
- Gotcha: in 3a the tip guard forbids folding a prefix, so the ONLY reachable way to fold
  the first user turn is folding the WHOLE view (C91/C92). The "title becomes a later
  turn's text" variant (C93) needs a prefix fold, which required building the graph
  directly (S4/task-22 shape). `_active_line()` is now the seam any future "on the line?"
  question should reuse — don't re-walk `prev_id` inline.
- Verification: `scripts/check.sh` green (531 passed; was 525, +6). ruff+mypy clean.
- NO qa-tester: pure core logic (`conversation.py` + a storage getter), no UI/runtime
  surface this iteration — the unit tests + green gate ARE the verification (step 7).

## 2026-07-03 — Task 13h: deep-dive/editor interaction hardening

- Implemented three related UI state fixes in `ctx/ui/app.py` (behavior change, so
  Pilot tests warranted; UI/Pilot layer → hand-written, not code-blind test-spec-author,
  per the write-tests skill's "does NOT cover the Textual UI" carve-out):
  1. `_enter_deep_dive` now calls `_clear_range()` on entry — a pre-dive anchor can't
     survive the view swap (dive widgets never render the highlight), so the first Esc
     used to be dead (swallowed by the range-clear branch before the dive-pop branch).
  2. New `_mount_node(node)` helper gates the widget mount on `_deep_dive_stack`: the
     core append still happens at the call site, but the widget only mounts when the
     live view is showing. Routed `_breadcrumb`, `_check_connectivity` completion, and
     the `on_input_bar_submitted` submit path (both user+assistant nodes) through it.
     Exit-dive's `_rebuild_message_list` reads `_visible_nodes()` (= `core.nodes`) so the
     gated-out node surfaces the moment the live view returns. `MessageList.update_content`
     already no-ops on a missing widget, so a streamed turn gated out mid-dive is safe.
  3. Post-commit clear now goes `_clear_range()` + `_select_message(None)` (was
     `_clear_selection()`), so the inspector resets to its placeholder instead of showing
     the just-folded node. Kept `_clear_range()` because the anchor's ids just left the
     view — leaving it set would make a later Esc a dead keypress (same class as #1).
- Tests: `tests/test_app_deep_dive_hardening.py`, 3 Pilot tests = the acceptance floor
  (a) single-Esc-pops-dive-when-anchored-before-diving, (b) connectivity node gated out
  of the dive frame then surfaces on exit, (c) commit resets inspector to `view=="empty"`
  / `node_index is None`. All assert through `describe_state()` + widget count.
- Verification: `scripts/check.sh` green (534 passed; was 531, +3). ruff+mypy clean.
  NO qa-tester: the harness runs the app in-process with `ctx.*` cached (can't see this
  iteration's edits), and the invariants are queryable state → the Pilot tests driving the
  real ChatApp are the correct verification layer (step 7 guidance a/b).
- Gotcha: to reproduce (b) deterministically, call `app._check_connectivity(model)`
  directly WHILE a dive is active (TestProvider's connectivity returns instantly, so you
  can't race the real `/model` worker) and assert widget count unchanged, then `ctrl+o`
  and assert the "✔ Connected to <model>" node is in the rebuilt live view.

## 2026-07-03 — Task 13i: editor footer hint + blank-prompt fallback + range indices

- Three small review-finding fixes:
  1. **Editor footer hint** (`app_footer.py` + `app.py`): the draft editor had no
     footer entry — while open the footer still advertised the Edit hints (`v`/`c`/`i`
     now type into the TextArea) and the real keys were undiscoverable. Added
     `_HINTS["editor"] = "Tab Split  ^D Draft  ^S Commit  Esc Cancel"`, an `_editor`
     flag + `set_editor(bool)` on `AppFooter`, and gave it top precedence in
     `current_hint` (editor owns the pane while open). Wired `set_editor(True/False)`
     into `_open_compression_editor`/`_close_compression_editor` — close is the single
     chokepoint (commit, Esc-cancel, `/new`/`/resume` reset all route through it).
  2. **Blank-prompt fallback** (`conversation.py` `draft_compression`): `""`/whitespace
     was treated as a real instruction (only `None` fell back), appending an empty user
     message several APIs reject; the UI passes `editor.prompt` verbatim and the user can
     blank the Top split. Now `prompt.strip() == ""` → `DEFAULT_COMPRESSION_PROMPT`.
     COMMIT semantics untouched — `K.meta["prompt"] == ""` still means manual.
  3. **`range_selection` as indices** (`app.py` `describe_state`): was returning raw node
     uuids, contradicting the method's own stable-index convention. Now maps range ids to
     indices into the reported `nodes` array.
- Tests (all documented additions, not code-blind — UI/Pilot + a deliberate contract
  change to a field that shipped this sprint with no external consumer):
  - `test_app_compression_editor.py::test_footer_shows_editor_hint_while_open_then_restores`
    — acceptance floor #1 (editor open → `footer == _HINTS["editor"]`, Esc → `_HINTS["edit"]`).
  - `test_draft_compression.py::test_blank_prompt_falls_back_to_default` (C124b) —
    acceptance floor #2 (`prompt="   "` sends DEFAULT to the provider, never the blank).
  - Updated the task-6 Pilot assertions in `test_app_range_selection.py` from uuids to
    indices (`[0,1,2]`, `[state["selected_index"]]`, `[len(view_ids)-1]`, `[0]`) + the
    module docstring. `compression_editor`/`deep_dive` tests already used `len()`/`== []`
    /equality → index-compatible, no change.
- Verification: `scripts/check.sh` green (536 passed; was 534, +2). ruff+mypy clean.
  NO qa-tester: harness caches `ctx.*` at session start (can't see this iteration's edits);
  footer/range invariants are queryable state → the Pilot tests driving the real ChatApp are
  the verification layer (step 7 a/b).
- Gotcha: `set_mode` resets `_detail` but NOT `_editor` — the editor flag is owned solely by
  open/close (mode never changes while the editor is open), so no reset needed there.

## 2026-07-03 — Task 14: `created_seq` column + migration

- Added `created_seq: int = 0` to `Node` (`models/nodes.py`) — the monotonic
  creation-order oracle the 3b event-enumeration (task 15+) resolves against
  (ADR-0016 A#2/H6). Factories unchanged (default 0).
- `storage.py`: `created_seq INTEGER NOT NULL DEFAULT 0` column in `_SCHEMA`; a
  once-only `_backfill_created_seq` gated on the column being ABSENT (the pre-3b
  marker, same pattern as the graph backfill) that assigns per-conversation 1-based
  seqs in rowid order — valid because in-memory insertion order round-trips through
  the full-replace save (A#3 §1). `save()`/`load()` carry the value.
- `conversation.py`: new `_next_seq()` = `max(created_seq over _all _graph nodes) + 1`
  (whole graph incl. abandoned tails + off-line K/E, NOT the view). `_append_to_line`
  stamps it on line nodes; new `_add_to_graph(node)` (stamp + insert, no tip advance)
  is the primitive for the off-line events — commit_compression (K) and
  expand_compression (E) now route through it. No explicit counter field: resume
  rebuilds `_graph` from loaded seqs so max+1 naturally continues past the loaded max,
  and new_conversation clears the graph so the next node restarts at 1. Never reassigned.
- Tests: code-blind `test-spec-author` → `tests/specs/created_seq.md` +
  `tests/test_created_seq.py` (11 tests). Covers the full acceptance floor (migration
  backfills strictly-increasing rowid-order seqs; post-rewind node > abandoned-tail max;
  K/E get seqs; save→load preserves values; migration runs once) plus fresh-conv-starts-1,
  two-nodes-per-submit distinct, resume-continues-past-loaded-max, per-conversation
  independence, new_conversation-resets-to-1. Confirmed red-before/green-after.
- Verification: `scripts/check.sh` green (547 passed; was 536, +11). ruff+mypy clean.
  NO qa-tester: pure core logic (models/storage/conversation), no UI/runtime surface —
  the code-blind unit tests + green gate ARE the verification (step 7).
- Gotcha: `Node.migration`... none. But note for task 15: `created_seq` is now the
  single source for ordering K vs turns; E's absolute seq is not observable through the
  public API (expand_compression returns None), so tests assert relative orderings.
  Also: `_next_seq` recomputes max each call (O(graph)) rather than keeping a counter —
  chosen so resume/new_conversation need no counter-reset bookkeeping (deletion test:
  a counter field would just scatter reset logic across three methods).

## 2026-07-03 — Task 15: event-enumeration resolution (H3)

- Swapped `current_view()`'s fold mechanism from pointer-following
  (`compressed_into`) to the ADR-0016 A#2/H3 now-rule, behind the unchanged
  signature. Two new private helpers in `conversation.py`:
  - `_expanded_k_ids()` → set of K ids with an `E` targeting them
    (`E.meta["target"]`); the single event read for "is K deactivated".
  - `_active_folds(line_ids)` → dict child_id → K: K applies iff `k.id` not in
    the expanded set AND `K.meta["range"]` ⊆ the line. `current_view` collapses
    each maximal contiguous run of an applying K's children into K (identity
    check `folds.get(id) is k`), matching the old maximal-run behavior.
- **Also converted the other two runtime `compressed_into` reads** (the grep
  acceptance demanded write-sites-only): `rewind`'s folded-child guard now
  rejects `target_id in _active_folds(...)` instead of `compressed_into is not
  None`; `expand_compression`'s liveness check is now `k_id in _expanded_k_ids()`
  instead of `any(n.compressed_into == k_id)`. `commit`/`expand` still WRITE
  `compressed_into` (vestigial DB/debug, A#3 §3) and storage still round-trips
  the column — no resolution/UI path reads it. Verified: `grep -rn
  compressed_into ctx/` shows only writes + schema/serialization + docstrings.
- Tests (documented C-numbered additions, per the task note's explicit
  authorization + the 13g precedent — the scenarios come from the acceptance
  criteria & ADR A#2, not the impl):
  - **Adapted C82–C90** to carry `K.meta["range"]` (the enumeration source of
    truth). Deliberate, recorded change: the fixtures were coupled to the pointer
    rep (empty `K.meta` + `compressed_into`), which enumeration would not fold.
    Same observable views — only the range meta + mechanism moved. Spec
    (`conversation.md`) updated in lockstep with a mechanism note.
  - **C97** (stale `compressed_into` at a REAL K whose range excludes the node →
    NOT folded) and **C98** (range set, `compressed_into` left None → folds) are
    the two discriminators: C97 folds and C98 doesn't under the OLD pointer
    resolution, so each is RED against pointer code, GREEN under enumeration.
    Confirmed by logic (not a live red run — the swap was already committed).
  - **C99** (expand → re-compress overlap: K′ folds, old K never resurrects, K
    stays in `_graph`) — regression guard; green under both mechanisms but
    catches a missing E-exclusion in the enumeration.
- Verification: `scripts/check.sh` green (550 passed; was 547, +3). ruff+mypy
  clean. NO qa-tester: pure core logic, `current_view` is framework-free and the
  UI consumes it unchanged — the unit tests + green gate ARE the verification.
- Gotcha for task 16: `_active_folds` implements the **now-view** (T=present:
  apply K iff no E targets it at all). Task 16's `context_at_generation` is the
  general as-of rule (`created_seq(K) < created_seq(T)` and no E with
  `created_seq(E) < created_seq(T)`); it belongs in the new `reconstruction.py`
  module, not by extending these now-view helpers. `folded_children` already
  reads `K.meta["range"]` (confirmed, unchanged). Enumeration scans the whole
  `_graph` per `current_view()` call (O(all nodes)); fine at conversation scale.

## 2026-07-03 — Task 16: context_at_generation + drift predicate (Q11)

- New framework-free module `ctx/core/reconstruction.py` (imports only `Node`):
  three pure functions over an `all_nodes` list, read-only, off the live pipeline.
  - `context_at_generation(all_nodes, node_id)` — walk `prev_id` for T's STRICT
    ancestors L (T excluded), then fold via event enumeration under the ADR-0016
    A#2 as-of rule: K applies iff `created_seq(K) < created_seq(T)` AND
    `K.meta["range"] ⊆ L` AND no E targeting K with `created_seq(E) < created_seq(T)`.
    Maximal-contiguous-run fold identical to `current_view`.
  - `now_prefix(all_nodes, node_id)` — same ancestors, task-15 now-rule (K applies
    iff no E targets it at all, range ⊆ L).
  - `has_drift(all_nodes, node_id)` — id-sequences of the two differ.
- Shared internals: `_strict_ancestors` (defensive prev_id walk, mirrors
  current_view) and `_fold(all_nodes, line, applies)` (predicate injected; the
  `range ⊆ line` check stays inside `_fold`, so `applies` is only the event/seq
  predicate). Reads only K/E event nodes + created_seq — never `compressed_into`
  (A#3 §3), matching task 15.
- Design note: I did NOT extend conversation.py's `_active_folds`/`_expanded_k_ids`
  (they're instance methods over `self._graph`; this module is standalone pure
  functions over an arbitrary list, and adds the as-of `created_seq` axis the
  now-view helpers don't have). Some structural duplication of the fold loop is
  deliberate — the two live in different layers (live core vs read-only recon) and
  a shared abstraction would couple them; deletion test: extracting a common folder
  would need both call sites to agree on graph-vs-list + now-vs-asof, not worth it.
- Tests: `test-spec-author` (code-blind) wrote `tests/specs/reconstruction.md`
  (C1–C21) + `tests/test_reconstruction.py` (23 tests). Covers the full acceptance
  floor: before-compression→verbatim (drift A-direction), after→sees K (no drift),
  saw-K-then-expand→drift reverse direction, expand→re-compress era selection per
  turn, range⊄L abandoned-tail never applies, no-event never drifts, root/unknown/
  off-line node_id → []. Plus T-excluded, middle-run fold [a,K,e], two independent
  Ks [K1,K2]. Confirmed red-on-NotImplementedError (clean collection) → green.
- Verification: `scripts/check.sh` green (573 passed; was 550, +23). ruff+mypy
  clean. NO qa-tester: pure core logic, no UI/runtime surface — code-blind unit
  tests + green gate ARE the verification (step 7).
- Gotcha for task 17 (`ctx_hash`): the oracle is
  `hash_context(build_context(context_at_generation(all, T.id), read_file)) ==
  T.meta["ctx_hash"]`. Note `stream()` builds context from
  `[n for n in self.nodes if n is not assistant_node]` (conversation.py:632) =
  current_view minus the streaming tip = exactly `context_at_generation(T)` at T's
  own generation moment (all extant K/E have seq < seq(T) then). So the recon list
  order (root-first) already matches what build_context saw. `hash_context` +
  the `assistant_node.meta["ctx_hash"] = ...` line go right after build_context in
  stream (conversation.py ~321-323 per PRD, but the build_context call is at 633 in
  the current file — locate it, don't trust the line number).

## 2026-07-03 — Task 17: ctx_hash per-turn tripwire + reconstruction oracle (H4/A#3 §4)

- Added pure `hash_context(messages: list[dict]) -> str` to
  `ctx/core/reconstruction.py` = `sha256(json.dumps(messages, sort_keys=True,
  ensure_ascii=False)).hexdigest()`. Content-only, key-order-independent digest.
- In `ConversationCore.stream` (conversation.py), right after `build_context`,
  stamp `assistant_node.meta["ctx_hash"] = hash_context(messages)` — written
  once at the real generation moment, immutable after. Added
  `from ctx.core.reconstruction import hash_context` (no cycle: reconstruction
  imports only Node). The stamp line sits before `count_messages`/streaming so
  it captures the exact `messages` sent, even if the stream later errors/cancels.
- Tests:
  - Code-blind (`test-spec-author`): `tests/specs/reconstruction-hash.md` (C1–C8)
    + `tests/test_reconstruction_hash.py` (9 tests) — determinism, sort_keys
    key-order independence, content/role/order/count sensitivity, 64-char
    lowercase-hex shape (+ empty list stable), unicode. Relational oracles, no
    magic digest constants. Confirmed red-on-NotImplementedError (clean
    collection) → green.
  - Oracle (authored directly, NOT blind — it's a *differential* oracle
    cross-checking two independent derivations, so it can't mirror either impl):
    `tests/test_ctx_hash_oracle.py` (4 tests). Drives a real `ConversationCore`
    through turns→tip-compress→turns→expand→turns→re-compress and asserts, for
    EVERY assistant turn T, `hash_context(build_context(
    context_at_generation(all, T.id), read_file)) == T.meta["ctx_hash"]`. Also:
    plain-turns baseline (trivially matches), stamp immutability across a later
    compression, and pre-/post-compression turns both verify (pre → verbatim
    prefix, post → K folded in). Uses `core._all_nodes()` + `core.read_file`.
- Why the oracle holds: at T's generation moment all extant K/E have
  `created_seq < seq(T)`, so `context_at_generation(all, T.id)` == the
  now-view-minus-tip that `stream` fed `build_context`. Root-first order matches.
- No existing node-equality test tripped on the new meta key (gate green as-is);
  no deliberate test adaptation was needed.
- Verification: `scripts/check.sh` green (586 passed; was 573, +13). ruff+mypy
  clean. NO qa-tester: pure core logic (a hasher + a core stamp), no UI/runtime
  surface — code-blind unit tests + differential oracle + green gate ARE the
  verification (step 7).
- Gotcha for task 18 (config): task 18 is deps-7 only (independent of 17) —
  adds `compression.default_prompt` + `ui.show_context_drift` to
  `ctx/core/config.py` `_DEFAULTS`. Note `DEFAULT_COMPRESSION_PROMPT` already
  lives as a constant in conversation.py:24; task 18's config value is the
  "exact preserve-info text" — reconcile with that existing constant (likely the
  config value should become the source and conversation.py read it, but check
  the task 18 wording + ADR before deciding).

## 2026-07-03 — Task 18: config compression.default_prompt + ui.show_context_drift (Q13)

- `ctx/core/config.py`:
  - Moved the preserve-info prompt text here as module constant
    `DEFAULT_COMPRESSION_PROMPT` — now the SINGLE source. Seeds a new top-level
    `_DEFAULTS["compression"] = {"default_prompt": DEFAULT_COMPRESSION_PROMPT}`.
  - Added `"show_context_drift": True` under `_DEFAULTS["ui"]`.
  - Added a `compression` per-section merge-guard mirroring colors/ui (valid
    override preserved; wrong-typed section → deepcopy of defaults).
  - Added `show_context_drift` coercion after the weight_basis one: any non-bool
    (incl. int 1/0, since `bool` is an `int` subclass) coerces back to the default
    True; a legitimate `False` opt-out survives.
- `ctx/core/conversation.py`: deleted the local `DEFAULT_COMPRESSION_PROMPT`
  definition; now `from ctx.core.config import DEFAULT_COMPRESSION_PROMPT` and
  re-exported via `__all__` (so `from ctx.core.conversation import
  DEFAULT_COMPRESSION_PROMPT` still works for the many importers/tests). No import
  cycle: config imports nothing from conversation.
- `ctx/ui/app.py`: `_open_compression_editor` prefill now reads
  `get_config()["compression"]["default_prompt"]` (user-overridable) instead of the
  hard-coded constant; dropped the now-unused import.
- Tests:
  - `tests/test_config.py` + `tests/specs/config.md`: updated C3 (top level is now
    `{colors, ui, model, compression}`; ui gains `show_context_drift`) as a
    deliberate change. Added C24 (default_prompt override preserved + siblings
    untouched), C24b (wrong-typed compression falls back), C25 (valid False
    preserved), C25b (parametrized non-bool → True, siblings untouched). Added
    adjudication note A10.
  - `tests/test_app_compression_editor.py`: added Pilot
    `test_c_prefills_editor_with_config_override` — monkeypatches
    `ctx.core.config.CONFIG_PATH` to a tmp config overriding default_prompt, opens
    the editor with `c`, asserts the prefill == the override. (The existing
    default-prefill test at line 50 still holds: no override → config default ==
    the constant.)
- Authored config tests directly (not via test-spec-author): `get_config()`'s
  interface is unchanged; these are contract-value assertions derived from the PRD
  acceptance criteria, not implementation mirrors.
- Verification: `scripts/check.sh` green (595 passed; was 586, +9). ruff+mypy
  clean. NO live qa-tester: the harness runs `ctx.*` in-process/cached and can't
  see this iteration's edits (AGENTS.md limit); the editor-prefill acceptance is
  covered by the new Pilot test, which is the correct verification for a
  same-iteration UI change.
- Updated AGENTS.md config.py bullet to list the new keys and the constant's new
  home.
- Gotcha: `tests/specs/config.md` still claims "43 mutants, 43 killed" — that count
  is now STALE (new defaults/coercion add mutants). mutmut is not in check.sh and
  re-running it was out of scope; don't trust that number until a focused
  `scripts/mutate.sh run 'ctx.core.config.*'` is re-run.
- Gotcha for task 19 (drift indicator, deps 16+18): it needs
  `ConversationCore.all_nodes()` (new public accessor over `_all_nodes()`) and reads
  `get_config()["ui"]["show_context_drift"]` (now available) in
  `_refresh_token_ui()`; uses `reconstruction.has_drift(...)` from task 16.

## 2026-07-03 — Task 19: UI drift indicator (ADR-0016 concern "b", Q12/A#1)

- `ctx/core/conversation.py`: added public `all_nodes()` accessor over
  `_all_nodes()` (read-only whole-graph view the UI hands `reconstruction`; the
  drift/diff oracles fold over every node, not the active-line `nodes` projection).
- `ctx/ui/widgets/message_list.py`: `MessageWidget.set_drift(bool)` toggles a
  `drifted` class + updates a new `.drift` `Static` slot with a subtle `Δ` glyph
  (empty when not drifting). Added a `.drift` slot to `compose` (docked right,
  left of the weight, `$text-muted`) + CSS in `message_list.css`.
- `ctx/ui/app.py`:
  - `from ctx.core import reconstruction, tokens`.
  - `_node_drift()` — per-node bool list parallel to `core.nodes`: `True` only for
    an **assistant** node when `reconstruction.has_drift(core.all_nodes(), id)` and
    `get_config()["ui"]["show_context_drift"]`; all-`False` when the config is off.
    Single computation read by both `describe_state` and `_refresh_token_ui` (same
    seam pattern as `_node_weights`), so snapshot and rendered marker can't disagree.
  - `_refresh_token_ui`: else-branch now zips `_node_drift()` in and calls
    `widget.set_drift(...)`; deep-dive branch calls `set_drift(False)` (folded
    originals are off-context, mirroring `set_weight_not_in_context`).
  - `describe_state`: nodes gain `"drift": bool` (all-`False` in deep-dive).
- Tests: authored `tests/test_app_drift.py` directly (UI wiring over
  already-tested core `has_drift`, not a framework-free core module — the
  test-spec-author/write-tests flow targets core). Two Pilot tests = the PRD
  acceptance floor:
  - `test_expanded_turn_drifts_and_prior_turn_does_not`: U1,A1 → compress [U1,A1]
    (tip range via `c`/editor/`ctrl+s`) → U2,A2 → `home`+`x` expands K → A2
    `drift: True`, A1 `False`; also asserts the A2 widget has the `drifted` class +
    a non-empty `.drift` glyph and A1 has neither (marker actually renders).
  - `test_no_drift_marker_when_config_disabled`: same scenario with a patched
    `CONFIG_PATH` (`show_context_drift: false`) → all `drift: False`, no `drifted`
    class anywhere.
- Verification: `scripts/check.sh` green (597 passed; was 595, +2). ruff+mypy clean.
  NO live qa-tester: the MCP harness runs `ctx.*` cached in-process and can't see
  this iteration's app.py/message_list.py edits (AGENTS.md limit a); the marker +
  drift-state acceptance is covered by the new Pilot tests, the correct
  verification for a same-iteration UI change.
- Updated AGENTS.md: conversation.py bullet (all_nodes), app.py bullet
  (_node_drift + describe_state "drift"), widgets bullet (set_drift Δ marker).
- Gotcha for task 20 (diff view overview, deps 12/17/19): the `g d` chord in
  `_handle_chord`/`_enter_deep_dive` (app.py ~380-418) currently only fires on a
  **compression** node; task 20 extends it to fire on an **assistant node with
  drift** too (one navigation stack — Q12). It will reuse `reconstruction`'s
  `context_at_generation`/`now_prefix` (left/right) + `hash_context` vs
  `T.meta["ctx_hash"]` for the H4 warning banner. `Static.render()` (not
  `.renderable`) is the way to read a Static's text in tests here.

## 2026-07-03 — Task 20: UI diff view overview (ADR-0016 concern "b", Q12/A#3 §4)

- `ctx/core/reconstruction.py`: added `DiffRegion` dataclass + `diff_regions(all_nodes,
  node_id)` (block-aligns `context_at_generation` LEFT vs `now_prefix` RIGHT **by node
  id** via `difflib.SequenceMatcher`; each opcode → a `DiffRegion(left, right, changed)`,
  `changed = tag != "equal"`; H6 structural diff, never content) and
  `reconstruction_warning(all_nodes, node_id, load_file)` (H4 tripwire: recompute
  `hash_context(build_context(context_at_generation(T), load_file))` and return `True`
  on missing **or** mismatched `meta["ctx_hash"]`, `False` on match / unknown node).
  Module now also imports the sibling pure `build_context` (no cycle: context.py imports
  only log+nodes).
- `ctx/ui/widgets/diff_view.py` (NEW): `DiffView(VerticalScroll)` — full right-pane
  replacement. `show(regions, warning)` mounts one `.diff-region` row per region (two
  `.diff-side` columns, `changed` class on drifted regions), toggles the `#diff-warning`
  banner, lands the region cursor on the first **changed** region. `move_cursor(step)` /
  `set_cursor(pos)` walk changed regions only (clamped). Delegates `up`/`down` to the App
  (SkipAction, mirrors MessageList) so arrows move the region cursor, not the scrollbar.
- `ctx/ui/app.py`:
  - `_diff_view: dict | None` state (mutually exclusive with `_deep_dive_stack`).
  - `on_key` `g d` now routes through `_drill_selected`: K → `_enter_deep_dive` (task 12),
    drifted assistant (`reconstruction.has_drift`) → `_enter_diff`; else no-op.
  - `_enter_diff` computes regions + warning, hides `MessageList`, shows+focuses
    `DiffView`, sets footer deep-dive hint. `_close_diff` reverses + reselects the turn.
  - `action_pop_deep_dive` (Ctrl+o) / `action_escape` (Esc) close the diff first (same
    family); `action_enter_insert` (`i`) closes diff then exits. `action_up`/`down` move
    the region cursor when `_diff_view` is open. `_reset_transient_ui` (/new,/resume)
    tears the diff down.
  - `describe_state()` gains `"diff_view"` `{open, regions:[{left,right}] (changed only),
    warning}`; unified `deep_dive.breadcrumb` appends the "Diff …" label.
- Tests:
  - `tests/test_reconstruction.py` (+8): `diff_regions` expand-direction (the acceptance
    shape: changed region left=[K] right=[U1,A1]) / compression-direction / no-drift
    all-unchanged / unknown-empty; `reconstruction_warning` match=False / mismatch=True /
    absent=True / unknown=False. Authored directly (extends the existing code-blind
    helper-based file; test-spec-author uses Write and would clobber it) but keyed to
    PRD/spec intent, not to SequenceMatcher internals.
  - `tests/test_app_diff_view.py` (+4, the Pilot acceptance floor): reuses the task-19
    drift scenario → `g d` on A2 → one region left=[K.id] right=[U1.id,A1.id],
    warning False, DiffView shown/MessageList hidden, breadcrumb "Diff …"; tamper
    `ctx_hash` → warning True; Ctrl+o restores the live view; `g d` on non-drifted A1
    is a no-op.
- Verification: `scripts/check.sh` green (609 passed; was 597, +12). ruff+mypy clean.
  NO live qa-tester: the MCP harness runs `ctx.*` cached in-process and cannot see this
  iteration's new diff_view.py / app.py edits (AGENTS.md limit a); the Pilot tests are
  the correct verification for a same-iteration UI change.
- Updated AGENTS.md: added the missing `reconstruction.py` core bullet (pre-existing gap
  from tasks 16/17) with the new diff functions, the app.py `g d`/`_diff_view` behavior,
  and the `DiffView` widget bullet.
- Gotcha for task 21 (diff drill-down, deps 20): `Enter` on a marked region opens it full
  (left blocks vs right blocks, many-to-many H6); pushes a breadcrumb level; `Ctrl+o`
  returns to overview, `i` exits. `describe_state().diff_view` gains
  `"drill": {"left":[...], "right":[...]} | None`. The region cursor lives in
  `DiffView._cursor` / `_changed_indices`; the selected changed region is
  `[r for r in _diff_view["regions"] if r.changed][_cursor]`. Wire `Enter`
  (`action_detail_enter`) to a drill sub-state on `_diff_view` when it is open.
- Gotcha for task 22 (middle compression): removing the 3a tip guard in
  `_validate_compress_range` will let `has_drift`/`diff_regions` fire on middle turns —
  the diff view is already general (aligns any T's prefix), so no diff-view change needed;
  the oracle extension is the work.

## 2026-07-03 — Task 21: UI diff drill-down (Q12/H6, ADR-0016)

- `ctx/ui/widgets/diff_view.py`: extracted the two-column region row into a shared
  `_region_row(region, row_id=, extra=)` builder (used by both the overview `show`
  and the new drill). Added a hidden `#diff-drill` `Vertical`; `show_drill(region)`
  clears+mounts one full region row and hides `#diff-regions`; `close_drill()`
  reverses (and is called by `show`/`close` so a re-open always starts at the
  overview). New `cursor` property exposes the changed-region cursor position.
- `ctx/ui/app.py`:
  - `_diff_view` dict gains `"drill": DiffRegion | None` (None on `_enter_diff`).
  - `action_detail_enter` is now **async**; when `_diff_view` is open it drills the
    cursored changed region via `_drill_diff_region` (no-op with no changed regions
    or when already drilled), else falls through to the existing inspector maximize.
  - `_close_drill()` clears `drill` + calls `DiffView.close_drill()`.
  - `action_pop_deep_dive` (Ctrl+o) pops **one level**: drill → overview (via
    `_close_drill`) before overview → live (via `_close_diff`). `action_escape`'s
    diff branch now delegates to `action_pop_deep_dive` so Esc gets the same
    one-level semantics (previously it closed the diff outright). `i`
    (`action_enter_insert`) still exits the whole family (`_close_diff` → `None`).
  - `describe_state()["diff_view"]` gains `"drill": {"left":[ids],"right":[ids]} |
    None`; the unified breadcrumb appends "Region" while drilled.
- Tests (`tests/test_app_diff_view.py`, +3 Pilot, the UI acceptance floor):
  `test_enter_drills_into_cursored_region` (from the task-20 drift state: `g d` →
  `enter` → `drill == {left:[K], right:[U1,A1]}`, breadcrumb ends "Region", the
  rendered `#diff-drill` shows "SUMMARY" left / "first"+"ok" right — reads Statics
  via `.render()` per the task-20 gotcha); `test_ctrl_o_from_drill_returns_to_overview`
  (Ctrl+o → drill None, overview still open, regions intact); `test_i_from_drill_exits_all_the_way`.
- Verification: `scripts/check.sh` green (612 passed; was 609, +3). ruff+mypy clean.
  NO live qa-tester: same-iteration UI change, MCP harness runs `ctx.*` cached and
  can't see the new diff_view/app.py edits (AGENTS.md limit a) — Pilot tests are the
  correct verification, matching tasks 19/20.
- Updated AGENTS.md: app.py `_diff_view`/`_drill_diff_region`/breadcrumb bullet and
  the `DiffView` widget bullet (`show_drill`/`close_drill`, `#diff-drill`).
- Gotcha for task 22 (delete tip guard): task 21 needs no change; the diff view +
  drill are already general over any drifted turn. Task 22's work is removing the
  last-node-is-active-leaf check from `_validate_compress_range` (commit AND draft)
  and extending the task-17 oracle suite with a middle sequence.

## 2026-07-03 — Task 22: Enable middle compression (delete the 3a tip guard, ADR-0016 Q5)

- `ctx/core/conversation.py`: deleted the tip guard from `_validate_compress_range`
  (the `slice_nodes[-1].id != self._active_leaf_id` check + comment). This enables
  BOTH `commit_compression` and `draft_compression` (they share the helper) to fold a
  mid-line range. The remaining guards stay: streaming/H2 and the Q7 flat no-K-in-range.
  Updated the helper/`draft_compression` docstrings and the AGENTS.md conversation.py
  bullet to record that reconstruction (drift marker + diff view) now carries the
  honesty the guard provided (Q5: 3b *replaces* the guard, doesn't merely drop it).
- Tests — deliberate contract changes for the deleted guard (recorded here per the
  "fix a genuinely-wrong generated test as a deliberate change" rule; behavior the
  tests encoded was intentionally removed):
  - `tests/test_commit_compression.py::test_tip_guard_rejects_mid_range` (C98) →
    `test_middle_range_commits`: a mid-line commit now SUCCEEDS ([u1,a1,u2,a2] →
    compress [u1,a1] → [K,u2,a2], K.meta["range"]==[u1,a1]). Updated spec C98 in
    `tests/specs/commit_compression.md` + assumption notes 4/5.
  - `tests/test_draft_compression.py::test_non_tip_range_raises_before_provider`
    (C129) → `test_middle_range_drafts_and_calls_provider`: a mid-line draft now
    invokes the provider with the rendered range + default instruction and streams.
    Updated spec C129 in `tests/specs/draft_compression.md`.
  - `tests/test_app_commit_failures.py`: removed `test_non_tip_commit_...` (the
    non-tip guard it exercised is gone); updated the module docstring. Streaming +
    range-containing-K failure triggers still covered.
- Tests — new (the PRD acceptance floor):
  - `tests/test_reconstruction.py` (+3, M1/M2/M3): the middle sequence
    U1,A1,U2,A2 → compress [U1,A1] → U3,A3. A2 drifts (`has_drift` True,
    gen=[U1,A1,U2] verbatim, now=[K,U2]); the changed diff region is
    left=[U1,A1]/right=[K]; A3 born-after-K does NOT drift (gen folds K =
    [K,U2,A2,U3], never U1/A1 — "next turn reads the summary, not the children").
    (Note: A3's prefix includes its own U3 — the recorded gen is 4 nodes, not 3.)
  - `tests/test_app_diff_view.py` (+1 Pilot): `test_middle_compress_earlier_turn_drifts`
    — middle-compress via the real editor (range NOT ending at the tip), then `g d`
    on A2 shows the single changed region left=[U1,A1]/right=[K], warning False,
    DiffView shown / MessageList hidden. New `_middle_compress_scenario` helper
    returns the folded (off-view) child ids captured before the compress.
- Verification: `scripts/check.sh` green (615 passed; was 612). ruff+mypy clean.
  NO live qa-tester: task 22's core+UI edits are same-iteration; the MCP harness runs
  `ctx.*` cached in-process and can't see them (AGENTS.md limit a). The Pilot +
  reconstruction unit tests are the correct verification (matches tasks 19/20/21).
  The qa-tester leg of the acceptance is folded into task 23's end-to-end pass.
- Gotcha for task 23 (final qa-tester verify-feature): middle compress is now a live
  path — drive a continued conversation, middle-compress an early range, confirm later
  turns read coherently and the earlier turn's `g d` diff shows what it saw (left=
  originals, right=K). Drift markers now legitimately appear on non-tip turns.

## 2026-07-03 — Task 23: Sprint 3 end-to-end verification (qa-tester, verify-feature)

- No code changes (verification-only task). Ran two sequential `qa-tester`
  verify-feature passes against the live `HarnessApp` (deterministic `TestProvider`,
  fresh temp workspace per launch). Config is read LIVE from `~/.config/ctx/config.json`
  (no caching, `ctx/core/config.py::get_config`), so config-override checkpoints were
  set from the main agent by writing that file before each pass; the file did NOT exist
  before and was REMOVED after (clean state restored).
- Pass A (config: custom `compression.default_prompt` = "CUSTOM_QA_MARKER…" + drift ON):
  ALL 7 checkpoints PASS — (1) config prompt reached editor prefill; (2) tip compress
  draft→edit→commit + deep-dive/`Ctrl+o`/`i`; (3) middle compress, later turns coherent,
  A2 `drift:true` / A3 `drift:false`; (4a) diff overview+drill left=[U1,A1]/right=[K],
  warning False; (4b) post-expand drift reverses direction, diff shows correctly;
  (5) expand→re-compress overlapping range commits (empty-summary correctly rejected);
  (6) `/new`+`/resume` SQLite round-trip preserved K/originals/weights; (7)
  `textual_check_errors` clean throughout.
- Pass B (config: `ui.show_context_drift: false`): drift `Δ` markers correctly
  suppressed on all nodes (PASS — this is the "disappear" half of checkpoint 3).
- Harness constraints handled: full process restart is not testable (each launch gets a
  fresh `tempfile.mkdtemp` workspace, `tools/agent/harness.py`), so checkpoint 6
  persistence was exercised via `/new`+`/resume` (save→load through SQLite in the same
  process/tempdir) rather than a real restart — noted, meaningful round-trip either way.
- Verification: `scripts/check.sh` green at start of iteration (615 passed); no code
  touched this iteration, so still green. Config file removed post-run.

### Findings triaged (NOT patched here — filed as new tasks 24/25/26 per task 23's rule)
- NOT a defect: `v` range-select re-anchors on every press (by design,
  `ctx/ui/app.py:338` "a fresh press re-anchors at the cursor"). Correct mechanic is
  `v` once → move cursor with up/down to extend → `c`. My first pass-A brief had the
  wrong "v…v" mechanic; qa-tester self-corrected. Nothing to fix.
- Task 24 (consistency): `g d` diff drill uses `reconstruction.has_drift` DIRECTLY
  (`ctx/ui/app.py:427`), NOT the config-gated `_node_drift`, so the diff view opens on a
  drifted assistant turn even with `show_context_drift:false`. Config docstring is
  marker-scoped so this may be intended → task 24 is DECIDE-then-align, not a blind fix.
  Note: PRD checkpoint 3 only requires MARKERS to disappear (they do) — this passed.
- Task 25 (cosmetic, unconfirmed): qa-tester saw `Δ` seemingly overlapping the weight-%
  digit (`2Δ%`) in character-grid screenshots. Both `.weight`/`.drift` are `dock:right`
  (`message_list.css:28-40`) which should stack, and AGENTS.md limit (b) says the harness
  can't judge layout → task 25 is confirm-then-fix-if-real.
- Task 26 (QA tooling): `tools/agent/snapshot.py::render()` surfaces none of the Sprint 3
  `describe_state` fields (`drift`, `diff_view`, breadcrumb, `context_gauge`,
  `range_selection`), forcing screenshot inference this pass. Extend the renderer.

### Gotcha for future iterations
- To test config-dependent UI in qa-tester: write `~/.config/ctx/config.json` from the
  MAIN agent BEFORE spawning qa-tester (qa-tester has no Write). `get_config()` reads
  live, so no relaunch needed for the flag to take effect on the next action — but you
  cannot change it mid-run, so one config state per qa-tester pass. ALWAYS restore
  (delete if it didn't exist) afterward — it's the real user config, not a repo file.

## 2026-07-03 — Task 24: gate `g d` diff view on `ui.show_context_drift`

- DECISION (the DECIDE-then-align call): the flag gates *all* drift UI, not just
  the passive `Δ` marker. Rationale — with drift off there is no marker signalling
  that any turn drifted, so it's incoherent for the active `g d` drill to still open
  the full-screen diff on a turn the UI otherwise presents as undrifted. The K
  deep-dive branch of `g d` is untouched (that's compression navigation, not drift).
- Implementation: extracted a shared predicate `_turn_has_drift(node, all_nodes)`
  in `ctx/ui/app.py` that returns `False` for non-assistant roles, for undrifted
  turns, and for *every* node when `ui.show_context_drift` is off; otherwise
  `reconstruction.has_drift`. Both `_node_drift` (maps it over the view; keeps its
  own early-return so `get_config()`/`all_nodes()` aren't re-hit per node) and
  `_drill_selected`'s assistant branch now route through it. Previously the drill
  called `reconstruction.has_drift` directly (`app.py:427`), bypassing the gate.
- Docs aligned: `ctx/core/config.py` docstring widened from "marks" to "surfaces
  (marker + `g d` diff drill)"; AGENTS.md updated to describe the shared predicate.
- Test: added `test_gd_diff_is_noop_on_drifted_turn_when_config_disabled` to
  tests/test_app_drift.py — drift off, cursor on the drifted A2, `g d` →
  `describe_state()["diff_view"]["open"] is False`. A regression re-introducing the
  ungated drill would survive without it. The existing test_app_diff_view.py already
  locks the positive (drift on → diff opens).
- Verification: `scripts/check.sh` green (616 passed; was 615). ruff+mypy clean.
  NO qa-tester: same-iteration UI edit, MCP harness runs `ctx.*` cached in-process
  and can't see it (AGENTS.md limit a) — Pilot test is the verification (as tasks
  19–22). Remaining Phase 3c tasks: 25 (Δ vs weight-% layout), 26 (snapshot.py render).

## 2026-07-04 — Task 25: drift `Δ` vs weight-% layout (CONFIRMED REAL + fixed)

- CONFIRMED the overlap is real (not a character-grid artifact). Investigated via
  computed regions in a Pilot app: `.weight` "20%" occupied cols x=76,77,78 while
  `.drift` "Δ" landed at x=77 — squarely inside the % text, so the coarse grid
  rendered "2Δ%" (Δ overwrites the 0). Root cause: `.weight` and `.drift` were each
  `dock: right`, and Textual stacks multiple same-edge docks *on top of each other*,
  not side-by-side; the `.drift` `margin: 0 1 0 0` only nudged Δ one cell left
  (x=77), still inside `20%`.
- Fix: wrap both `Static`s in a single right-docked `.meta-slot` Horizontal row
  (`layout: horizontal`) so they flow left→right within it — drift first (left),
  weight second (right), the `.drift` right-margin giving a 1-cell gap. Removed
  `dock: right` from `.weight`/`.drift`. After: Δ at x=74 (right=75), weight at
  x=76 → no overlap for any weight width (verified "20%" and "100%").
- Test: new `tests/test_message_list_meta_layout.py` — mounts a `MessageWidget`,
  sets drift + weight, asserts `drift.region.right <= weight.region.x` (no column
  overlap, Δ left of %) for a 2-char and a 4-char weight value. This is the layout
  invariant AGENTS.md limit (b) says must live in a unit test, not qa-tester.
- Verification: `scripts/check.sh` green (618 passed; was 616). ruff+mypy clean.
  NO qa-tester: (a) same-iteration UI edit is invisible to the cached in-process
  MCP harness, and (b) the harness can't judge layout anyway — the region test IS
  the verification (same rationale as tasks 19-24).
- Remaining Phase 3c: task 26 (snapshot.py::render surfacing Sprint 3 fields).

## 2026-07-04 — Task 26: surface Sprint 3 state in snapshot.py::render() (FINAL)

- Extended the pure QA renderer (`tools/agent/snapshot.py`) to emit the five
  `describe_state()` fields it dropped, so agents read structured state instead of
  inferring from screenshots (AGENTS.md limit b):
  1. per-node `drift` → a `Δ` glyph appended AFTER the file/weight suffixes (last
     non-space char on the node line); omitted when drift false/absent.
  2. `context_gauge {pct, approximate}` → a `ctx: <marker><pct>%` line; `~` marks
     approximate, `?` is the neutral placeholder when pct is None; omitted when the
     key is absent.
  3. `range_selection` → a byte-exact `range=[i,j,k]` segment on the nodes header
     (mirrors `selected=[…]`, which is driven by top-level `selected_index`, NOT the
     per-node `selected` flag — the blind author guessed `selected=True`; corrected).
  4. `deep_dive.breadcrumb` → a `nav: a > b > c` line, OMITTED at the lone root
     `["Chat"]` / empty / absent (noise rule).
  5. `diff_view` → a `diff: <n> regions [warn] [drill]` line iff `open`; region count
     = len(regions), warn/drill indicators toggle with their flags.
- All new top-level lines sit before the `nodes=` header; each omitted when its data
  isn't meaningful, so the fixed line order + cheap-diff property (C24) hold. The 618
  existing snapshot/app tests stayed green throughout.
- Tests: code-blind flow. test-spec-author wrote contract CS1–CS26
  (`tests/specs/snapshot-sprint3.md`, additive to snapshot.md) + 23 cases
  (`tests/test_snapshot_sprint3.py`) from intent only. Confirmed red (15 behavior
  fails, 8 omit-cases already green, clean collection) before implementing.
  TWO blind-wiring fixes (test-infra carve-out, NOT weakening): CS4 used a `weight`
  key → corrected to `weight_pct` (the real key/int); CS16 used per-node
  `selected=True` to drive the header → corrected to top-level `selected_index=0`.
  Spec items CS4/CS16 updated to match.
- Verification: `scripts/check.sh` green (641 passed; was 618). ruff+mypy clean.
  NO qa-tester: `render()` is a pure presentation fn in `tools/agent` (outside the
  shippable ctx package, ADR 0012) with no UI/runtime surface to drive — the
  code-blind unit tests + green gate ARE the verification (step 7 carve-out).
- Kept the Sprint 3 contract as a separate `snapshot-sprint3.md` (self-labelled
  "additive to snapshot.md") rather than folding it in — avoids reflowing the
  existing mutmut-survivor analysis section; the new test file cites it directly.

### PRD COMPLETE
- All 26 tasks are now `- [x]`. This was the final Sprint 3 task.

## 2026-07-04 — Seed: Phase 3d (post-sprint review hardening, not a task)
- Sprint 3 (all 26 tasks) was reviewed by a three-agent adversarial pass over the
  full `develop...feat/compression` diff: core semantics vs ADR-0016 (15 executable
  probes), UI state machine (6 Pilot probes with real keypresses), and test
  integrity (incl. a live mutant re-run of the task-13c claim — verified).
- Overall verdict: the core conforms to ADR-0016 (event-only resolution, Q14 as-of
  rule, created_seq/H6, ctx_hash oracle all held under probing); the 13a–13i
  hardening is genuinely implemented; PROGRESS claims are trustworthy with ONE
  exception (task 22's "extended oracle" — see task 29).
- Filed tasks 27–32 (Phase 3d). The big two: the diff view never inherited the
  deep-dive read-only gates (`c`/`v`/`x` act under an open diff — task 27), and
  H2's `_streaming` flag starts one tick after `submit()` stamps the assistant
  seq, leaving the exact window ADR-0016 A#3 §2 forbids (task 28).
- Probe tests preserved in `scripts/ralph/probes/` (README there explains which
  are red-by-design and which must be INVERTED when their bug is fixed). They are
  outside the pytest gate (`testpaths=["tests"]`) but pass ruff+mypy. Promote
  into `tests/` as tasks land; delete the directory when Phase 3d completes.
- Gotcha: `test_review_hazards.py` currently FAILS by design — do not "fix" the
  probes to green without fixing the app; the failing assert IS the acceptance.

## 2026-07-04 — Task 27: diff view inherits the deep-dive read-only gates

- What: `action_anchor_range` (`v`), `action_compress` (`c`), `action_expand`
  (`x`) gated only on `self._deep_dive_stack`, not on an open diff view. With a
  diff open, focus sits on `DiffView` (not a text input), so these keys bubbled
  to the App bindings and acted under the diff: `c` opened the compression editor
  over the diff, `v` set an invisible anchor on the hidden message list (making
  the first Esc a dead keypress), `x` ran expand under the diff. Fix: added a
  shared predicate `ChatApp._in_full_screen_inspection()` → `bool(_deep_dive_stack)
  or _diff_view is not None`, and swapped the three `if self._deep_dive_stack:`
  gates to call it. One helper so the next full-screen view can't repeat this.
- Why the Esc fix falls out for free: with `v` now inert in a diff,
  `_range_anchor_id` stays None, so `action_escape`'s range-clear branch
  (`app.py:217`) is skipped and control reaches the diff-pop branch (`:223`) —
  no change to Esc ordering needed.
- Tests: promoted 4 of the 6 red probes from
  `scripts/ralph/probes/test_review_hazards.py` into `tests/test_app_diff_view.py`
  (house style — real keypresses, `describe_state()`/state asserts), renamed to
  positive assertions: `test_c_in_diff_view_is_a_noop`,
  `test_v_in_diff_view_does_not_anchor_and_first_esc_pops`,
  `test_x_in_diff_view_does_not_mutate`,
  `test_c_then_commit_in_diff_commits_nothing`. Reused the file's existing
  `_drift_scenario` / `_middle_compress_scenario` helpers. Removed those 4 probes
  from the probes file (+ its now-unused `CompressionEditor` import) and updated
  the probes README; the 2 remaining probes (tasks 30/31) stay red by design.
- Verification: `bash scripts/check.sh` green (ruff + mypy + 645 pytest). No
  qa-tester (in-process harness can't see this iteration's uncommitted edits; the
  4 deterministic Pilot tests are the acceptance floor per the PRD UI-task note).
- Gotcha for future iterations: tasks 30 (`test_diff_can_open_inside_deep_dive`)
  and 31 (`test_model_command_mounts_into_dive_frame`) are still red probes — do
  not "fix" them to green without their app fix. `_in_full_screen_inspection()`
  is now the canonical read-only gate; reuse it for any new selection/mutation
  action rather than re-checking the stack/diff by hand.

## 2026-07-04 — Task 28: close the H2 submit→first-tick window + UI commit guard

- Bug: `_streaming` flipped True only at `stream()`'s first `__anext__`
  (`conversation.py`), but the assistant node's `created_seq` is stamped earlier,
  in `submit()`. A commit/expand/draft landing in that event-loop gap was accepted
  — it gets `created_seq > seq(T)` yet folds into the context actually sent at the
  first tick, so `context_at_generation(T)` disagrees with `T.meta["ctx_hash"]`
  (the undetectable-direction poisoning ADR-0016 A#3 §2 forbids).
- **Decision (Option A, per the PRD's first choice):** set `self._streaming = True`
  at the end of `submit()` — the turn is in flight from the moment its seq is
  stamped. `stream()`'s `finally` clears it (unchanged). Chose A over Option B
  (pending-tip detection) because it's the ADR's literal "a turn is in flight"
  model, reuses the *single* `streaming` guard that `commit`/`expand`/`draft`
  already consult (all three now reject across the whole window), and the UI never
  reads `core.streaming` so there's zero UI regression.
- **Unwind of the "submit never followed by stream()" path** (tests-only today):
  `new_conversation()` and `resume_conversation()` reset `_streaming = False` — a
  fresh/switched conversation abandons any orphaned in-flight turn, so a stuck flag
  can't leak. Recorded in an ADR-0016 A#3 §2 implementation note + AGENTS.md.
- UI half: `action_commit_compression` (`ctx/ui/app.py`) now refuses `Ctrl+S`
  while `_stream_worker` is live via an explicit check (mirrors `action_expand`),
  breadcrumbing "Cannot commit while a response is streaming." instead of relying
  on the core `ValueError` catch below it.
- Tests (no code-blind flow — no new interface; the contract was pinned exactly by
  ADR-0016 A#3 §2 + the inverted probe):
  * Inverted the probe `test_h2_window_between_submit_and_first_tick` into
    `tests/test_commit_compression.py::test_events_rejected_in_submit_to_first_tick_window`:
    after a bare `submit()`, `streaming is True` and commit/expand/draft on an
    earlier already-streamed range all raise `ValueError`, nothing mutates, and the
    same commit succeeds once the turn is drained (proves it's the window, not a
    permanent lock). Removed the probe from `test_adversarial_core.py` + README.
  * Tightened `test_app_commit_failures.py`'s streaming-breadcrumb assertion to the
    exact UI-guard message (locks "via the UI guard, not the core exception").
- **Deliberate test-infra adaptation (NOT weakening):** six `c9x` setup-only tests
  in `tests/test_conversation.py` (C91/C92/C94/C95/C96/C99) used `submit()` twice
  *without streaming* purely to build settled graph state, then compress/rewind/
  expand. With `submit()` now correctly marking in-flight, that setup left the core
  streaming and the compress/rewind raised. Fix: made them `async` and drain each
  turn (`await _collect(core.stream(a))`) like `_build_line`/real usage do — all
  assertions unchanged. These are the C81–C90-family "build state directly" tests
  the PRD flagged as representation-coupled; the change is setup ceremony, not the
  contract.
- Verification: `bash scripts/check.sh` green (ruff + mypy + 646 pytest, was 640).
  No qa-tester: the in-process MCP harness can't see this iteration's edits
  (AGENTS.md limit a), so the updated Pilot test is the UI acceptance floor.
- Gotcha for future iterations: `core.streaming` is now True from `submit()`, not
  just during token flow. Any NEW test that submits without streaming and then
  mutates the graph (commit/expand/draft) OR asserts `streaming is False` right
  after submit must drain the turn first. `draft_compression` still does NOT set
  `_streaming` (parking-lot item (f)) — task 28 scoped only the submit→tick window.

## 2026-07-04 — Task 29: extend the ctx_hash oracle to middle compression

- Gap (review finding): task 22's PROGRESS claimed the task-17 oracle suite was
  extended with a middle sequence, but `tests/test_ctx_hash_oracle.py` only ever
  had tip-ending compression ranges. Every existing checked turn was
  *non-discriminating* against a bug where `context_at_generation` returns the
  now-prefix, because a tip K never folds material inside an earlier
  already-generated turn's strict-ancestor prefix, so gen-view == now-view for
  every checked turn.
- **CORRECTION to the 2026-07-04 task-22 PROGRESS entry:** the sentence claiming
  the ctx_hash oracle suite was extended with a middle sequence was inaccurate —
  no such case existed until this task. The task-22 *code* (middle compression,
  deleted 3a tip guard) was correct and stands; only its test-coverage claim was
  overstated. This entry closes that gap.
- Added two differential-oracle cases (authored against the public core API, not
  the blind flow — this file is a cross-derivation oracle by design):
  * `test_oracle_holds_for_middle_compression`: U1,A1,U2,A2 → compress the MIDDLE
    range [u1,a1] into K → U3,A3 → `_check_oracle` over ALL assistant turns. A2 is
    the discriminating turn — generated verbatim ([u1,a1,u2]) before K existed, but
    its now-view folds [u1,a1] into K ([K,u2]); asserted via `has_drift`.
  * `test_oracle_holds_through_middle_expand_recompress`: middle compress → expand
    (E event) → re-compress the same range into K' → U3,A3, `_check_oracle` at each
    stage; A2 still discriminates (K expanded, K' applies).
- **Discrimination proof (acceptance):** temporarily made `context_at_generation`
  `return now_prefix(...)` — both new cases (and one existing tip case) went RED;
  reverted the mutant (NOT committed; `git diff ctx/core/reconstruction.py` empty).
- Verification: `bash scripts/check.sh` green (ruff + mypy + 648 pytest, was 646).
  No qa-tester — pure core-logic test task, no UI/runtime surface.
- Gotcha: middle-compression discrimination requires a checked turn whose K folds
  *inside its strict-ancestor prefix* (gen-view != now-view). Tip-K cases can't do
  this — keep at least one middle case if the oracle is ever pruned.

## 2026-07-04 — Task 30: diff/deep-dive exclusivity + cursor restore

- **Decision (the task asked to decide first): diff-inside-dive is FORBIDDEN.**
  It contradicts the documented mutual-exclusivity invariant (`app.py:115-119`
  `_diff_view` comment) and the review probe already asserted the forbidden
  behavior (`assert not diff_view["open"]`). A nested diff would also break the
  `action_pop_deep_dive` close ordering and the breadcrumb (`Chat › K… › Diff…`).
  Rejected the "legitimate stack level" reading — it's the bigger change and
  reopens a settled invariant.
- Fix (1): `_drill_selected` now gates the diff branch on `_deep_dive_stack` — a
  drifted *frame* assistant turn is a **silent no-op** while diving (not a
  breadcrumb; consistent with the task-27 read-only v/c/x gates, which also just
  `return`; a breadcrumb would add a persistent system node to the conversation).
  The compression branch (nested K dive) is left intact (nesting-ready; 3a depth
  stays 1 so it's inert in practice).
- Fix (2): `_close_diff` restores the cursor via `_visible_nodes()` instead of
  `core.nodes` membership (symmetric with `action_pop_deep_dive`). Under the
  exclusivity gate the dive stack is always empty when a diff closes, so this
  equals `core.nodes` today — but it stays correct if the invariant ever changes,
  and `_select_message` already re-shows the inspector, so cursor + inspector both
  restore.
- Tests (Pilot, authored directly — UI layer, not the code-blind core flow):
  * `test_diff_does_not_open_inside_deep_dive`: promotes the review probe
    (double-compress K1/K2 → dive K2 → cursor on frame A2). Asserts A2 genuinely
    drifts (`_turn_has_drift is True`) so the test can only pass because the gate
    blocks it, then that `g d` leaves the diff shut, the dive active, and no
    "Diff" breadcrumb.
  * `test_ctrl_o_from_diff_restores_cursor_and_inspector`: opens a diff from the
    live view, `ctrl+o`, asserts `selected_index`/`selected_role` and
    `detail.node_index`/`node_role` all restore to the pre-diff assistant turn
    (the existing `test_ctrl_o_restores_live_view` only checked pane display).
- Verification: `bash scripts/check.sh` green (ruff + mypy + 650 pytest, was 648).
  No qa-tester: the in-process MCP harness can't see this iteration's app.py edits
  (AGENTS.md limit a), so the new Pilot tests are the UI acceptance floor.
- Gotcha: the review probe file `scripts/ralph/probes/test_review_hazards.py` is
  KEPT — task 31 still needs its `test_model_command_mounts_into_dive_frame`.

## 2026-07-04 — Task 31: gate the remaining direct add_node appenders (13h#2 completion)

- Fix: routed the three command handlers that still appended widgets directly
  through the dive-gated `_mount_node` (which is a no-op while `_deep_dive_stack`
  is non-empty and lets exit-dive rebuild self-heal):
  * `_handle_model_command` (both query + switch forms) — was `add_node`.
  * `_handle_resume_command`'s no-conversations branch — was `add_node`.
  * `_handle_include_command` (no-files node + the per-file loop) — was `add_node`;
    dropped the now-unused local `message_list`.
- Sweep `grep -n add_node ctx/ui/app.py` now shows only 4 sites, all gated:
  `_rebuild_message_list` (778, clear-then-rebuild from `_visible_nodes()`),
  `_mount_node` itself (791, the gate), `_handle_new_command` (1312) and
  `_handle_resume_command`'s full path (1337) — the latter two both call
  `_reset_transient_ui()` (which `.clear()`s the dive stack, app.py:670) before
  clearing children and rebuilding, so no mount lands in a live dive frame.
- Test (Pilot, authored directly — UI layer): promoted the throwaway probe
  `test_model_command_mounts_into_dive_frame` into
  `tests/test_app_deep_dive_hardening.py::test_model_command_gated_out_of_dive_then_surfaces`.
  Per the acceptance it uses the **switch** form `/model gpt-test` (not the probe's
  query form), drains the connectivity worker too, asserts the dive `MessageWidget`
  count is unchanged mid-dive, then asserts the "Model set to: gpt-test" breadcrumb
  is visible in the live view after `ctrl+o`.
- Deleted the throwaway `scripts/ralph/probes/test_review_hazards.py`: both its
  probes are now promoted (`test_diff_can_open_inside_deep_dive` → task 30's
  `test_diff_does_not_open_inside_deep_dive`; the model one → this task). The
  probes dir is NOT in pytest `testpaths` (["tests"]), so it was never collected.
  `bench_drift.py` and `test_adversarial_core.py` remain (bench_drift feeds task 32).
- Verification: `bash scripts/check.sh` green (ruff + mypy + 651 pytest, was 650).
  No qa-tester: the in-process MCP harness can't see this iteration's app.py edits
  (AGENTS.md limit a), so the new Pilot test is the UI acceptance floor.
- Gotcha: `_mount_node` re-queries `MessageList` per call, so the include loop now
  does one query per file (was hoisted). Negligible; kept for a single gated seam.

## 2026-07-04 — Task 32: cache the per-refresh drift computation
- `_node_drift` (`ctx/ui/app.py`) re-folded the whole graph per assistant node
  (`reconstruction.has_drift`, O(n²)) on every `_refresh_token_ui` AND every
  `describe_state()`. Added a UI-layer memo: `_drift_signature()` returns a cheap
  key `(conversation_id, len(all_nodes), max created_seq, len(core.nodes),
  show_context_drift)`; `_node_drift` returns the cached `list[bool]` when the
  signature matches, else recomputes and stores. `ctx/core/reconstruction.py`
  stays pure (untouched).
- Why the key works: graph is append-only, so any K/E/turn insertion bumps
  `len(all_nodes)`/`max created_seq`; a rewind shortens `core.nodes`; `/new`/
  `/resume` swap `conversation_id`; the flag flip is in the key. Streaming grows
  node *content* only (drift is structural), so the cache correctly survives an
  in-flight stream — no spurious invalidation. Auto-invalidating; no manual reset.
- Tests: new `tests/test_app_drift_cache.py` (2 Pilot tests) is the acceptance
  floor — monkeypatch-counts `reconstruction.has_drift`: cold pass recomputes,
  a consecutive `describe_state()` on an unchanged graph does NOT, and a new
  commit (K enters graph) does. Reused `_drift_scenario` from `test_app_drift.py`.
- Gotcha: the scenario's own `_refresh_token_ui` warms the cache, so the test
  sets `app._drift_cache = None` for a known cold baseline before arming the
  counter — otherwise the first `describe_state()` is already a cache hit (count 0).
- Gotcha: tests/ is not a package — import helpers as `from test_app_drift import …`
  (bare, not relative), matching the pytest rootdir sys.path insert.
- Verification: `scripts/check.sh` green (653 tests, ruff+mypy). Behavior-preserving
  (drift markers/diff unchanged), so no qa-tester. The cited bench probe
  (`scripts/ralph/probes/bench_drift.py`) measures the raw reconstruction cost that
  motivated this; the memo proof is the call-count unit test, not the probe.
- **All PRD tasks (1–32) are now `- [x]`.**

## 2026-07-06 — Task 33: clear the stuck `_streaming` flag on a pre-stream failure
- Fix (`ctx/core/conversation.py` `stream()`): the context-build region
  (`build_context` → loader I/O, `hash_context`, `count_messages`) ran BEFORE the
  `try` whose `finally` cleared `_streaming`, so any raise there left the flag stuck
  True → every later `commit/draft/expand_compression` raised "cannot … while
  streaming" until `/new`/`/resume`. Wrapped the whole body in an outer `try/finally`
  (flag lowered on ANY exit) and kept an **inner** `try/except/else` for persist —
  so a pre-stream build failure clears the flag but does NOT persist the empty
  assistant node (submit already persisted the user tip; resume still lands cleanly
  on the user turn). Framework-free; core-only.
- Test (code-blind flow, `test-spec-author`): new `tests/test_stream_streaming_flag.py`
  (1 test) + `tests/specs/conversation_streaming_flag.md`. Asserts public invariant
  only: after a raising context build, `core.streaming is False` and a subsequent
  `commit_compression` on a 1-node range succeeds.
- **Test-infra correction (not a weakening):** the blind author injected a loader
  raising `OSError`, but `build_context` deliberately **swallows** `OSError/ValueError`
  (renders an error placeholder, `ctx/core/context.py:52`) — so that never reaches
  stream()'s pre-region. Changed the loader to raise `RuntimeError` (a type
  `build_context` propagates) to model a genuine context-build failure; all observable
  assertions kept. Also fixed the author's import path (`ctx.core.conversation`) and
  tightened `pytest.raises(Exception)` → `RuntimeError` (ruff B017).
- Red/green proof: with the fix stashed, the test fails at `assert core.streaming is
  False` (flag stuck True); with it restored, green. Genuine regression net.
- Verification: pure core change, no UI/runtime surface → no qa-tester, no render
  (PROMPT step 7). `bash scripts/check.sh` green (663 passed, was 662).
- Gotcha for a future iter: an unreadable `/include`d file does NOT trigger this path
  (build_context catches it); the realistic real-world trigger is a `count_messages`
  failure. The invariant (any pre-stream raise clears the flag) is what the test locks.

## 2026-07-06 — Task 34: build_context never emits two adjacent same-role messages
- Fix (`ctx/core/context.py`): the task-15 "coalescing boundary" rule reset a
  `coalescing` flag to False on any dropped node (system breadcrumb), so
  `[user, dropped-system, user]` emitted TWO adjacent `{"role":"user"}` dicts —
  which Anthropic-family providers (via litellm) reject. Also the merge `+=` glued
  blocks with NO separator, running `</conversation_summary>` straight into the next
  user text. Rewrote the emit boundary: **always** merge user-role material into the
  previous message when the last emitted dict is already user, joining with an
  explicit `\n\n` separator; only an assistant message breaks the run. Deleted the
  `coalescing` flag entirely (now redundant — "is the last dict user?" is the sole
  condition). The `\n\n` separator preserves the "separate runs" intent while the
  no-two-adjacent-same-role output invariant now always holds. Pure/framework-free.
- Tests (code-blind flow, `test-spec-author`): new `tests/test_context_role_alternation.py`
  (4 tests) + `tests/specs/context_role_alternation.md`. Every test runs
  `_assert_alternating` (no adjacent same-role dicts) plus: (C1) dropped node does
  NOT split a user run → 1 dict; (C2) K then user → 1 dict, separator between the
  closing tag and the text; (C3) two user nodes → exact `a\n\nb`; (C4) assistant
  splits into two user dicts. Red proof: C1–C3 failed against old code (2 dicts /
  no separator), C4 passed (unchanged), clean collection.
- **Deliberate existing-test change (not a weakening):** `test_compression_node.py`
  C11 + its spec (`tests/specs/compression_node.md` C11) and `tests/specs/context.md`
  C24 all encoded the OLD "dropped node is a coalescing boundary → 2 dicts" behavior
  that task 34 explicitly reverses. Updated them to the new contract (1 merged dict
  with separator), citing task 34. These were the *reversed* behavior, not the
  invariant under test — updating them is the task, not defeating the blind author.
- Verification: pure core change (`ctx/core/context.py`), no UI/runtime surface →
  no qa-tester, no render (PROMPT step 7). `bash scripts/check.sh` green (667 passed,
  was 663). Ruff flagged the authored `zip(...)` missing `strict=` — added `strict=False`.
- Gotcha: this changes `build_context` output → shifts `hash_context` digests and
  token counts, but those are computed live from `build_context`, so nothing pins a
  stale value; the full suite stayed green. `tests/specs/context.md` C24 had no
  enforcing test (spec-only), so only the prose needed updating.

## 2026-07-06 — Task 35: reset `_last_drafted_prompt` on draft cancel/failure
- Fix (`ctx/ui/app.py`): `action_draft_compression` stamps `_last_drafted_prompt`
  BEFORE the worker runs so a later `Ctrl+S` can mark an AI-drafted K. But nothing
  cleared it when the draft was cancelled (Esc) or errored, so a user who then
  hand-wrote a summary and committed stamped the STALE prompt → K read as
  AI-drafted, corrupting the manual-vs-drafted distinction. Cleared
  `_last_drafted_prompt = ""` in `_draft_compression_worker`'s `CancelledError`
  and `Exception` handlers, plus a defensive clear in `_close_compression_editor`
  (belt for any close path that skips the worker handlers). The commit path reads
  the prompt BEFORE calling `_close_compression_editor`, so the drafted-commit
  case (task 9's `test_ctrl_s_after_draft_stamps_drafted_prompt_on_k`) is unaffected.
- Test (Pilot, mandatory floor): new `tests/test_app_draft_prompt_reset.py` (2
  tests). (1) cancel path — blocking provider, `Ctrl+D` with a custom Top prompt,
  Esc to cancel the live worker (editor stays open), hand-write summary, `Ctrl+S`
  → `K.meta["prompt"] == ""`. (2) failure path — erroring provider raises
  mid-stream, then a hand-written commit → `K.meta["prompt"] == ""`. Both assert
  `K.content` is the hand-written text too. Authored directly (not via
  test-spec-author): a 4-line mechanical guard with an existing precedent
  (`test_app_draft_worker_lifecycle.py`'s `_BlockingProvider`); assertions come
  straight from the acceptance criterion, not implementation shape.
- Red/green proof: both tests failed on old code with `assert 'focus on the
  decisions' == ''`; green after the fix.
- Verification: deterministic queryable state (K meta), no visual surface → Pilot
  test IS the verification (PROMPT step 7 — no qa-tester, no render). Full gate
  `bash scripts/check.sh` green (669 passed, was 667).
- Gotcha: the failure path only clears — it does NOT reopen/reset the editor, so a
  user can still hand-commit after a failed draft (intended). The commit's prompt
  read precedes the close-clear, so ordering matters if that ever changes.

## 2026-07-06 — Task 36: extract a shared compact message-row renderer (`MessageRow`)
- Refactor (behavior-preserving): the compact two-line row rendering lived inside
  `MessageWidget` (coupled to `MessageList`); tasks 37/38 need to render nodes as
  the same compact rows in the diff panes and inspector splits. Extracted the row
  rendering into a new thin UI widget `ctx/ui/widgets/message_row.py::MessageRow`
  (takes a `Node`; draws the palette-colored left bar tall/solid, applies per-role
  truncation, composes the right-docked drift+weight meta slot + content — Markdown
  for turns, Static for system/context; `update_content`/`set_weight_*`/`set_drift`).
  It sets **no id** unless the caller passes one, so the same node can appear in
  more than one pane without an id collision (the blocker for 37's two panes).
- `MessageWidget` now **subclasses** `MessageRow`, adding only the list-specific
  state: `set_selected`/`set_range_selected`/`set_new_pass` + the `msg-<id>` id.
  `_pass_starts`/`_SIDE` stay in `message_list.py` (pass margins are list-only).
- CSS (`message_list.css`): retargeted the shared rules (padding/margin/overflow,
  role-italic, `.content`, Static/Markdown, `.meta-slot`/`.weight`/`.drift`) from
  `MessageWidget` to the `MessageRow` type selector; kept list-only rules
  (`.pass-start` margin, `.selected`, `.range-selected`, `MessageList` scrollbar) on
  `MessageWidget`/`MessageList`. **Key risk verified:** Textual type selectors match
  a widget's base-class names, so `MessageRow` rules cascade to the `MessageWidget`
  subclass — confirmed deterministically by the pre-existing
  `test_message_list_meta_layout` (asserts `.meta-slot` dock/layout on a
  `MessageWidget`) staying green, and by the visual render below.
- Tests: new `tests/test_message_row.py` (10 = 2 parametrized × 5 roles) — the
  acceptance floor exercising the *new* renderer on user/assistant/context/system/
  compression: (a) left-bar `_border_color` == palette color for the role; (b) the
  two-line layout (drift+weight meta slot present, content is Markdown for turns /
  plain Static for system+context). Authored directly (not test-spec-author): a
  behavior-preserving extraction where the acceptance IS the spec; the "renders
  identically" half is proved by the whole existing UI suite staying green.
- Verification: `bash scripts/check.sh` green (679 passed, was 669). Visual: rendered
  `committed-K` via `tools/agent/visual.py`, judged the main list against "compact
  two-line rows, role-colored left bars, right-docked weight/drift" — PASS (violet K
  bar / orange assistant bar, 61% / Δ 39% weight slots intact; identical to before).
  The violet K bar is expected here — recoloring it green is task 39, not 36.
- Gotcha for 37/38: mount `MessageRow(node)` (NOT `MessageWidget`) in the diff/
  inspector panes — `MessageWidget` forces the `msg-<id>` id and would collide with
  the live list's row for the same node. `MessageRow` shared CSS is in
  `message_list.css` (loaded app-wide via `CSS_PATH`), so it already applies anywhere.

## 2026-07-06 — Task 37: rebuild the diff view as a full-screen two-pane node diff
- UI rework (behavior contract unchanged): `DiffView` was a single-column
  `VerticalScroll` inside `#conversation` that replaced only the message list and
  laid out an *internal* was/now split of plain `[role] content` text; the left
  detail pane stayed visible, so it was neither full-screen nor compact-row.
- New `ctx/ui/widgets/diff_view.py`: a `Vertical` with a warning banner + a
  `#diff-overview` Horizontal of two side-by-side `.diff-pane`s — `#diff-left`
  ("was — context at generation") and `#diff-right` ("now — current context"),
  each a `VerticalScroll` of task-36 `MessageRow`s. Every region's `left` nodes go
  in the left pane, `right` nodes in the right pane (aligned by id via
  `diff_regions`); changed-region rows carry `.changed` (amber bg) and the cursored
  region's rows carry `.cursor` (brighter). `up`/`down` walk changed regions
  (`set_cursor`/`move_cursor` now iterate per-region row lists, `_region_rows`,
  instead of `#diff-region-N` ids). A separate `#diff-drill` Horizontal renders the
  cursored region's blocks **in full/untruncated** (task 21). Preserved the public
  API (`show`/`show_drill`/`close_drill`/`close`/`cursor`/`set_cursor`/`move_cursor`)
  and the `up`/`down` `delegate_nav` binding, so `describe_state()["diff_view"]`
  (computed in app.py from `self._diff_view`, not the widget) is unchanged.
- Full-screen: added `ChatApp._toggle_diff_fullscreen(on)` — hides/restores
  `MessageList` + `DetailInspector` + `#input-area`. Hiding the inspector lets
  `#conversation` (width 1fr) expand to full body width, so the DiffView (still
  inside it) spans the screen. `MessageList.display` still toggles (existing tests
  assert it). Wired into `_enter_diff`/`_close_diff` **and** `_reset_transient_ui`
  (the `/new`/`/resume` path also closes a standing diff — it previously restored
  only `MessageList`, leaving the inspector/input hidden; now fixed via the helper).
- `MessageRow` gained a keyword-only `truncate=True`; the diff *drill* passes
  `truncate=False` so a region's blocks render in full (task 21 fidelity).
- Tests: updated `_drill_text` helper in `tests/test_app_diff_view.py` (the old DOM
  `#diff-drill .diff-side` Static structure is gone — now reads `MessageRow._content`
  from `#diff-drill-left`/`-right`); added one Pilot test
  `test_diff_is_fullscreen_two_pane_compact_rows` asserting the new invariants
  (inspector+input hidden on open / restored on `ctrl+o`; panes render `MessageRow`s
  whose ids == `context_at_generation` (left) / `now_prefix` (right); `.changed`
  rows present). All other diff tests (open/close/drill/gates/exclusivity) unchanged
  and green — they key on `describe_state`, not the DOM.
- Verification: `bash scripts/check.sh` green (680 passed, was 679). **Visual**:
  rendered `drift-diff` at 160x48 via `tools/agent/visual.py`, `Read` the PNG —
  judged against "two side-by-side panes, compact two-line rows with colored left
  bars, changed region highlighted" → PASS (labels "was …"/"now …", one amber-
  highlighted compact row per pane with a colored left bar + `--%` slot, visible
  center divider, no inspector/input bar). **qa-tester**: verified the real-TUI
  flow (drift a turn → `g d` → full-screen two panes, inspector+input gone →
  `up`/`down` no-crash → `enter` drills → `ctrl+o` back to overview → `ctrl+o`
  closes + restores live list/inspector/input; `esc` close path too) — all PASS,
  `textual_check_errors` clean throughout.
- Gotchas for 38/44: diff panes mount `MessageRow(node)` (never `MessageWidget` —
  no `msg-<id>` id, so the same node can appear on both sides). The diff rows show
  a default `--%` weight slot (not wired in the diff); harmless but a future polish
  could suppress it. `_region_rows` is index-aligned with the full region list
  (incl. unchanged), `_changed_indices` selects the walkable ones. qa-tester note:
  to get a drifted later turn, submit BOTH turns first then compress+expand the
  earlier pair (compressing before the 2nd turn makes it fold on both sides → no
  drift, `g d` correctly no-ops).

## 2026-07-06 — Task 38: inspector splits render compact rows + visible dividers
- UI-only, thin adapter (core untouched). The committed-K detail inspector's
  central "Originals" (content) split used to render the folded children as one
  joined `**role**\n\ncontent` markdown-bold string via `Static.update`; now it
  renders them as the shared task-36 `MessageRow`s (colored left bar, two-line
  compact row), one per folded child. Added a visible divider between the three
  splits (Prompt / Originals / Summary).
- Changes:
  - `NodeView` gained `content_nodes: tuple[Node, ...] = ()` — the message-bearing
    nodes behind the content split. `content` (the joined text) is KEPT so the
    existing string assertions and `maximize_named`'s non-empty check stay valid;
    the rows are an *additional* view, not a replacement of `content`.
  - `ctx/ui/app.py::_node_view` passes `content_nodes=tuple(children)` for a K.
  - `DetailInspector.compose` adds `Vertical(id="detail-content-rows")` inside the
    content `_Split`; `_render_context` delegates the content split to a new
    `_render_content_split(view, text)` that mounts `MessageRow`s when
    `content_nodes` is present (via `remove_children()` + `mount_all(...)`, both
    queued on the pump — flushed by `pilot.pause()`), else shows the plain text
    (unchanged for file/context imports and the defensive "(no content)").
  - CSS: `border-bottom: solid $surface` on `#detail-prompt` and `#detail-content`
    (dividers between the three splits); `#detail-content-rows { height: auto }`.
- GOTCHA: the helper was first named `_render_content` — collides with a Textual
  `Widget._render_content` method (mypy override error). Renamed to
  `_render_content_split`. Don't reintroduce the bare name.
- Tests: added one Pilot test `test_k_inspector_originals_split_renders_compact_rows`
  (asserts `#detail-content-rows MessageRow` count == folded-children count, the
  plain-text Static is hidden, and `#detail-content` carries a `border_bottom`
  style). Existing `splits_visible == [prompt,content,output]` tests remain the
  structure floor and stayed green (they key on `content` string / splits_visible,
  both preserved).
- Verification: `bash scripts/check.sh` green (681 passed, was 680). **Visual**:
  rendered `k-inspector` (140x44) via `tools/agent/visual.py`, `Read` the PNG —
  judged against "Originals split shows compact rows with colored left bars + a
  visible divider between the three splits" → PASS (Originals shows "hello there"
  as a compact row with a colored left bar + `--%` slot; dashed horizontal
  dividers between Prompt|Originals and Originals|Summary). Pure rendering change,
  so no qa-tester (visual driver sees on-disk code by construction).
- Gotcha for 43: the inspector's Originals rows currently show a default `--%`
  weight slot; folded originals are "not in context" (Q9) — a future polish could
  call `set_weight_not_in_context()`, but task 38 left the default (out of scope).

## 2026-07-06 — Task 39: compression node color = context color (+ Σ glyph)
- UI/config-only, thin adapter. The K left bar was violet (`#a855f7`) while
  context imports are green (`#22c55e`), reading as unrelated node kinds. Changed
  the default `compression` palette color to `#22c55e` (== context) in
  `ctx/core/config.py`. Since a K and a file import now share a bar color, added a
  distinguishing **kind glyph** to the compression row: `MessageRow` now renders a
  `.kind` Static (glyph `Σ` = the "sum"/summary of a folded run) in the meta slot,
  for compression rows only.
- Changes:
  - `ctx/core/config.py` — `_DEFAULTS["colors"]["compression"]` → `#22c55e`.
  - `ctx/ui/widgets/message_row.py` — `_KIND_GLYPH = {"compression": "Σ"}`;
    `compose` yields `Static(glyph, classes="kind")` first in the meta-slot, only
    when the role has a glyph (so `.kind` exists on compression rows only — a clean
    queryable). Glyph is in the Greek block alongside the working drift `Δ`.
  - `ctx/ui/widgets/message_list.css` — `.kind` styling (mirrors `.drift`).
  - `tools/agent/visual.py` — task-39 FIXTURE intent sentence now mentions the Σ.
- GOTCHA: first tried glyph `≡` (U+2261) — it renders as a **tofu box** in the
  cairosvg render font (the font lacks it, even though `Δ`/`Σ` in the Greek block
  render fine). If you add another kind glyph, verify it isn't tofu by rendering,
  not just by the unit test (which only checks non-empty).
- Tests: added to `tests/test_message_row.py` — (1)
  `test_compression_row_carries_a_kind_glyph` (compression row has a non-empty
  `.kind`), (2) `test_context_row_has_no_kind_glyph` (a same-green context import
  does NOT — the glyph is the discriminator), (3)
  `test_snapshot_colors_line_shows_compression_equals_context_green` (the floor:
  `get_config` compression==context==`#22c55e` AND `render()`'s `colors:` line
  surfaces both as `#22c55e`). Wrote these directly (not code-blind): a 4-line
  palette+glyph change with a precisely-specified floor; the blind author is
  overkill here. `test_visual_states.py` k-violet/k-green variant tests still pass
  (they patch config explicitly, independent of the new default).
- Verification: `bash scripts/check.sh` green (684 passed, was 681). **Visual**:
  rendered `committed-K` (default) — K left bar **green** with a `Σ` glyph before
  its weight %, distinct from the assistant's `Δ`. Calibrated both directions:
  `--variant k-violet` → violet bar (FAIL-looking), `--variant k-green` → green
  (PASS-looking); both discriminate. Verdict: PASS. Pure rendering/config change,
  so no qa-tester (visual driver sees on-disk code by construction).
- Gotcha for 40/43: the K row now shows a default `--%` weight slot alongside the
  `Σ`; task 43(a) will suppress `--%` on non-model nodes but K *does* go to the
  model, so its `%` stays. The `Σ` glyph is left-of the drift/weight, sharing the
  meta-slot layout task 25 fixed.

## 2026-07-06 — Task 40: blank-line separation before a compression node
- UI-only, pure-function tweak. A K node maps to the assistant *side* in
  `_SIDE` (`ctx/ui/widgets/message_list.py`), so `_pass_starts` gave it no
  `pass-start` when it followed an assistant turn (same side) — the K hugged the
  reply above it with no `.pass-start { margin-top: 1 }` gap and the two read as
  produced together.
- Change: `_pass_starts` now special-cases `role == "compression"` to *always*
  begin a new pass (`prev_side is not None`, i.e. a start unless it's the very
  first node), so a K always detaches from the preceding turn. The existing
  `MessageWidget.pass-start` CSS supplies the margin — no CSS change needed.
  (Kept K's side as "assistant" for the *following* node's computation; only the
  K's own start flag is forced.)
- Tests (written directly, not code-blind — a 3-line change to an already-tested
  pure function with a precisely-specified floor, same judgment as task 39):
  - `tests/test_message_list_passes.py`: `test_compression_after_assistant_starts_a_new_pass`
    (`[user,assistant,compression]` → `[F,T,T]`, the regression net) +
    `test_leading_compression_is_never_a_pass_start` (`[compression,user]` →
    `[F,T]`; first node never a start, the following human query legitimately is).
  - `tests/test_app_commit_compression.py`:
    `test_committed_k_after_assistant_carries_pass_start_margin` (the mandated
    Pilot floor — compress only user2 so the K lands after assistant1; assert the
    K widget `has_class("pass-start")`).
- GOTCHA: my first draft of the leading-compression unit test wrongly expected
  `[F,F]` — the `user` after a K *is* a pass start (K is assistant-side, user is
  human-side). Fixed the assertion to `[F,T]` (not the code). If you touch
  `_pass_starts`, remember a K only forces *its own* start; side tracking for
  neighbours is unchanged.
- Verification: `bash scripts/check.sh` green (687 passed, was 684). **Visual**:
  rendered `k-after-assistant` (real on-disk code) — the first assistant reply
  (orange, 24%) is followed by a **blank margin row**, then the green K (Σ 37%),
  matching every other turn-to-turn gap. Calibrated both directions against the
  standing fixture pair: `--variant k40-nogap` → assistant + K flush (BROKEN),
  `--variant k40-gap` → separated (FIXED); the real render matches k40-gap.
  Verdict: PASS. Pure rendering change, so no qa-tester (visual driver sees
  on-disk code by construction).

## 2026-07-06 — Task 41: range selection = hover styling, bridged across gaps
- UI-only rendering change (CSS + a small MessageWidget/MessageList refactor).
  Two defects: (1) `.range-selected` was a solid dark blue (`$primary-darken-2`)
  unlike the grey hover `.selected` (`$surface-lighten-1`); (2) the inter-row
  **margin** gaps kept the default background, so a multi-node selection read as
  separate bars, not one block (margin paints outside the widget box).
- Changes:
  - `ctx/ui/widgets/message_list.css`: `.range-selected` background → grey
    (`$surface-lighten-1`, same as hover). New `.range-continues-below`
    (`margin-bottom: 0; padding: 0 1 1 2`) and `.range-continues-above`
    (`margin-top: 0`), placed AFTER `.pass-start` so the zeroed top margin wins at
    equal specificity. The upper row of an adjacent pair absorbs the separator as
    grey padding; the lower row drops its pass-start top margin → one grey row
    between, contiguous.
  - `ctx/ui/widgets/message_list.py`: `MessageWidget._refresh_border()` sets a
    bold `thick` role-colored left bar when the row is cursor- OR range-selected
    (else `tall`); both `set_selected`/`set_range_selected` call it. New
    `set_range_continues(above, below)`. New `MessageList.set_range(selected_ids)`
    centralizes the per-row flags (marks range-selected + computes contiguity from
    visible order) so the app never has to know a row's neighbours.
  - `ctx/ui/app.py`: `_apply_range_selection`/`_clear_range` now delegate to
    `MessageList.set_range(...)` (used `contextlib.suppress` in clear — ruff SIM105
    fired once it became a single statement).
  - `tools/agent/visual.py`: new post-variant `range-blue` (forces the broken look:
    solid blue, thin bar, continues classes stripped) + `range-grey` (no-op = real
    fixed code); new FIXTURE entry `task-41-range-selection-contiguous-hover-style`.
  - `tests/test_visual_states.py`: added `range-blue`/`range-grey` to
    `known_variants`.
  - `scripts/ralph/VISUAL-FIXTURE.md`: documented the new pair.
- GOTCHA: first tried `padding-bottom: 1` (single edge) in `.range-continues-below`
  — the fixed render lost its left indent (selected rows' text jumped ~2 cols
  left). Textual reset the `padding` shorthand when only the bottom edge was set in
  a higher-specificity rule. Fixed by writing the full shorthand `padding: 0 1 1 2`
  (preserves left 2 / right 1 / top 0, adds bottom 1). NOTE the asymmetry: the
  single-edge **margin** overrides (`margin-top: 0`, `margin-bottom: 0`) merge fine
  (same as `.pass-start`'s `margin-top: 1`), but single-edge **padding** did not —
  use the full padding shorthand if you touch this.
- Tests (written directly, not code-blind — a CSS + ~30-line class-logic change
  with a precisely-specified floor, same judgment as tasks 39/40):
  `tests/test_app_range_selection.py::test_range_selection_uses_hover_style_and_bridges_gaps`
  — v+down+down selects rows 0,1,2; asserts every selected row's `border_left[0]
  == "thick"`, the interior contiguity classes (top: continues-below only; mid:
  both; bottom: continues-above only), and the outside row has no selection classes
  and a `tall` bar (the regression net for both the bar restyle and the bridging).
- Verification: `bash scripts/check.sh` green (688 passed, was 687). **Visual**:
  rendered `range-selection` (real on-disk code) — the 3 selected rows show bold
  role-colored (blue/orange/blue) left bars over a grey hover background, the bar +
  background bridging the inter-row gaps into one continuous block; the 4th
  (unselected) row is detached by a normal gap; no solid blue anywhere. Calibrated
  both directions: `--variant range-blue` → solid-blue rows with dark gaps (BROKEN),
  `--variant range-grey` → grey contiguous block (FIXED); both discriminate.
  Verdict: PASS. Pure rendering change, so no qa-tester (visual driver sees on-disk
  code by construction).

## 2026-07-06 — Task 42: transient hints leave the conversation graph
- UI-only change. `_breadcrumb` (appended a persistent `core.add_system_message`
  graph node) → renamed `_hint`, now a transient toast: sets `self._last_hint` and
  calls `self.notify(text)`, adds NO node. All 6 refusal/guidance call sites
  (expand-while-streaming, "Not a compression node", draft-in-progress,
  commit-while-streaming, empty-summary, commit-error) route through it. Also
  converted the two dead-end info messages ("No past conversations found.", "No
  files in .ctx/context/ to include.") from persistent nodes to `_hint`.
- Durable breadcrumbs UNCHANGED: `/model` changes + connectivity notices still go
  through `core.add_system_message` → persistent nodes (ADR 0006 #6). This is the
  reserve half of the task.
- `describe_state()` gains `"last_hint"` (most-recent hint | None); reset to None in
  `_reset_transient_ui` so `/new`/`/resume` clear it. `tools/agent/snapshot.py`
  renders it as a `hint="..."` line (only when set) so qa-tester can confirm a hint
  fired without it appearing among the nodes.
- Tests (written directly — UI change, ~20 product lines, precisely-specified floor;
  same judgment as tasks 39–41):
  `tests/test_app_transient_hints.py` — (1) empty-summary Ctrl+S → `last_hint` set,
  node count unchanged, no system node added; (2) `/model openai/gpt-4o` → node count
  grows and a system node names the model (guards against over-correcting ALL system
  messages to transient).
- Updated existing tests that asserted the OLD breadcrumb-as-node contract (deliberate
  — behavior changed): `test_app_commit_compression.py` (empty-summary now asserts
  `last_hint`), `test_app_commit_failures.py` + `test_app_draft_worker_lifecycle.py`
  (`_has_system_breadcrumb` → `_hint_shown` checking `last_hint`),
  `test_app_expand.py` (`x` on non-compression → hint + no node added, renamed test).
- Verification: `bash scripts/check.sh` green (690 passed, was 688 + net new/moved).
  No qa-tester/visual this iteration: the MCP harness runs `ctx.*` cached and can't
  see this session's edits (AGENTS.md), and the acceptance is behavioral (node
  presence), fully captured by the deterministic Pilot floor above. Phase-3e
  end-to-end qa-tester pass is task 45.
- AGENTS.md app.py bullet updated: transient hints via `_hint`→`notify` (not graph
  nodes); durable breadcrumbs stay `add_system_message`; `describe_state` `last_hint`.

## 2026-07-06 — Task 43: no weight on non-model nodes; silent invalid keys; contextual footer
- UI-only, three small changes:
  - (a) `MessageRow.set_weight_pct` + `compose` now render the weight slot **empty**
    (not "--%") when `self.node.goes_to_model()` is False. A system breadcrumb never
    reaches the model, so a `--%` there was misleading. Suppression lives in the
    shared row (single surface) so it holds in the list, diff panes, and splits.
  - (b) `action_expand` (`x`): a non-compression selection is now a **silent no-op**
    (was a "Not a compression node" hint) — the footer advertises `x` only on a K, so
    a warning there is noise. Also wrapped `core.expand_compression` in
    `try/except ValueError` → `_hint(str(exc))` (mirrors `action_commit_compression`;
    folds in the review finding about an uncaught core guard).
  - (c) The Edit-mode footer hint is now contextual: `AppFooter.set_selection(
    node_type, drifted)` + `_edit_hint()` insert `x Expand` only when a K is selected
    and `g d Drift` only on a drifted assistant turn; `_HINTS["edit"]` is the
    no-selection base (head+tail, `x Expand` removed from it). App `_sync_footer`
    now also pushes selection context; called from `_select_message`/`_clear_selection`
    so the hint tracks the cursor. Drift computed via existing `_turn_has_drift`.
- Tests (written directly — UI change, ~35 product lines, precisely-specified floor;
  same judgment as tasks 39–42):
  - `tests/test_message_row.py`: `test_non_model_node_shows_no_weight_slot` (system
    row weight Static renders "" at mount and after `set_weight_pct(None)`),
    `test_model_node_keeps_its_weight_slot` (assistant still shows "12%").
  - `tests/test_app_footer_context.py`: footer omits `x Expand` on a plain turn (==
    `_HINTS["edit"]`) and gains it once a committed K is selected.
  - Updated `tests/test_app_expand.py`: the x-on-non-compression test now asserts a
    silent no-op (`last_hint is None`, node count unchanged) — deliberate behavior
    change from the task-42 "Not a compression node" hint contract; renamed the test.
- Verification: `bash scripts/check.sh` green (693 passed, was 690 + net new/renamed).
  No qa-tester/visual this iteration: the MCP harness runs `ctx.*` cached and can't
  see this session's edits (AGENTS.md), and every acceptance proxy is queryable and
  covered by the deterministic Pilot/row floor above (weight Static content, footer
  string, node count + last_hint). No visual fixture state exercises a system-node
  weight slot, and the "--%" suppression is a direct-render assertion, not a spacing
  judgment. Phase-3e end-to-end qa-tester + visual pass is task 45.
- Doc updates: AGENTS.md AppFooter bullet (contextual Edit hint via set_selection);
  removed the stale "Not a compression node" example from `_hint`'s docstring.

## 2026-07-06 — Task 44: incremental message-list reconcile (kill the refresh flash)
- UI-only change. New `MessageList.reconcile(nodes)` mutates only the difference:
  removes widgets whose node left the view, mounts one row per node that entered
  (via `mount(before=0)` / `mount(after=prev)` so DOM order matches the target),
  and preserves every surviving node's *same widget instance*. Re-applies pass
  margins once and scrolls to end (behavior-preserving vs the old per-add scroll).
- `_rebuild_message_list` (`ctx/ui/app.py`) now delegates to `reconcile(_visible_nodes())`
  instead of teardown-every-child + add-every-node. The list becomes a pure projection
  of the view; the top-to-bottom blank/repopulate flash on commit/expand/deep-dive-nav
  is gone (the flash *was* the teardown+remount). All three call sites unchanged
  (commit :806, expand :652, deep-dive nav via `_refresh_deep_dive_view` :505).
- Assumption documented in reconcile's docstring: surviving rows keep relative order
  (structural changes only drop/insert contiguous runs, never reorder survivors), so
  new rows mount next to their predecessor. True for every current structural op.
- Test (written directly — UI change, ~30 product lines, precisely-specified floor;
  same judgment as tasks 39–43): `tests/test_app_reconcile.py::test_commit_preserves_
  surviving_widget_instances` — 2 turns → fold the trailing 2 nodes → assert the two
  leading rows are the *identical* widget objects (`after[id] is before[id]`), exactly
  3 rows remain, and the lone new K widget is last/in-place. This is the queryable
  proxy for "no teardown" — a revert to remount recreates the instances and fails it.
- Verification: `bash scripts/check.sh` green (694 passed, was 693). The existing
  suite exercises the reconcile path through the still-green expand
  (`test_app_expand.py`), deep-dive, and commit Pilot tests, so those structural ops
  render correctly through the new code.
- No qa-tester/visual this iteration: the "flash" is a rendering-*timing* artifact
  (transient teardown→repopulate) — qa-tester (runs `ctx.*` cached, snapshot-only,
  can't see this session's edits or perceive timing) and the single-frame visual
  driver both physically cannot observe a flash. Instance preservation is the exact
  mechanism that removes it, so the deterministic Pilot floor above fully captures the
  acceptance. Phase-3e end-to-end qa-tester + visual pass is task 45.

## 2026-07-06 — Task 45: Sprint 3 end-to-end verification (qa-tester + visual) — FINAL
- Verification-only task (no product code changed). Gate green up front:
  `bash scripts/check.sh` → 694 passed, ruff + mypy clean.
- **qa-tester behavioral pass** (one launch, in-process HarnessApp via ctx-agent MCP):
  all 8 acceptance items reported WORKS, `textual_check_errors` clean after every
  risky step (compression commit, deep-dive enter/exit, diff enter/exit, include
  modal, invalid key). Confirmed: 4-turn build → middle-range commit (range=[2,3,4],
  nodes 8→6, downstream turns gain Δ, no crash); contiguous range_selection=[2,3,4];
  empty-commit hint adds no node (node count held); `x` on non-K and unbound `z` are
  silent no-ops; footer shows `x Expand` only on a K and `g d Drift` only on a drifted
  turn; deep-dive K shows the folded originals + read-only footer, Ctrl+o pops;
  diff view opens on drifted turn [3] (diff_view.open, 1 region, up/down no-crash,
  Ctrl+o closes); `/include` modal dismisses cleanly with no soft-lock (submitted a
  message afterward, nodes 8→10). Two fixture-gap notes (not product bugs): the harness
  always seeds sample.txt so the literal "nothing to include" hint path is unreachable
  (substituted empty-commit hint); diff region-cursor movement only exercised with 1
  region since the compact `diff:` snapshot line exposes no active-region index.
- **Visual pass** (fresh `uv run` visual driver, always current on-disk code). Rendered
  and judged each state against its one-line intent:
  - `committed-K` — K left bar context-green with `Σ` glyph, assistant below has `Δ` → PASS
  - `k-after-assistant` — blank margin row separates the green `Σ` K from the assistant
    turn directly above it → PASS
  - `k-inspector` — Prompt / Originals / Summary splits render as compact rows with
    visible dotted dividers → PASS
  - `range-selection` — grey hover-style block, role-colored left bars, contiguous
    across inter-row gaps; unselected trailing turn stays dark → PASS
  - `drift-diff` — two panes ("was — context at generation" / "now — current context"),
    compact rows, changed region highlighted amber → PASS
- **VISUAL-FIXTURE re-run** — all 6 PNGs matched `expected_verdict`, both directions
  discriminate (gate calibrated): task-40 FAIL flush-K / PASS gap-before-K; task-41
  FAIL solid-blue-with-dark-gaps / PASS grey-contiguous-block; task-39 FAIL violet-bar /
  PASS green-bar.
- No regressions found → no follow-up tasks filed. **This was the last open PRD task —
  Sprint 3 (compression & spatial navigation, 3a–3e) is complete.**

## 2026-07-07 — Task 46: `build_compression_transcript` helper (Phase 3f start)
- Pure, framework-free renderer added to `ctx/core/context.py` next to `build_context`
  (no new imports; `load_file` injected → stays testable without I/O). Renders a
  `list[Node]` as one plain-text transcript: each `goes_to_model()` node becomes a
  `"{Role}:\n{body}"` block in node order (user/assistant → content by role; a
  `context` node → its loaded file body, NOT the "Included:" label; a committed `K` →
  its summary). Non-model nodes (system/expand) and empty-body blocks emit nothing —
  the exact set `build_context` skips. The contiguous in-range blocks (ids in
  `range_ids`) are bracketed by `<compress_this>`/`</compress_this>` marker lines
  (module constants `OPEN_/CLOSE_COMPRESS_MARKER`); before/after blocks sit outside.
- **Design decision (documented in the docstring + spec, adjudicable):** context and
  compression nodes are labeled `User:` — their *model-facing* role (build_context
  routes both as user). Bodies are plain text with NO `<context_import>`/
  `<conversation_summary>` XML wrapper (A#6: "imports as file bodies, K's as their
  summaries"). Empty marked span still emits both markers as an adjacent empty pair so
  task 47 can detect it and raise `ValueError` before any provider call.
- Not wired anywhere yet — task 47 (`draft_compression` reframe) is the sole consumer.
  Read ADR-0016 Amendment #6 before 47/48.
- Tests: code-blind flow (PROMPT.md step 4). Stub (signature+docstring+`NotImplementedError`)
  → `test-spec-author` given ONLY the interface + prose intent → 7 tests collected clean
  and failed red on `NotImplementedError` → implemented to green. `tests/specs/
  compression_transcript.md` (C1–C7) + `tests/test_compression_transcript.py`: range
  between markers (C1), before/after outside (C2), context file body not label (C3), K
  summary (C4), system dropped (C5), role labels + node order (C6), empty marked span =
  adjacent empty markers (C7). All 7 earn their place (one per acceptance item + 2 edge
  invariants); deletion test applied, none pruned.
- Verification: pure core logic, not wired to any UI/runtime surface this iteration
  (step 7) → no qa-tester, no visual; the code-blind tests + green gate ARE the
  verification. `bash scripts/check.sh` green (701 passed, was 694; +7 new). ruff + mypy
  clean.
- Note: the uncommitted CONTEXT.md / ADR-0016 (A#6) / PRD.md (Phase 3f filing) working-tree
  changes were the phase-3f setup left in place; folded into this commit as the phase's
  first landing.
