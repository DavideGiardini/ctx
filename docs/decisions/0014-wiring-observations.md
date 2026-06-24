# 0014 — System-level / wiring observations

**Status:** Notes (no action required)

## Context

Cross-cutting observations from stepping back and looking at how the core modules
wire together (not issues inside any single module). The dependency skeleton is
sound — `core/` never imports `ui/`, `models/nodes` is a leaf, `conversation.py` is
the only core module depending on the others, and `ChatApp.__init__` is a real
single composition root with genuine injection seams. The notes below are about the
connective tissue.

## Observations

### 1. No single source of truth for "what kind of node is this"

A `Node`'s kind is over-determined by five overlapping signals — `role`,
`node_type`, `conversation_id` (present/absent), `content` semantics (payload vs.
label), and `meta` (e.g. `source_path`). A context node must satisfy all five at
once, and nothing enforces the combination: `Node(...)` is a bare dataclass, so
invalid mixes (a `system` node *with* a `conversation_id`, a `context` node with no
`source_path`) are constructible and silently misbehave.

Worse, three subsystems each key off a *different* facet: persistence on
`conversation_id`, context-building on `role`, UI rendering on `role` + `node_type`.
They agree today by coincidence of construction, not design (cf. 0006 #6). A single
classifier — factory constructors (`Node.context(...)`, `Node.system(...)`) plus
derived predicates (`is_durable`, `goes_to_model`) — would establish the invariants
once and let every subsystem read the same answer instead of re-deriving it. This
is the deepest structural debt in the core.

### 2. A conversation's model is never persisted

`ConversationCore.model` is in-memory conversation state, but it is never written:
`save()` is `save(conversation_id, title, nodes)`, the `conversations` table has no
`model` column, the `set_model` breadcrumb node is filtered out (no
`conversation_id`), and `resume_conversation()` restores nodes/id/title but **not**
model. Net: switching model and then resuming another conversation (or restarting)
silently loses the model — you fall back to whatever is active, or `DEFAULT_MODEL`.
Conceptually the model belongs to the conversation; the wiring treats it as a global
session setting. Closest thing here to an actual user-facing bug.

### 3. The "pure" core leans on a global logger (and build_context isn't side-effect-free)

ADR 0004 calls `build_context` "pure … no side effects", but it calls
`logger.warning(...)` on bad/unreadable context nodes — logging is I/O. The *return
value* is deterministic, but "no side effects" is overstated. More broadly, every
core module imports the module-level `logger` singleton (`ctx.core.log`) — the one
ambient global the otherwise framework-free core never pushed to a seam. Low-harm
and conventional, but worth not pretending it isn't there.

### 4. The failure model is ad hoc across modules

How a failure reaches the user is decided independently per module, in four
different styles: `context.py` logs-and-skips (silent), `provider.stream` raises raw
backend exceptions, `check_connectivity` returns `(bool, str)`, and
`resume_conversation` returns `[]` for an unknown id. No unified domain error
strategy, which is why (e.g.) a failed context load is invisible (0007 #1) while a
stream failure surfaces loudly.
