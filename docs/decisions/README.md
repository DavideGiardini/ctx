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
| [0002](0002-provider-protocol.md) | Deepen provider.py with a Provider protocol | Accepted |
| [0003](0003-conversation-repository.md) | Deepen storage.py into a ConversationRepository | Accepted |
| [0004](0004-pure-context-builder.md) | Make context.py pure via an injected file loader | Accepted |
| [0005](0005-inject-workspace.md) | Inject Workspace as a class | Accepted |
