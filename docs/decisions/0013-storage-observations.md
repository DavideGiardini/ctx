# 0013 — storage.py observations

**Status:** Notes (no action required)

## Context

Noticed while reading `ConversationRepository` in `ctx/core/storage.py`. Not a bug;
recorded so the understanding isn't rediscovered later.

## Observation

### Connection-per-method: no long-lived connection

Every repository method (`init`, `save`, `load`, `list`, `get_last`) opens a fresh
SQLite connection via `self._connect()`, sets its pragmas (`WAL`,
`foreign_keys=ON`), does its work, and closes it in a `finally`. The repository
holds **no** persistent connection.

Upsides — and why it's the right call today:
- No shared mutable connection state; each method is self-contained and can't leak
  a half-open transaction to the next.
- Combined with the injected `db_path`, it removes the old global `Path.cwd()`
  coupling and makes the repo trivially constructible against any path.

Consequences to keep in mind:
- **`":memory:"` does not work with this design.** An in-memory SQLite database is
  private to its connection, so a fresh connection per method means `init()`,
  `save()`, and `load()` would each see a *different* empty database. The tests use
  a temp-file DB for exactly this reason (documented in `tests/conftest.py`). Note
  ADR 0003 still claims `:memory:` is supported "for tests" — that detail is stale.
- **Per-call overhead.** Each call pays a connect + pragma setup. Negligible at a
  TUI's call frequency (a save per human action), but it's a real cost that would
  compound if persistence ever became hot — e.g. the snapshot/branching futures
  (0009 / 0006), or anything that saves more than once per human action. If that
  happens, a longer-lived connection (or a connection per logical operation) is the
  lever to reach for.
