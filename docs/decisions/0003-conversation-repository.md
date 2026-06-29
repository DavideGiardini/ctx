# 0003 — Deepen storage.py into a ConversationRepository

**Status:** Accepted

## Context

`storage.py` exposed free functions (`init_db`, `save_conversation`,
`load_conversation`, `list_conversations`, `get_last_conversation_id`) that
returned raw `Node` objects while internally managing SQL schema, JSON
serialization, and connection lifecycle — the SQLite mechanics weren't hidden.
Every function opened its own connection (coupling to global state), and callers
had to understand the destructive delete-all/re-insert strategy of
`save_conversation`. A temporary `StorageAdapter` pass-through in the UI
(from [0001](0001-extract-conversation-core.md)) papered over the missing seam.

## Decision

Introduce a `ConversationRepository` class.

- **Constructor:** `ConversationRepository(db_path: str)` — supports `:memory:`
  for tests.
- Each method opens/closes its own connection from `self._db_path`, removing the
  global `Path.cwd()` dependency.
- SQL schema and `init()` live inside the class, fully encapsulated.
- The `StoragePort` protocol grew `list()` and `get_last()` so the whole UI uses
  one seam; the repository *is* the concrete adapter (the `StorageAdapter`
  pass-through was deleted).

## Consequences

- The UI layer no longer imports the raw persistence module — the entire
  persistence surface sits behind `StoragePort`. `HistoryScreen` receives the
  repository and calls `self._repo.list()`.
- All SQL and serialization logic is encapsulated behind a small interface.

---

**Correction:** the Decision's claim that the constructor "supports `:memory:` for
tests" is stale — the connection-per-method design (each method opens a fresh
connection) makes an in-memory DB invisible across calls, so tests use a temp-file
DB instead. See [0013](0013-storage-observations.md).
