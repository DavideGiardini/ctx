# 0015 — Report provider token usage via an `on_usage` callback

**Status:** Accepted

## Context

The context-budget UI (Sprint 1) needs the *exact* prompt-token count a provider
billed for a turn, to sharpen its local tiktoken estimate into a calibrated
header gauge (`ctx/core/tokens.gauge`). litellm can surface this: passing
`stream_options={"include_usage": True}` makes the backend emit a final stream
chunk whose `choices` is empty and which carries a `usage` object
(`prompt_tokens`/`completion_tokens`/`total_tokens`).

The `Provider` seam (ADR 0002, 0010) deliberately yields a stream of plain
`str` tokens — `stream(messages, model) -> AsyncIterator[str]`. Usage is a
*different kind of value* arriving on the *same* stream. We had to decide how to
get it across the seam without leaking litellm types or complicating every
caller that only wants tokens.

Two shapes were on the table:

1. **Widen the stream's element type** to a `str | StreamChunk` union (or yield
   `StreamChunk` objects with `.text`/`.usage` fields). Every consumer would then
   have to discriminate the union on every iteration.
2. **Deliver usage out-of-band** via an optional callback the caller passes in:
   `stream(messages, model, on_usage=None)`.

A latent bug forced the issue regardless: the existing loop did
`chunk.choices[0].delta.content`, which `IndexError`s on the empty-`choices`
usage chunk the moment `include_usage` is on.

## Decision

Add an optional `on_usage: Callable[[Usage], None] | None = None` parameter to
`Provider.stream` and both implementations. `stream` keeps yielding plain `str`.

- A small framework-free `Usage` dataclass (`prompt_tokens`, `completion_tokens`,
  `total_tokens`) is the domain type; litellm's usage object never crosses the
  seam.
- `LiteLLMProvider` passes `stream_options={"include_usage": True}`, guards the
  chunk loop so an empty-`choices` chunk is tolerated (content is read only when
  `chunk.choices` is non-empty), and — when a chunk carries `usage` and a
  callback was supplied — invokes `on_usage(Usage(...))` exactly once.
- `TestProvider` takes an optional `usage: Usage | None = None`; after streaming
  its tokens it calls `on_usage(usage)` only when both `usage` and the callback
  are present. The default `None` keeps the `test_provider` fixture and every
  existing `provider.stream(messages, model)` caller green.

**Why callback over union:** usage is optional, at-most-once, and orthogonal to
the token text. A union tax every consumer on every chunk to service a value
that arrives at most once at the end; the callback confines that cost to the one
caller (`ConversationCore`, Task 5) that actually wants calibration. The token
stream stays a clean `AsyncIterator[str]`, so the app's `async for token`
streaming worker is untouched. This is provider-agnostic: a provider that never
reports usage simply never calls the callback, and passing `on_usage` is always
safe and never required.

## Consequences

- Backward compatible: callers that ignore usage pass nothing and see no change.
- The empty-`choices` guard fixes a real latent crash that `include_usage` would
  otherwise trigger.
- `ConversationCore.stream` (Task 5) supplies an `on_usage` that sanity-checks
  the count against its local sum and stores a calibration ratio for the gauge.
- If a future need arises for *multiple* mid-stream signals (e.g. tool-call
  events), revisit: a richer event seam may then earn its keep. For one
  at-most-once usage value, the callback is the minimal seam.
