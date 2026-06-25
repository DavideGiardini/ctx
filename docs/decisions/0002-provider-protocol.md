# 0002 — Deepen provider.py with a Provider protocol

**Status:** Superseded by [0010](0010-connectivity-on-provider-seam.md)
(the `check_connectivity` decision below no longer holds — it is now a protocol
method, not a module-level function)

## Context

`stream_response` forced callers into an inversion-of-control callback pattern
(`on_token`, `on_done`, `on_error`) nearly as complex as writing the stream loop
themselves, and passed `list[dict]` (litellm's native wire format) straight
through with no domain adapter. Only one implementation existed (litellm), so the
seam was hypothetical. The callback shape also forced a fragile `asyncio.Queue`
bridge inside `ConversationCore.stream()` (see [0001](0001-extract-conversation-core.md)).

## Decision

Define a `Provider` protocol with a single deep method:
`def stream(self, messages: list[dict], model: str) -> AsyncIterator[str]`
(not `async def` in the protocol — the return type is already an async iterator;
implementations are `async` generators).

- **Two adapters make the seam real:** `LiteLLMProvider` wraps
  `litellm.acompletion(stream=True)`; `TestProvider` yields tokens from a list.
- `check_connectivity` stays a module-level function — a one-off probe that
  doesn't need to cross the seam.

## Consequences

- `ConversationCore.stream()` collapsed from a ~35-line queue bridge to a simple
  `async for token in self._provider.stream(...)`; the `asyncio.Queue`/`_bridge`
  task and unused `asyncio`/`contextlib` imports were deleted.
- `TestProvider` is what makes the headless agent harness
  (`tools/agent/harness.py`) deterministic and network-free.
- This is the canonical example of "introduce a Protocol seam only once a second
  real implementation exists."
