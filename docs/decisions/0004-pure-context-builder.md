# 0004 — Make context.py pure via an injected file loader

**Status:** Accepted

## Context

`build_context` looked like a pure domain transformer (`Node` → message dicts),
but it secretly performed filesystem I/O by calling `read_context_file` from
`workspace.py`. You could not test message assembly without creating real files
in `.ctx/context/` or mocking the workspace module — a locality/testability
problem inherited from [0001](0001-extract-conversation-core.md).

## Decision

Make `build_context(nodes, load_file)` pure: `load_file: Callable[[str], str]` is
a required parameter, called instead of importing `read_context_file`. The loader
is injected at the call site.

- `ConversationCore` receives the loader in `__init__` and passes it to
  `build_context`.
- `ChatApp`, as the composition root, wires the real `read_context_file`.
- `context.py` no longer imports `workspace.py` at all.

## Consequences

- `context.py` is a pure transformer: same inputs → same outputs, no side effects.
  Tests pass a stub loader (`build_context(nodes, load_file=lambda p: "stub")`).
- The injected loader was later unified into `Workspace.read_file` — see
  [0005](0005-inject-workspace.md).
