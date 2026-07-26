# Architecture Decision Records

This directory records **why** the `ctx` architecture is the way it is, so that
agents and humans don't re-litigate settled decisions. Read the relevant ADR
before reopening a design question.

These ADRs are the canonical source consulted by the `/improve-codebase-architecture`
skill and the "Designing new modules" guidance in `AGENTS.md`.

## Design philosophy

`ctx` is built on **deep modules**: a simple interface hiding a substantial
implementation. The shared vocabulary — *module, interface, depth, seam, adapter,
leverage, locality* — and its principles (the **deletion test**, "the interface
is the test surface", "one adapter = hypothetical seam, two = real") drive every
decision here. Core domain logic (`ctx/core/*`) stays free of `textual` imports;
the UI is a thin adapter over it.

## Format

One file per decision: `NNNN-short-title.md` with sections **Status**,
**Context**, **Decision**, **Consequences**. Status is one of `Accepted`,
`Superseded by NNNN`, or `Proposed`. ADRs are immutable once accepted — supersede,
don't rewrite.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-extract-conversation-core.md) | Extract ConversationCore from ChatApp | Accepted |
| [0002](0002-provider-protocol.md) | Deepen provider.py with a Provider protocol | Superseded by 0010 |
| [0003](0003-conversation-repository.md) | Deepen storage.py into a ConversationRepository | Accepted |
| [0004](0004-pure-context-builder.md) | Make context.py pure via an injected file loader | Accepted |
| [0005](0005-inject-workspace.md) | Inject Workspace as a class | Accepted |
| [0006](0006-conversation-core-followups.md) | ConversationCore observations | Notes |
| [0007](0007-context-builder-observations.md) | context.py (build_context) observations | Notes |
| [0008](0008-workspace-observations.md) | workspace.py observations | Notes |
| [0009](0009-imports-live-not-snapshots.md) | File imports are live, not snapshots (§3.3 gap) | Notes |
| [0010](0010-connectivity-on-provider-seam.md) | check_connectivity crosses the Provider seam | Accepted |
| [0011](0011-provider-observations.md) | provider.py observations | Notes |
| [0012](0012-agent-tooling-should-not-ship.md) | agent/ is dev-only tooling but currently ships | Notes |
| [0013](0013-storage-observations.md) | storage.py observations | Notes |
| [0014](0014-wiring-observations.md) | System-level / wiring observations | Notes |
| [0015](0015-usage-off-the-stream.md) | Report provider token usage via an `on_usage` callback | Accepted |
| [0016](0016-append-only-conversation-graph.md) | Conversation state is an append-only node graph (no op log, no soft-delete) | Accepted |
| [0017](0017-ctx0-rescope.md) | Re-scope to ctx0: ship a smaller, complete product | Accepted |
| [0018](0018-tool-calling-on-the-provider-seam.md) | Tool calling on the provider seam, and tool history replayed as text | Accepted |
