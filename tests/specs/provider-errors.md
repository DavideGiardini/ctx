# Behavioral contract: ProviderError + stream timeout on the Provider seam

Source of intent: PRD task + ADR 0011 #1. Module under test: `ctx/core/provider.py`
(`ProviderError`, `STREAM_TIMEOUT`, `LiteLLMProvider.stream`) and the
`ConversationCore.stream` consumption path in `ctx/core/conversation.py`.

The single guarantee being defended: backend (litellm) exception types must never
leak through the `Provider` seam; callers catch one domain type, `ProviderError`,
and the original is recoverable via `__cause__`. A finite request timeout must be
handed to the backend so a hung connection cannot keep a stream open forever.

---

PE1. Backend failure at REQUEST time wraps as ProviderError
  Given:    A `LiteLLMProvider`, with the backend entry point (`acompletion`)
            monkeypatched to raise a backend-specific exception (e.g. RuntimeError)
            synchronously when awaited — before any chunk is produced.
  Expect:   Iterating `provider.stream(messages, model)` raises `ProviderError`
            (not the raw RuntimeError). `exc.__cause__` is the original RuntimeError
            instance (identity preserved via `raise ... from exc`).
  Rationale:ADR 0011 #1: request-time backend errors must not leak the backend type;
            callers handle one domain type and can still inspect the original cause.

PE2. Backend failure MID-STREAM wraps as ProviderError, preserving prior tokens
  Given:    A `LiteLLMProvider` whose backend returns an async iterator that yields
            one or more valid chunks and then raises a backend exception during
            iteration.
  Expect:   The already-produced deltas are yielded as plain strings, and then the
            iteration raises `ProviderError` with `exc.__cause__` being the original
            backend exception instance.
  Rationale:Mid-stream failures are still provider failures; per the docstring they
            are wrapped identically to request-time failures, and partial output
            already delivered to the consumer must not be discarded.

PE3. STREAM_TIMEOUT is a positive finite number and is passed to the backend
  Given:    A `LiteLLMProvider` with a fake backend that records the kwargs it was
            called with; drive `stream` to completion.
  Expect:   `STREAM_TIMEOUT` is a real number, strictly > 0, finite (not inf/NaN);
            and the backend was invoked with a `timeout` kwarg whose value equals
            `STREAM_TIMEOUT`.
  Rationale:The finite request timeout is the mechanism that prevents a hung
            connection from holding a stream open indefinitely; the seam must hand
            it to the backend, and a non-finite/non-positive bound would be useless.

PE4. Happy path yields content deltas in order as plain strings, no wrapping
  Given:    A `LiteLLMProvider` with a fake backend that yields a known ordered
            sequence of content chunks and never raises.
  Expect:   `stream` yields exactly those contents, in the same order, each a plain
            `str` (not chunk/SimpleNamespace objects), and raises nothing — no
            `ProviderError` is produced on a clean stream.
  Rationale:The adapter's job is to surface content deltas as strings; wrapping is
            reserved for failures, so a clean stream must be transparent.

PE5. CancelledError / GeneratorExit are NOT wrapped
  Given:    A `LiteLLMProvider` whose backend raises `asyncio.CancelledError`
            (cancellation signal, not a provider failure) during streaming.
  Expect:   The raised exception is `asyncio.CancelledError` (or a subclass), NOT a
            `ProviderError`. Cancellation propagates as cancellation.
  Rationale:Docstring is explicit: cancellation signals are not provider failures
            and must not be masked as `ProviderError`, or cancellation/shutdown
            semantics break.

PE6. ProviderError flows through ConversationCore.stream unchanged; partial persisted
  Given:    A `ConversationCore(repo, provider, workspace)` after `setup()` and
            `submit(...)`, where the provider's `stream` yields some tokens and then
            raises a specific `ProviderError` instance.
  Expect:   Driving `core.stream(assistant_node)` raises the SAME `ProviderError`
            object (identity, not merely the same type), AND afterward
            `repo.load(core.conversation_id)` contains an assistant node whose
            `content` equals the concatenation of the tokens streamed before the
            failure (the partial content persisted).
  Rationale:Intent: on any exception during streaming, partial assistant content is
            persisted and the original exception re-raised unchanged. `ProviderError`
            is an ordinary exception on this path; nothing special wraps/rewraps it,
            and no partial output is lost.

---

## Intent ambiguities (flagged for human resolution)

- A1 (PE4): "plain strings" — I assume `None`-content chunks (litellm emits delta
  objects with `content=None`, e.g. role-only or final chunks) are skipped rather
  than yielded as the string `"None"` or as `None`. The docstring says "content
  deltas (plain strings)", which implies non-string/None deltas are not yielded, but
  it does not state the skipping rule explicitly. PE4 only asserts on chunks with
  real string content to avoid coupling to an unstated rule. If skipping is intended,
  add a dedicated contract item.
- A2 (PE2): The docstring does not state whether mid-stream tokens already yielded to
  the consumer are retained vs. retracted. I assume they are retained (you cannot
  un-yield a value from an async iterator), so PE2 asserts the pre-failure tokens were
  observed before the `ProviderError`.
- A3 (PE6): "persists the partial content" — I assume the persisted assistant content
  equals exactly the tokens yielded before the failure (no trailing markers/trimming).
  If the core normalizes/trims content on persist, this expectation needs adjusting.
- A4 (PE3): I assume the kwarg name handed to the backend is literally `timeout`
  (per the repo convention note: "assert a `timeout` was passed"). If the backend
  arg is named differently, PE3's kwarg-name assertion must change.
