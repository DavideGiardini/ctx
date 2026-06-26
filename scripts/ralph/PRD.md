# PRD — Core hardening & node-classification cleanup

## Goal
Resolve the Tier-1/Tier-2 correctness and quality issues found in the
session-recorded triage (`docs/decisions/0006`–`0014`): make context-load and
stream failures visible instead of silent, give the conversation a model that
survives resume, make persistence uniform, and introduce a single source of truth
for node construction/classification. Each task is an independent, green-keeping
slice; the per-issue rationale lives in the referenced `docs/decisions/` notes.

## Constraints / notes
- Follow the "Designing new modules" guidance in `AGENTS.md`: deep modules, `core/`
  stays framework-free (zero `textual` imports), seams only on a second real
  implementation, deletion test before abstraction.
- Read the referenced ADR/notes before starting a task — they carry the *why*.
- `StoragePort` (`ctx/core/storage.py`) has a **second implementation**,
  `SaveCountingStorage` in `tests/test_conversation.py`. Any change to the
  `StoragePort` interface (e.g. `save()` signature) MUST update that double in the
  same task, or the tree goes red.
- Behavioral checks go through the `qa-tester` subagent (the `ctx-agent` MCP server
  drives `tools.agent.harness:HarnessApp`). Unit-level acceptance goes through
  `scripts/check.sh` (ruff + mypy + pytest).
- Shared fixtures already exist in `tests/conftest.py` (`repo`, `workspace`,
  `test_provider`, `make_node`, `stub_loader`) — reuse them.
- Do NOT introduce `Node` subclasses — the chosen approach is factory classmethods +
  predicates on the single `Node` dataclass (see tasks 4–5 and `docs/decisions/0014`).

## Tasks
Top-to-bottom by priority; the loop always takes the topmost unchecked task.

- [x] **Harden `build_context` against bad/empty nodes** — in
      `ctx/core/context.py`, stop silently dropping context nodes whose file fails
      to load: when `load_file` raises `OSError`/`ValueError`, emit a *visible*
      marker into the built message (e.g. a `<context_import source="…"
      error="…">` block) instead of `continue`-ing past it. Also skip
      `user`/`assistant` nodes whose `content` is empty so no empty-content message
      is produced. (Refs: 0007 #1, 0007 #2.) _Acceptance:_ unit tests in
      `tests/test_context.py` — (a) a `stub_loader` that raises for a path produces
      a message that references that path with an error indication (not silently
      absent); (b) an `assistant` node with `content=""` yields no message.
      `scripts/check.sh` green.

- [x] **Persist & restore the conversation's model** — add a `model` column to the
      `conversations` table in `ctx/core/storage.py`; extend `StoragePort.save` and
      `ConversationRepository.save` to take and write the model; have
      `ConversationCore.persist` pass `self.model`; have
      `resume_conversation` restore `self.model` from the stored row. Add a small
      migration in `init()` for pre-existing DBs (SQLite has no `ADD COLUMN IF NOT
      EXISTS` — guard via `PRAGMA table_info`). Update the `SaveCountingStorage`
      double. (Ref: 0014 #2.) _Acceptance:_ unit test — set a model, persist, then a
      fresh `ConversationCore` sharing the same `repo` resumes that id and has the
      stored `model`. qa-tester — switch model with `/model`, `/resume` that
      conversation, snapshot shows the conversation's model in the footer.
      `scripts/check.sh` green.

- [x] **Source the default model from `config.py`** — move the default model out of
      the `DEFAULT_MODEL` constant in `ctx/core/conversation.py` into the defaults
      in `ctx/core/config.py`; have `ConversationCore` read the default from config
      (read it once, e.g. at construction — don't do file I/O per call). Update the
      `app.py` reference. (Ref: 0006 #3.) _Acceptance:_ unit test — config supplies
      the default model and a freshly constructed `ConversationCore` uses it; the
      hardcoded constant is gone. `scripts/check.sh` green.

- [ ] **Add `Node` factory constructors and migrate `ConversationCore`** — add
      classmethods `Node.user`, `Node.assistant`, `Node.system`, `Node.context` to
      `ctx/models/nodes.py`, each encoding the correct `role`/`node_type`/`content`/
      `meta` combination (e.g. `Node.context(source_path, conversation_id)` sets
      `role="context"`, `node_type="context"`, `content="Included: …"`,
      `meta={"source_path": …}`). Migrate every `Node(...)` construction in
      `ctx/core/conversation.py` to the factories. No behavior change. (Ref:
      0014 #1.) _Acceptance:_ unit tests assert each factory's field combination;
      the existing `tests/test_conversation.py` suite stays green.
      `scripts/check.sh` green.

- [ ] **Add a `goes_to_model` predicate and route `build_context` through it**
      *(depends on the factories task above)* — add `Node.goes_to_model() -> bool`
      (`role in {"user","assistant"}` or `node_type == "context"`) to
      `ctx/models/nodes.py`, and replace the inline role-based inclusion logic in
      `ctx/core/context.py` with it, so the "which nodes reach the LLM" rule has one
      definition. No change to the produced messages. (Ref: 0014 #1.)
      _Acceptance:_ unit test covers the predicate truth table (user/assistant/
      context → True; system → False); existing `build_context` tests stay green.
      `scripts/check.sh` green.

- [ ] **Make persistence uniform across all commands** — every command method in
      `ctx/core/conversation.py` (`set_model`, `check_connectivity`,
      `add_system_message`, …) calls `persist()`, and the nodes they create carry
      the `conversation_id` so they are actually written (today system/connectivity
      breadcrumbs are filtered out by the storage layer). Document the uniform policy
      in the `ConversationCore` docstring. Consequence (intended): model-change and
      connectivity messages now reappear on resume. (Ref: 0006 #6.) _Acceptance:_
      unit tests — after each command, `repo.load(id)` reflects the created node(s);
      qa-tester — `/model X`, `/resume`, snapshot shows the "Model set to: X" node in
      the restored conversation. `scripts/check.sh` green.

- [ ] **Give the provider a timeout and a domain error type** — in
      `ctx/core/provider.py`, define a small `ProviderError`; have
      `LiteLLMProvider.stream` pass a sane `timeout` to `acompletion` and map raised
      backend exceptions to `ProviderError` (so the litellm type doesn't leak through
      the seam). `ConversationCore.stream` already persists-and-re-raises on
      exception — ensure `ProviderError` flows through unchanged. (Ref: 0011 #1.)
      _Acceptance:_ `ProviderError` exists; a provider test double that raises
      `ProviderError` from `stream` causes `ConversationCore.stream` to persist the
      partial assistant node and re-raise `ProviderError` (unit test). Note:
      `LiteLLMProvider` itself is the network adapter and stays out of the unit suite
      by design. `scripts/check.sh` green.

- [ ] **Decouple `stream()` from node ordering** — in `ConversationCore.stream`
      (`ctx/core/conversation.py`), replace `build_context(self.nodes[:-1], …)` with
      a slice that excludes the streamed node *by identity*:
      `build_context([n for n in self.nodes if n is not assistant_node], …)`. Same
      behavior, no reliance on the assistant node being last. (Ref: 0006 #1.)
      _Acceptance:_ existing stream tests stay green; a unit test confirms the
      context excludes exactly the streamed assistant node regardless of its
      position in `self.nodes`. `scripts/check.sh` green.

## Out of scope
- **Feature-gated** (change only when the triggering feature is built): the
  persistence-model rework / soft-delete + node graph + op log (0006 #2), import
  snapshots & staleness (0009), `<context_import>` escaping for untrusted sources
  (0007 #3), and the structural persist choke-point (`_add`) (0006 #6 structural).
- **Deferred to a later PRD** (minor cleanups, to be scoped next session):
  bounded UTF-8 sniff in `list_files` (0008 #1), `list_files`/`read_file` traversal
  alignment (0008 #2), `_derive_title` helper (0006 #5), and the stale-ADR doc fixes
  (0013 #1, 0014 #3).
- **Node subclassing / inheritance** — explicitly rejected in favor of factories +
  predicates.
- Do not touch `main`/`develop`, `uv.lock` (use `uv`), `.ctx/`, or `.env`.
