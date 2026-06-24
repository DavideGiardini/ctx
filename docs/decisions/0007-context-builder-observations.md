# 0007 — context.py (build_context) observations

**Status:** Notes (no action required)

## Context

Things we noticed while reading `build_context` in `ctx/core/context.py`.
Neither is a bug; recorded so the understanding isn't rediscovered later.

## Observations

### 1. A context file that fails to load disappears silently

When `load_file(source_path)` raises `OSError`/`ValueError` (missing file,
permission, decode error), `build_context` logs a warning and `continue`s — the
context node is skipped. The file simply never reaches the LLM, and the **UI shows
nothing**; the only trace is a line in `~/.local/state/ctx/ctx.log`. So a user can
believe an `/include`d file is in context when it silently isn't.

Given the product's "informs visually" stance, a stale/error marker on the node
(rather than a silent skip) would fit better. Worth keeping in mind, not urgent.

### 2. Empty nodes become empty messages

A cancelled or failed stream can leave an `assistant` node with `content=""` saved
to history. On a later `build_context`, that becomes `{"role": "assistant",
"content": ""}`. Several provider APIs reject empty-content messages, so this can
surface as a confusing API error when resuming such a conversation. `stream()`
excludes the *current* placeholder via `[:-1]`, but a *previously saved* empty node
is not protected.

### 3. The `<context_import>` wrapper is built without escaping (future injection risk)

`build_context` wraps file content with a naive f-string:

```python
node_content = f'<context_import source="{source_path}">\n{content}\n</context_import>'
```

Neither `source_path` (attribute) nor `content` (body) is escaped. The closing tag
is just the literal text `</context_import>`, so if a file's content contains that
string, the model sees the file's copy as the *real* end of the fence — everything
after it reads as direct user instructions rather than imported data. The wrapper's
whole job is to fence imported material off as data, and forged delimiters defeat
that. Same class of flaw as SQL injection: untrusted text stuffed into a structured
template that uses an in-band delimiter.

Low risk **today** — the only import source is the user's own KB files, and the
product is "power over protection." It becomes real once imports come from
less-trusted sources the Product Concept plans (RAG results, other conversations,
web/MCP content — §3–5). Fix when that lands: escape `<`/`>`/`&` in the body (and
quotes in the attribute), or stop relying on an in-band text delimiter.
