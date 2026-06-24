# 0010 — check_connectivity crosses the Provider seam

**Status:** Accepted (supersedes [0002](0002-provider-protocol.md))

## Context

[0002](0002-provider-protocol.md) introduced the `Provider` protocol and stated
that `check_connectivity` would "stay a module-level function … that doesn't need
to cross the seam." The implementation evolved past that: `check_connectivity` is
now a method on the `Provider` protocol and on both adapters. This ADR records the
current shape so 0002's stale detail isn't taken as canonical. The rest of 0002's
decision (the protocol, the two adapters, the `def`-not-`async def` signature)
still stands and is restated here for completeness.

## Decision

`Provider` is a Protocol describing a complete LLM backend through **two** methods,
both of which cross the seam:

- `def stream(self, messages: list[dict], model: str) -> AsyncIterator[str]` —
  declared `def` (not `async def`) because the async-generator implementations are
  *called* synchronously to obtain the iterator; awaiting happens inside `async for`.
- `async def check_connectivity(self, model: str) -> tuple[bool, str]` — a
  reachability probe. It belongs on the seam because each backend needs its own:
  `LiteLLMProvider` fires a single-token network probe; `TestProvider` returns
  `(True, "ok")` with no network.

Two real adapters keep the seam real: `LiteLLMProvider` (wraps
`litellm.acompletion`) and `TestProvider` (canned tokens, network-free — powers the
agent harness).

## Consequences

- Everything in 0002's Consequences still holds (the `asyncio.Queue` callback bridge
  was removed; `ConversationCore.stream` is a plain `async for`).
- The `Provider` seam now fully describes a backend: streaming **and** connectivity.
  A new backend implements both methods.
