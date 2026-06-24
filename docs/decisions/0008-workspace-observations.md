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
"accepted, bounded compromise" (validation stays coupled to listing). Worth
remembering as the first thing to optimize if listing ever feels slow — sniff a
chunk or check for null bytes instead of reading the whole file.

### 2. `list_files()` and `read_file()` can disagree about the same file

They validate differently: `list_files()` checks UTF-8 decodability; `read_file()`
enforces the traversal guard (`is_relative_to` after `.resolve()`). So `list_files`
can surface a file — e.g. one reachable via a symlink that resolves outside
`context/` — that `read_file` then rejects with "Path escapes context directory".
A user could pick a listed file and have the include silently fail (see 0007 #1).
The two methods are not guaranteed consistent.
