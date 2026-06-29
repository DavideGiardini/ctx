# 0008 — workspace.py observations

**Status:** Notes (no action required)

## Context

Things we noticed while reading `Workspace` in `ctx/core/workspace.py`. Neither is
a bug; recorded so the understanding isn't rediscovered later.

## Observations

### 1. `list_files()` reads every file in full just to validate UTF-8

To decide whether a file is "text", `list_files()` calls `path.read_text(...)` and
discards the result, for every file, on every call. So listing the KB is O(total
bytes of all files), with the reads thrown away. ADR 0005 already flags this as an
"accepted, bounded compromise" (validation stays coupled to listing).

**Decision (for the deferred cleanup task):** classify includable files by
**sniffing the first ~8 KB** — reject the file if that prefix contains a NUL byte
or is not valid UTF-8 (decode tolerantly at the chunk boundary so a multi-byte char
split across it isn't a false negative). This is bounded (one small read,
independent of file size), dependency-free, and **extension-free** — so
extensionless dev files (`Dockerfile`, `Makefile`, `LICENSE`, …) pass naturally and
there is no allowlist to maintain or configure. The criterion ("NUL-free,
UTF-8-decodable prefix") deliberately matches what `read_file` (UTF-8) can actually
consume, so the picker and the reader agree by construction. Edge cases (valid
prefix but garbage later; non-UTF-8 encodings) are *not* guarded — they fail loudly
at read time (0007 #1), which is acceptable for a developer tool ("power over
protection"). This **replaces** the earlier "sniff vs. extension allowlist" idea.

**Caching — deliberately not now.** The bounded sniff is already cheap for the
curated `.ctx/context/` (one ~8 KB read × a handful of files = milliseconds), so
caching the verdict adds cache-invalidation complexity for negligible gain — skip
it (deletion test). Note the scope: text-ness is a **`Workspace`** property, not a
*conversation* one (the file set doesn't change on `/new`/`/resume`), so any cache
belongs on `Workspace`, never the conversation. If/when the KB widens to the whole
launch directory (Product Concept §3) and listing spans thousands of files,
revisit: a `Workspace`-level cache keyed by `(path, mtime, size) → is_text` that
still does the cheap `rglob` + `stat` every call but skips the *read* for unchanged
files.

### 2. `list_files()` and `read_file()` can disagree about the same file

They validate differently: `list_files()` checks UTF-8 decodability; `read_file()`
enforces the traversal guard (`is_relative_to` after `.resolve()`). So `list_files`
can surface a file — e.g. one reachable via a symlink that resolves outside
`context/` — that `read_file` then rejects with "Path escapes context directory".
A user could pick a listed file and have the include silently fail (see 0007 #1).
The two methods are not guaranteed consistent.
