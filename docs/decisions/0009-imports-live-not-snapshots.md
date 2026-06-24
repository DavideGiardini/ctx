# 0009 — File imports are live, not snapshots (Product Concept §3.3 gap)

**Status:** Notes (no action required)

## Context

Cuts across `context.py`, `workspace.py`, and the product vision. Recorded because
it's a real gap between current behavior and the planned feature, and the eventual
fix is non-trivial.

## Observation

Today a context node stores only `meta["source_path"]` (plus a label in `content`)
— **not** the file's text. `build_context` re-reads the file fresh from disk at
every stream via `Workspace.read_file`. So imports are **live**: edit the source
file after importing and the model silently sees the new version on the next turn.

Product Concept §3.3 wants the **opposite** — static snapshots frozen at import
time, a staleness marker (`~`) when the source drifts, `gd` (view the snapshot the
LLM saw) vs `gD` (view the live file), and explicit re-import to update. All of
that *requires storing a copy* of the content. That storage cost is the feature,
not waste — but it's the exact cost the current by-reference design avoids.

## How to deal with it when the time comes (sketch)

- **Capture at import:** snapshot content + `sha256` + `(mtime, size)`. Store the
  content in a **content-addressed blob store** (a separate table, or `.ctx/`
  dir, keyed by hash); the context node references the hash in `meta`. → dedup
  (same file imported twice = one blob), lean `nodes` table, immutable-by-hash.
- **`build_context` resolves the snapshot by hash** (injected getter) instead of
  reading live disk → context becomes a pure transform over *captured* data, and
  the stream-time live read disappears. Bonus: the silent load-failure mode
  (0007 #1) moves to **import time**, where it's visible to the user.
- **Staleness (`~`):** computed lazily at render time — `stat` the source, compare
  `mtime`/`size`, hash only on mismatch; handle a deleted source gracefully.
- **`gd`** shows the stored snapshot; **`gD`** does a live `read_file` (graceful if
  the file is gone).
- **Re-import is explicit** and creates a *new* snapshot version, preserving the
  old (consistent with "nothing is truly deleted").
- **Dovetails with 0006 #2:** immutable, hash-keyed blobs fit an append-only
  persistence model far better than today's full-replace `save()` (which would
  otherwise re-write large blobs on every save). The snapshot feature is another
  forcing function for that persistence-model change.
