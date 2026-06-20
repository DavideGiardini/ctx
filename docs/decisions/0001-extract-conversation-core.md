# 0001 — Extract ConversationCore from ChatApp

**Status:** Accepted

## Context

`ChatApp` was a ~495-line zero-depth god orchestrator: it inlined command
parsing, mode switching, the streaming lifecycle, persistence triggers, and
direct widget manipulation into a single Textual `App` subclass. Its interface
(event handlers) *was* its implementation — there was no seam between the UI
framework and application state, so testing any command required booting the
entire TUI.

## Decision

Extract a `ConversationCore` module (`ctx/core/conversation.py`) that owns the
conversation state machine: `nodes`, active `model`, `conversation_id`/title, and
the streaming lifecycle. The UI (`ctx/ui/app.py`) becomes a thin adapter.

- **Pull interface.** Commands return typed results (`submit(text) -> (Node, Node)`,
  `set_model(model) -> Node`); every UI action is a request, so no callback
  protocol is needed.
- **UI owns the Textual worker.** The `@work` shell stays in `ChatApp`; the core
  exposes `async def stream(...) -> AsyncIterator[str]` which the UI drives.
- **Core owns persistence**, via an injected `StoragePort` protocol (mockable).
- Moved `DEFAULT_MODEL` and `MAX_TITLE_LENGTH` constants into `conversation.py`.

Widget management, focus, mode switching, screen handling, keyboard navigation,
and message selection stay in `ChatApp`.

## Consequences

- `ChatApp` shrank to a UI adapter; `conversation.py` is pure Python with zero
  `textual` imports and is testable in isolation.
- Established the core/UI seam and the injected-port pattern that ADRs 0002–0005
  build on.
- Some temporary bridges were introduced here and later removed: a callback→queue
  streaming bridge (resolved by [0002](0002-provider-protocol.md)), a
  `StorageAdapter` pass-through (resolved by [0003](0003-conversation-repository.md)),
  impure context loading (resolved by [0004](0004-pure-context-builder.md)), and a
  hardcoded workspace path (resolved by [0005](0005-inject-workspace.md)).
