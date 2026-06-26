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
