# Behavioral contract — `ctx/core/provider.py`

The oracle of record for the `Provider` seam and its two implementations. Authored
code-blind from intent (see `.claude/skills/write-tests`), then human-adjudicated.
Tests in `tests/test_provider.py` cite these item ids. **When behavior changes, update
this contract first**, then the tests.

`Provider` is the streaming-LLM seam: `stream(messages, model) -> AsyncIterator[str]`
yields the assistant's reply token-by-token, and `check_connectivity(model) -> (ok, msg)`
probes whether a model is reachable without ever raising. Two implementations exist:

- **`TestProvider`** — a deterministic double that streams a fixed token list and reports
  constant health. Covered by C1–C4 (the `TestProvider` section below).
- **`LiteLLMProvider`** — the production adapter over `litellm.acompletion`. It is the
  thin translation layer between ctx and litellm; its job is to forward the request to
  litellm asking for a stream, surface the upstream's content deltas as plain strings, and
  turn a connectivity probe into a non-raising `(ok, message)` verdict. Covered by C5–C9.

### Test seam for `LiteLLMProvider` (adjudicated A1)

`LiteLLMProvider` calls the module-level name `litellm.acompletion`, imported into
`ctx.core.provider` as `acompletion`. Tests isolate it from the network by monkeypatching
`ctx.core.provider.acompletion` with a fake **async** callable — **no real network I/O**.
The upstream contract this adapter speaks to (litellm's documented response shape) is part
of the seam, not a ctx secret:

- For **streaming** (`stream=True`): the awaited call yields an async iterator of *chunk*
  objects; each chunk exposes `chunk.choices[0].delta.content`, a `str` token or `None`
  (litellm emits `None`/empty content on role-only and finish chunks). The fake returns an
  async iterator of such chunk-shaped objects.
- For the **connectivity probe** (`stream=False`): the awaited call either returns a
  response object (success) or raises an exception (failure). The fake returns a sentinel
  on success, or raises to simulate failure.

Expected values come from intent (below), never from reading the implementation.

## Contract

### `TestProvider` (deterministic double)

**C1. `stream` yields exactly the constructor tokens, in order.**
Given `TestProvider(tokens)` → `stream(...)` yields exactly `tokens`, in order, preserving
duplicates; a single-element list yields that one token; an empty list yields nothing.

**C2. `TestProvider.stream` output is independent of `messages` and `model`.**
Given the same `TestProvider`, two `stream` calls with different `messages` and `model`
yield identical token sequences (the double ignores both arguments).

**C3. (folded into C1)** empty token list yields nothing.

**C4. `TestProvider.check_connectivity` returns a constant healthy verdict.**
For any `model`, `check_connectivity(model)` returns `(True, "ok")`, independent of the
model argument.

### `LiteLLMProvider` (production adapter)

**C5. `stream` surfaces the upstream content deltas as plain strings, in order.**
Given an upstream stream of chunks whose `delta.content` values are `"Hello"`, `" world"`
→ `LiteLLMProvider().stream(messages, model)` yields exactly `["Hello", " world"]`, in that
order. The adapter unwraps `chunk.choices[0].delta.content` and yields the raw token string.

**C6. `stream` drops empty/`None` content deltas.** *(adjudicated A2: a chunk carrying no
text — `None` or `""` content, as litellm emits for role-only/finish chunks — contributes
no token; only non-empty deltas are forwarded.)*
Given an upstream stream whose `delta.content` values are `"a"`, `None`, `""`, `"b"` →
`stream(...)` yields exactly `["a", "b"]` — the `None` and `""` chunks are skipped, not
yielded as `None`/`""`.

**C7. `stream` requests a streamed completion for the caller's model and messages.**
Given `stream(messages, model)` → the adapter invokes the upstream with `stream=True`, and
forwards the caller's `model` and `messages` through unchanged (observable via the
monkeypatched `acompletion`'s captured arguments). *(Format pinned only to: streaming
requested, and model/messages passed through; other kwargs not asserted.)*

**C8. `check_connectivity` returns an affirmative verdict when the probe succeeds.**
Given an upstream probe that returns normally → `check_connectivity(model)` returns a tuple
`(True, msg)` where `ok is True` and `msg` is a non-empty string that mentions the `model`.
It does not raise.

**C9. `check_connectivity` converts an upstream failure into a negative verdict, never
raises.** *(adjudicated A3: connectivity is a best-effort probe — any upstream exception is
reported, not propagated, so a model that cannot be reached degrades gracefully.)*
Given an upstream probe that raises an exception carrying a recognizable message → 
`check_connectivity(model)` returns `(False, msg)` where `ok is False` and `msg` is a string
reflecting the failure (contains the upstream error's text). The exception does not escape.

## Adjudication notes
- **A1 (test seam):** `LiteLLMProvider` is tested by monkeypatching
  `ctx.core.provider.acompletion`; no network. The litellm chunk shape
  (`chunk.choices[0].delta.content`) is the documented upstream seam, fair to encode in the
  fake. Reversed the earlier "out of scope (network)" stance for the adapter's pure
  translation logic (the delta filter and the connectivity verdict), which needs no network.
- **A2 (empty deltas):** dropped, not yielded — only non-empty content tokens reach the
  caller (C6).
- **A3 (connectivity never raises):** any upstream exception becomes `(False, <msg>)`; the
  probe is advisory and must not take down the caller (C9).
- **Log channel not asserted.** `LiteLLMProvider` logs at info/warning; like the other
  modules, log text is a diagnostic side-channel and is not part of any oracle.

## Mutation testing (mutmut)
Focused run: `scripts/mutate.sh run 'ctx.core.provider.*'`. **26 survivors, all
documented-equivalent w.r.t. this contract.** Every behavior-changing mutant is killed:
the `if delta:` empty-delta filter (C6), the `stream=True` flag and the `model`/`messages`
forwarding on the streaming call (C7), the `chunk.choices[0]` index, and both
`check_connectivity` verdict flips (`True`/`False`) and the except-branch verdict (C8/C9)
are all killed.

The 26 survivors fall into two documented-equivalent classes:
- **Connectivity-probe request shape (≈20)** — mutating the kwargs the connectivity probe
  sends to the (faked) upstream: `model`/`messages`/`max_tokens`/`stream` set to `None` or
  dropped, the `"ping"` message dict's keys/values case-flipped, `max_tokens=2`,
  `stream=True` on the probe. C8/C9 pin only the *verdict* (`ok`, and `msg` containing the
  model / the error text), deliberately NOT the probe's request shape — asserting the exact
  ping request would couple the test to the connectivity-check mechanism (same stance as the
  log channel). Equivalent w.r.t. this contract.
- **Log channel (≈6)** — `logger.info`/`logger.warning` argument/wording mutations in
  `stream` ("stream started"/"stream done") and the `check_connectivity` except branch. Log
  text is not the oracle (same as in `context`/`storage`/`snapshot`/`workspace`).

LiteLLMProvider's whole-program sweep would also surface these; a focused run plus this
triage is the intended workflow. Re-triage only if the probe's exact request or a log line
ever becomes contractual.
