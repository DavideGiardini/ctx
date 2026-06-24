# 0011 — provider.py observations

**Status:** Notes (no action required)

## Context

Noticed while reading `ctx/core/provider.py`. Not a bug; recorded so it isn't
rediscovered later.

## Observation

### `LiteLLMProvider.stream` has no timeout or error typing, and assumes chunk shape

- **No timeout.** A hung connection keeps the stream open until the user cancels
  it; there is no upper bound on how long a token can take to arrive.
- **Raw error propagation.** Exceptions from `acompletion` propagate unwrapped (as
  litellm exceptions) up to `ConversationCore.stream`'s `except Exception:
  persist(); raise`. Callers can't distinguish error kinds without catching litellm
  types — i.e. the backend leaks through the seam.
- **Chunk-shape assumption.** `chunk.choices[0].delta.content` assumes a non-empty
  `choices` list and the `delta`/`content` attributes. litellm normally normalizes
  this, but a malformed chunk would raise `IndexError`/`AttributeError`.

If graceful "model stalled / network error" handling is ever wanted, this method is
the place: add a timeout and map backend exceptions to a small domain error type so
the seam stops leaking litellm.
