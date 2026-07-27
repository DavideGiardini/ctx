# 0018 — Tool calling on the provider seam, and tool history replayed as text

## Status

Accepted (2026-07-26)

## Context

ctx0 Phase 4 gives the model two web tools — `search(query)` and `fetch(url)` —
whose results become nodes in the conversation graph (concept §4.4, plan:
`docs/ctx0 Phase 4 Plan — Web search.md`). Function calling is the first change
to the `Provider` seam's shape since ADR-0015, and it forces two decisions that a
later session would otherwise re-derive — one of them wrongly.

**First**, how do tool calls cross the seam? ADR-0015 chose an `on_usage`
callback over widening `stream()`'s element type to a union, and closed with an
explicit caveat: *"if a future need arises for multiple mid-stream signals (e.g.
tool-call events), revisit: a richer event seam may then earn its keep."* This is
that future need, so the caveat has to be answered rather than assumed either way.

**Second**, and less obviously: once a tool round-trip has happened, how is it
represented on *subsequent* requests? The OpenAI/Anthropic wire protocol has a
specific shape for this — an assistant message carrying `tool_calls`, answered by
`role="tool"` messages keyed by `tool_call_id`. The obvious move is to store
those ids on the nodes and replay them faithfully forever. That obvious move is
wrong here, and the reason is not visible from the provider side at all.

## Decision

### 1. Tool calls cross the seam via an `on_tool_calls` callback

```
Provider.stream(messages, model, on_usage=None,
                tools=None, on_tool_calls=None) -> AsyncIterator[str]
```

`stream()` keeps yielding plain `str`. A new frozen `ToolCall(id, name,
arguments)` dataclass is the domain type; litellm's chunk objects never cross the
seam, the same discipline `Usage` established. `LiteLLMProvider` accumulates
`chunk.choices[0].delta.tool_calls` deltas by index internally and fires
`on_tool_calls(calls)` exactly once when the response ends in tool calls.

**Why the callback still wins, despite ADR-0015's caveat.** The caveat was about
*multiple mid-stream signals*. A tool-call batch is not one: it is complete at the
end of a response (`finish_reason == "tool_calls"`), so like `Usage` it is an
at-most-once, out-of-band value. The delta accumulation is real but it is an
implementation detail of the adapter, not a property of the seam. Widening the
yielded type to `str | ToolCall` would tax the consumer on every chunk to service
a value that arrives at most once at the end — exactly the trade ADR-0015
rejected — and it would push the union through `ConversationCore.stream()` into
the UI's `async for token` loop, which is otherwise untouched by this whole phase.

Revisit this only if a provider starts emitting signals that are genuinely
mid-stream and interleaved with text (partial tool arguments the caller must act
on before the response ends, say). Accumulating deltas privately does not count.

### 2. The tool loop lives in `ConversationCore`, not in the provider

`ConversationCore.stream()` owns the round loop: build the request, stream text
into the current assistant node, execute any returned tool calls, append their
nodes, and go again up to the configured cap. The provider stays a single-request
adapter.

This follows from where the state is. Each tool result becomes a graph node with
a `created_seq`, and node creation, the `ctx_hash` stamp, and persistence are all
core responsibilities. A provider that owned the loop would have to call back into
the core to create nodes, inverting the dependency for no gain.

Newly appended nodes reach the UI through an `on_node` async callback supplied to
`stream()` — the same out-of-band shape as `on_usage`, for the same reason: the
token stream stays `str`. A sibling `on_tool_round` fires once per round that
settles on tool calls, *before* those calls run: a tool's node cannot announce the
wait it is about to cause, because it does not exist until the search or fetch has
returned. That is what lets the view retire a silent round's `▌` caret for the
duration of the web work instead of leaving it standing in for an answer that is
not coming.

### 3. Tool history is replayed as text, not natively

**Within the live turn**, the round-trip uses the native protocol. Strict
providers (the Anthropic family) require every `tool_use` id to be answered by a
matching `tool_result`, so there is no choice. To keep `build_context`'s
role-alternation invariant intact, the loop builds the base context once from the
nodes that existed before the turn and appends round-trip messages to a
turn-local list, rather than re-deriving them from the graph.

**On every subsequent turn**, those same nodes are rendered by
`model_facing_form` as ordinary XML-wrapped user content —
`<search_results query="…">` for a search node, the existing
`<context_import source="…">` for a fetched page — and **never** as native tool
messages. Their `tool_call_id`s are not persisted, because nothing may depend on
them.

**Why, and this is the load-bearing part:** compaction. A tool node is a node
like any other, so the user can fold it into a `K` (ADR-0016). If history were
replayed natively, compacting a search node would leave an assistant `tool_call`
with no matching `tool_result`, and the very next request would be rejected by
the provider — a one-way door where ctx0's central verb silently corrupts the
conversation. Text replay makes tool output exactly as foldable, expandable and
editable as an import, at the cost of the model no longer seeing that a past
result came from a tool call rather than from the user. That cost is the right
one to pay: it is also the more ctx-shaped answer, since a search result is
context the user controls, not an opaque protocol artifact.

### 4. Two web tools, two node representations

`search` is a new node type (`Node.search`, added to `goes_to_model()`, its own
truncation key): a query plus a ranked hit list is a new shape in the graph, so
it needs its own model-facing form and its own inspector splits. It is *not* a
new color — it renders in the context-import green, like every other block of
material injected into the conversation for the model to read (a search is not
"a different kind of thing" from an import; it is an import the model asked
for). `fetch` reuses the existing `context` node with `source_path` set to the
URL — a fetched page *is* an import whose source happens to be a URL, with the
same content-on-node storage, wrapper, inspector and weight accounting.

### 5. No search-backend abstraction of our own

litellm's `asearch(query, search_provider=…)` already normalizes fourteen
backends behind one call. A `SearchBackend` Protocol is injected into
`ConversationCore` (real adapter + test double, so the seam is real by the
ADR-0002 rule), but nothing below it: per-backend adapters of our own would be a
shallow module wrapping a wrapper, and the deletion test says so. Swapping
backends is one config line, which is exactly what concept §7 asked for.

## Consequences

- The UI's streaming path is unchanged: `ConversationCore.stream()` still yields
  `str`, and `end_turn` remains the single owner of how a turn ends (Phase 1).
- `Node` gains one kind. `goes_to_model()`, the color palette, and
  `ui.truncation_lines` each gain one entry.
- Search and fetch nodes are compactable and expandable with no special-casing,
  because they are model-facing text like everything else.
- Because tool ids are not persisted, a resumed conversation can never replay a
  native tool round-trip. This is intended; if a future version wants faithful
  replay it must first answer what compaction does to it.
- A turn can now append several nodes, so any code assuming "one submit → one
  user node + one assistant node" is invalidated. Notably, a turn that opens with
  a silent tool call leaves the `submit()`-created assistant node empty, and the
  append-only graph cannot remove a node from the middle of the line — the view
  drops zero-content assistant nodes that are not the live streaming target,
  generalizing the phantom-row rule already established for zero-token cancels.
- ADR-0009 (imports are live, not snapshots) is already superseded by ctx0's
  content-on-node imports; fetched pages follow the same content-on-node rule.
