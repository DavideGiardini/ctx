# Behavioral Contract — `ctx/core/workspace.py`

## What this module is for

`Workspace` models the on-disk layout of a `ctx` project rooted at some directory.
Given a `root_path`, it derives a fixed set of paths under a hidden `.ctx/` directory:
the workspace itself (`<root>/.ctx`), a `context/` subtree where the user's context
files live (`<root>/.ctx/context`), and a SQLite conversations database
(`<root>/.ctx/conversations.db`). It can materialize that layout on disk (`ensure()`),
enumerate the context files (`list_files()`), and read a single context file by its
relative path (`read_file()`).

The defining property of `read_file()` is **safety**: it is a sandboxed reader. Only
files that genuinely live inside the context directory may be read. Any relative path
whose *resolved* (canonical, symlink-followed, `..`-collapsed) location falls outside
the context directory must be rejected before any I/O escapes the sandbox. `list_files()`
is correspondingly forgiving: it silently skips anything it cannot represent as readable
UTF-8 text rather than failing the whole listing.

### Byte-exact / contractual vs. observable-only

- **Contractual (byte-exact):** the path values returned by `workspace_path`,
  `context_dir`, and `db_path` (they are fixed string suffixes under `root_path`); the
  fact that `ensure()` returns `workspace_path`; the sorted, relative, forward-slash
  (posix) form of `list_files()` entries; the exact text round-tripped by `read_file()`;
  and the specific exception *type* raised by `read_file()` for each error condition.
- **Observable-only (not pinned):** the precise mechanism by which non-text/unreadable
  files are detected; any warning/log emitted when a file is skipped (a side channel we
  do not assert on); the exact `OSError` subclass for a non-readable / directory target
  (we assert the `OSError` family, not the subclass); whether intermediate directories
  are created with any particular mode.

## Contract

### Path properties

**C1. `workspace_path` is `<root>/.ctx`.**
- Given: `Workspace(root)` for some directory `root`.
- Expect: `ws.workspace_path == root / ".ctx"`.

**C2. `context_dir` is `<root>/.ctx/context`.**
- Given: `Workspace(root)`.
- Expect: `ws.context_dir == root / ".ctx" / "context"`.

**C3. `db_path` is `<root>/.ctx/conversations.db`.**
- Given: `Workspace(root)`.
- Expect: `ws.db_path == root / ".ctx" / "conversations.db"`.

**C4. Reading properties is pure (no disk mutation).**
- Given: a fresh `Workspace(tmp_path)` over a directory with no `.ctx/`, before any
  `ensure()` call.
- Expect: accessing `workspace_path`, `context_dir`, and `db_path` creates nothing on
  disk — `.ctx/` and its children still do not exist afterward.

**C5. Properties are mutually consistent.**
- Given: any `Workspace(root)`.
- Expect: `context_dir.parent == workspace_path` and `db_path.parent == workspace_path`.

### `ensure()`

**C6. `ensure()` creates both directories.**
- Given: a `Workspace(tmp_path)` with no `.ctx/` yet.
- Expect: after `ensure()`, both `workspace_path` and `context_dir` exist and are
  directories.

**C7. `ensure()` returns `workspace_path`.**
- Given: a `Workspace(tmp_path)`.
- Expect: the return value of `ensure()` equals `workspace_path`.

**C8. `ensure()` is idempotent and non-destructive.**
- Given: an ensured workspace into which a file `context/keep.md` has been written.
- Expect: calling `ensure()` a second time succeeds, the directories still exist, and
  `context/keep.md` is still present with unchanged contents.

### `list_files()`

**C9. Empty list when the context directory does not exist.**
- Given: a fresh `Workspace(tmp_path)` that has never been ensured (no `.ctx/`).
- Expect: `list_files() == []` and no error is raised.

**C10. Empty list when the context directory is empty.**
- Given: an ensured workspace whose `context/` directory contains no files.
- Expect: `list_files() == []`.

**C11. Single top-level file by its relative name.**
- Given: an ensured workspace containing exactly one file `context/notes.md`.
- Expect: `list_files() == ["notes.md"]`.

**C12. Multiple files sorted by relative posix string.**
- Given: an ensured workspace containing top-level files `context/zeta.md`,
  `context/alpha.md`, and `context/beta.md`.
- Expect: `list_files() == ["alpha.md", "beta.md", "zeta.md"]` (ascending sort of the
  relative path strings).

**C13. Recurses into subdirectories with forward-slash posix relative paths.**
- Given: an ensured workspace containing `context/guides/setup.md`.
- Expect: `list_files()` contains the entry `"guides/setup.md"` (forward slashes,
  relative to the context dir), regardless of host OS path separator.

**C14. Lists files only, never directory entries.**
- Given: an ensured workspace containing `context/docs/readme.md` (so `context/docs/`
  is a non-empty subdirectory).
- Expect: `list_files()` includes `"docs/readme.md"` but does not include `"docs"` (or
  `"docs/"`) as an entry — directories themselves are not listed.

**C15. Skips a non-UTF-8 binary file.**
- Given: an ensured workspace containing one valid text file `context/notes.md` and one
  file `context/blob.bin` whose bytes are not valid UTF-8.
- Expect: `list_files() == ["notes.md"]` — the binary file is omitted and no error is
  raised.

**C16. Mixed valid + binary + nested → exactly the valid text files, sorted.**
- Given: an ensured workspace containing `context/intro.md` (text),
  `context/guides/setup.md` (text), `context/image.bin` (non-UTF-8 bytes), and
  `context/guides/data.bin` (non-UTF-8 bytes).
- Expect: `list_files() == ["guides/setup.md", "intro.md"]` — only the UTF-8-decodable
  files, in sorted relative-posix order.

**C26. Skips a file it cannot read.**
- Given: an ensured workspace with two valid-UTF-8 text files, `context/readable.md`
  and `context/locked.md`, where read permission has been removed from `locked.md`
  (e.g. `os.chmod(path, 0o000)`).
- Expect: `list_files()` omits `"locked.md"` (the same treatment as a binary file),
  still includes `"readable.md"`, and does not raise.
- Note for author: the test must SKIP when the process can read the file anyway — i.e.
  when running as root (`os.geteuid() == 0`) or when an actual read attempt still
  succeeds — because permission bits do not constrain root. Restore the file's
  permissions in a `finally` so the temp directory can be cleaned up.

### `read_file()` and security

**C17. Round-trips the exact text of a top-level file.**
- Given: an ensured workspace containing `context/notes.md` whose contents are a known
  multi-line UTF-8 string.
- Expect: `read_file("notes.md")` returns that exact string, byte-for-byte (same
  decoded text).

**C18. Reads a nested file via its posix relative path.**
- Given: an ensured workspace containing `context/guides/setup.md` with known contents.
- Expect: `read_file("guides/setup.md")` returns those exact contents.

**C19. `FileNotFoundError` for a non-existent in-bounds file.**
- Given: an ensured workspace with no file `context/missing.md`.
- Expect: `read_file("missing.md")` raises `FileNotFoundError`.

**C20. `ValueError` for a `../`-traversal that escapes the context directory.**
- Given: an ensured workspace.
- Expect: `read_file("../../etc/passwd")` raises `ValueError` — the resolved path lies
  outside the context directory.

**C21. The escape guard fires before existence is consulted.**
- Given: an ensured workspace and an escaping relative path that points at a location
  which does not exist (e.g. `"../../this/does/not/exist.md"`).
- Expect: `read_file(...)` raises `ValueError` (the escape), NOT `FileNotFoundError` —
  the sandbox boundary is checked before, and instead of, any existence/read attempt.

**C22. A path that resolves back inside the context dir is in-bounds.**
- Given: an ensured workspace containing a file `context/note.md`, addressed by a
  relative path that climbs out of `context/` and then re-enters it — e.g.
  `"../context/note.md"` (leaves `context/` into `.ctx/`, then re-enters `context/`),
  so its *resolved* location is genuinely inside the context directory.
- Expect: `read_file("../context/note.md")` does NOT raise `ValueError`; it reads the
  in-sandbox file and returns its exact contents. If the addressed in-sandbox file does
  not exist, it raises `FileNotFoundError` (an ordinary missing-file outcome) — still
  not `ValueError`. The boundary check is about where the path *resolves to*, not about
  any `..` segment appearing in the input.

**C23. Absolute `rel_path` → `ValueError`, never reads outside.**
- Given: an ensured workspace.
- Expect: `read_file("/etc/passwd")` raises `ValueError` and never returns the contents
  of any file outside the context directory — an absolute path is not a valid in-sandbox
  relative path.

**C24. A sibling directory sharing a name prefix is out of bounds.**
- Given: an ensured workspace, plus a real sibling directory `context-extra` created
  next to the `context` directory (i.e. `<root>/.ctx/context-extra/`) containing a real
  file `secret.txt`, addressed as `"../context-extra/secret.txt"`.
- Expect: `read_file("../context-extra/secret.txt")` raises `ValueError`. The sibling is
  a different directory that merely shares a leading substring of the name `context`;
  sharing a name prefix does not make it in-bounds. (Guards against a buggy
  `startswith`-style containment check.)

**C25. A symlink whose target is outside the sandbox is rejected.**
- Given: an ensured workspace containing a symlink that lives *inside* `context/` (e.g.
  `context/link.md`) whose target is a real file located OUTSIDE the workspace (e.g.
  under `tmp_path` but not under `.ctx/context/`), so the symlink's resolved target
  escapes the context directory.
- Expect: `read_file("link.md")` raises `ValueError`. Safety is defined by where the
  path *truly resolves to*; following the link out of the sandbox is rejected and the
  outside file's contents are never returned.

**C27. A path that resolves to the context directory itself → `OSError`.**
- Given: an ensured workspace and a relative path that resolves to exactly the context
  directory (a directory, not a regular file) — e.g. `""` or `"."`.
- Expect: `read_file("")` (or `read_file(".")`) raises `OSError`. The target is in
  bounds but is not a readable regular file, and the docstring documents `OSError`
  "if the file cannot be read." Assert against the `OSError` family broadly (an
  `IsADirectoryError` is an `OSError`); do not pin the exact subclass.

## Adjudication notes

- **Properties are pure (C4).** Reading any of the three path properties must not touch
  the filesystem; only `ensure()` creates directories.
- **`list_files()` sort key is the relative posix string (C12, C16).** Entries are
  sorted as their forward-slash relative-path strings, ascending.
- **"Text" means UTF-8-decodable (C15, C16).** A file is listable/readable iff its bytes
  decode as UTF-8; non-decodable files are silently skipped by `list_files()`.
- **Warning/log channel is not asserted (C15, C16, C26).** When `list_files()` skips a
  binary or unreadable file it may emit a warning or log line; the contract deliberately
  does not assert on that side channel, only on the absence of the entry and the absence
  of a raised exception.
- **Guard-before-existence (C21).** The sandbox-escape check precedes — and substitutes
  for — any existence check, so an escaping path that also happens not to exist yields
  `ValueError`, not `FileNotFoundError`.
- **Absolute path → `ValueError` (C23).** An absolute `rel_path` is treated as an
  out-of-bounds input and rejected with `ValueError`; it must never read an outside file.
- **Resolve-then-contain semantics (C22, the key C22 revision).** The boundary test is
  performed on the *resolved* (canonicalized, `..`-collapsed, symlink-followed) path, not
  on the textual presence of `..` in the input. A path that leaves and then re-enters the
  context directory resolves to an in-sandbox location and is therefore allowed; only a
  path whose resolved location is genuinely outside the context directory escapes. This is
  why C24 (sibling sharing a prefix) and C25 (symlink pointing out) are `ValueError`,
  while C22 (re-entry) is not.
- **Rationale for C24–C27.** These four pin the *safety* meaning of `read_file()` /
  `list_files()` against the most likely correctness gaps: C24 defends against a naive
  `startswith` containment check that would accept a prefix-sharing sibling; C25 defends
  against checking the lexical path instead of the symlink-resolved real path; C26
  defends the "skip what you cannot read" promise of `list_files()` for permission errors
  (not just encoding errors); C27 defends that an in-bounds-but-not-a-file target reports
  an `OSError` rather than silently returning directory bytes or the wrong exception.
- **Security-critical items:** C20, C21, C23, C24, and C25 are the security boundary of
  the module — each verifies that no file outside the context directory can be read. They
  are the highest-value items for mutation testing.

## Contract violations found

- **C24 — sandbox escape via name-prefix sibling (CONFIRMED BUG, quarantined
  `xfail(strict=True)`).** `read_file()` guards the sandbox with a string-prefix test
  (`str(target).startswith(str(context_dir.resolve()))`) that lacks a path-separator
  boundary. A sibling directory whose name merely *starts with* the context dir's name —
  e.g. `<root>/.ctx/context-extra/` next to `<root>/.ctx/context/` — produces a resolved
  path (`.../.ctx/context-extra/secret.txt`) that satisfies the prefix `.../.ctx/context`,
  so the guard passes and the out-of-sandbox file is read and returned. Expected per C24:
  `ValueError`. Test `test_c24_read_file_sibling_prefix_dir_raises_valueerror` is the
  executable spec of the correct behavior; see `FOUND-BUGS.md`. (All other security items —
  C20, C21, C23, C25 — pass; the symlink escape C25 is correctly caught because `.resolve()`
  follows the link before the prefix check.)

## Mutation testing

100% line + branch coverage. mutmut (`scripts/mutate.sh run 'ctx.core.workspace.*'`):
**27 survivors, all documented-equivalent — zero weak tests.** The security-critical
mutants were all killed: the path-escape *condition*, the `exist_ok` idempotency (so the
"ensure twice" test bites), and the binary/UTF-8 skip all detect their mutations.

Survivors, by category (none change observable behavior under this contract):
- **16 — logging side-channel.** `logger.info/warning` argument/wording mutations. Log
  text is not the oracle (same as in `context`/`storage`/`snapshot`).
- **6 — `mkdir(parents=…)` variants** (`True`→`False`/`None`/dropped). No-ops here because
  the workspace root always exists (tests build it under `tmp_path`), and `.ctx` is created
  before `.ctx/context`, so no parent is ever missing.
- **4 — `encoding="utf-8"`→`None`/`"UTF-8"`.** `"UTF-8"` is an alias; `None` = platform
  default = utf-8 on Linux (CI). Equivalent on Linux — the binary-file skip still triggers
  because a non-UTF-8 file fails to decode either way.
- **1 — `ValueError(msg)`→`ValueError(None)`.** The escape guard still *raises* `ValueError`;
  the contract asserts the exception type, not the (unpinned) message. Equivalent.
- **1 — `self._root = None` (in `__init__`).** Survives because `self._root` is **never read**
  (`_workspace`/`_context` derive from the `root_path` parameter directly). A harmless dead
  attribute; candidate for a one-line cleanup (drop `self._root`), not a bug.

## Addendum — list_files hardening (ADR 0008 #1/#2)

`list_files` was later hardened (round-2 cleanup, 2026-06-26). Its public signature is
unchanged, so these four behaviors are pinned by named tests in `test_workspace.py`
rather than new C-items:

- `test_list_files_lists_extensionless_text_file` — (a) no extension allowlist; a
  `Dockerfile` is listed.
- `test_list_files_skips_file_with_leading_nul_byte` — (b) a NUL byte in the prefix
  disqualifies a file.
- `test_list_files_lists_large_text_file_sniffing_only_prefix` — (c) the read is bounded
  to ~8 KB: a file clean for its first 8 KB but carrying a NUL far past the window is
  still listed, proving the whole file is not validated.
- `test_list_files_skips_symlink_resolving_outside_context` — (d) the containment guard
  (`resolve()` + `is_relative_to`) is applied at listing time, mirroring C25 for
  `read_file`, so picker and reader agree.
