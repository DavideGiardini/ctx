# 0005 — Inject Workspace as a class

**Status:** Accepted

## Context

`workspace.py` exposed free functions that relied on `Path.cwd()` (global process
state), hardcoded the `.ctx` directory name, and mixed UTF-8 validation into file
listing by reading every file's contents. `ConversationCore.setup()` called
`ensure_workspace()`, ambiently coupling the core to the working directory.

## Decision

Introduce a `Workspace` class instantiated with a root path and injected
everywhere.

- **Constructor:** `Workspace(root_path: Path)` — the root is the working
  directory, not `.ctx` itself; the class computes `workspace_path`,
  `context_dir`, and `db_path` from it.
- **Unified file access:** `Workspace.read_file(rel_path)` replaces the old
  `read_context_file`, superseding the separate `file_loader` parameter from
  [0004](0004-pure-context-builder.md). Methods: `ensure()`, `list_files()`,
  `read_file()`.
- **Composition root:** `ChatApp` creates one `Workspace(Path.cwd())` and passes
  it to `ConversationRepository`, `ConversationCore`, `IncludeScreen`,
  `FileViewer`, and `FileViewerScreen`.

## Consequences

- The single `Path.cwd()` call is now isolated to `ChatApp.__init__`; all
  downstream components are testable with a temp directory. This is exactly what
  makes `HarnessApp` (`tools/agent/harness.py`) able to run in an ephemeral temp dir.
- Validation still lives in `list_files()` (coupled to listing), but is now local
  to the workspace module — an accepted, bounded compromise.
