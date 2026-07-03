# Behavioral contract — `ConversationCore.draft_compression`

Streams an AI-drafted summary of a contiguous, tip-ending node range. It is the
AI-assisted counterpart of the pure `commit_compression`: it produces a *draft* for
human review and commits nothing. Clauses continue the repo numbering scheme
(`commit_compression.md` = C91–C103, `expand_compression.md` ≈ …–C120); this file
starts at **C121**.

Interface under test:

```python
from ctx.core.conversation import ConversationCore, DEFAULT_COMPRESSION_PROMPT

async def draft_compression(
    self, start_id: str, end_id: str, prompt: str | None = None
) -> AsyncIterator[str]: ...
```

`draft_compression(...)` is an async generator: its body (including range validation)
runs on first iteration, so a bad range raises `ValueError` only once iteration begins.

---

C121. **Yields exactly the provider's tokens, in order**
  - Setup: canonical line `[u1, a1, u2, a2]` (tip = a2); provider injected with a known
    token list, e.g. `["Here ", "is ", "the ", "summary."]`.
  - Action: fully consume `draft_compression(u2.id, a2.id)` into a list.
  - Expect: the collected list `==` the provider's canned token list, same order.
  - Rationale: a draft is defined as the streamed provider output for the range; the
    caller must receive precisely those tokens (streaming pass-through, not a rewrite).

C122. **The gauge is never touched — even when the provider reports Usage**
  - Setup: canonical line built; capture `usage_generation`, `calibration`,
    `last_usage`; then inject a provider whose `usage=Usage(prompt_tokens=50,
    completion_tokens=10, total_tokens=60)`.
  - Action: fully consume a draft over `(u2.id, a2.id)`.
  - Expect: all three accessors are unchanged from the captured pre-draft values.
  - Rationale: Q10b — a draft is a meta-operation, never a gauge anchor. It hands the
    provider a no-op `on_usage`, so calibration/generation/last_usage cannot move no
    matter what the provider reports (unlike a real `stream()` turn, which does move them).

C123. **A custom prompt reaches the provider's final user message**
  - Setup: canonical line; recording provider that captures the `messages` it is handed.
  - Action: consume `draft_compression(u2.id, a2.id, prompt="Summarize focusing on the
    migration timeline and blockers.")`.
  - Expect: the exact custom prompt string is the content of some `role=="user"` message
    in the captured messages.
  - Rationale: the user's instruction must drive the model; when supplied it is the
    trailing instruction appended to the rendered range.

C124. **Omitted/None prompt falls back to `DEFAULT_COMPRESSION_PROMPT`**
  - Setup: canonical line; recording provider.
  - Action: consume `draft_compression(u2.id, a2.id)` with no `prompt`.
  - Expect: `DEFAULT_COMPRESSION_PROMPT` is the content of some `role=="user"` message in
    the captured messages.
  - Rationale: the module must guarantee a sensible default instruction so a draft is
    always well-formed even with no user-supplied prompt.

C125. **The range is rendered through build_context (model-facing content)**
  - Setup: canonical line with distinctive user text ("second user message"); recording
    provider.
  - Action: consume `draft_compression(u2.id, a2.id)`.
  - Expect: the verbatim conversation text of the in-range nodes (e.g. "second user
    message") appears in the captured messages; the draft is fed the actual model-facing
    text of the range.
  - Rationale: Q10c — the draft must see what the model sees. The range is rendered via
    `build_context` (raw import -> full file body; summarized node -> its summary; never
    the UI-only "Included:" label). Weaker reliable form of the import-content invariant
    (see ambiguity note below).

C126. **Unknown `start_id` raises before any provider call**
  - Setup: canonical line; recording provider that flags if invoked.
  - Action: iterate `draft_compression("nonexistent-start", a2.id)`.
  - Expect: `ValueError` raised; recording provider was never invoked (captured messages
    stay empty / None).
  - Rationale: range is validated by `_validate_compress_range` before any provider call;
    a nonexistent endpoint is not a resolvable range.

C127. **Unknown `end_id` raises before any provider call**
  - Setup/Action as C126 but `draft_compression(u2.id, "nonexistent-end")`.
  - Expect: `ValueError`; provider never invoked.
  - Rationale: same guard, other endpoint.

C128. **Reversed range (start after end) raises before any provider call**
  - Setup: canonical line; recording provider.
  - Action: iterate `draft_compression(a2.id, u2.id)` (start later than end in the view).
  - Expect: `ValueError`; provider never invoked.
  - Rationale: a range must be a forward, contiguous view slice; a reversed slice is
    invalid and must fail fast, without spending a provider call.

C129. **Non-tip range (3a tip guard) raises before any provider call**
  - Setup: canonical line `[u1, a1, u2, a2]` (tip = a2); recording provider.
  - Action: iterate `draft_compression(u1.id, a1.id)` — a valid contiguous slice that does
    not end at the active leaf.
  - Expect: `ValueError`; provider never invoked.
  - Rationale: the 3a tip guard requires the range to end at the tip; drafting a mid-line
    slice is rejected identically to `commit_compression`.

C130. **Streaming/H2 guard: drafting during a live turn raises**
  - Setup: fresh core built directly with a blocking provider; one submitted user turn;
    begin that turn's `stream(...)` and advance one token so `core.streaming` is True.
  - Action: while the turn is live, iterate `draft_compression(u1.id, a1.id)`.
  - Expect: `ValueError` raised (no draft produced) while streaming is in progress.
  - Rationale: H2 forbids overlapping meta-operations with an in-flight turn.

C131. **A full draft mutates no conversation state**
  - Setup: canonical line; snapshot `current_view()` node ids.
  - Action: fully consume `draft_compression(u2.id, a2.id)`.
  - Expect: `current_view()` node ids after == the snapshot (same ids, same length, same
    order); no compression node was added.
  - Rationale: Q3 — a draft commits nothing; only `commit_compression` alters the graph.

C132. **A cancelled draft leaves the graph exactly as it was**
  - Setup: canonical line; snapshot `current_view()` node ids; provider with several
    tokens.
  - Action: begin the draft, advance one token, then close (cancel) the iterator early.
  - Expect: `current_view()` node ids after == the snapshot.
  - Rationale: Q3 — cancellation-safety; a partial/failed draft cannot leave partial state.

C133. **Flat guard: a range containing a compression node raises before any provider call**
  - Setup: a line in which the range spans an existing `compression`-type node.
  - Action: iterate `draft_compression(start, end)` over that range.
  - Expect: `ValueError`; provider never invoked.
  - Rationale: the flat guard forbids drafting across an existing compression boundary,
    mirroring `commit_compression`. *(Not covered by a test below — see ambiguity note.)*

---

## Intent ambiguities assumed past (flag for human)

1. **Provider streaming method name / call shape.** I could not see the provider Protocol
   or the existing `BlockingProvider`. The recording/blocking providers below assume the
   core invokes a streaming method (aliased to several likely names to be robust) and that
   the messages argument is a `list[dict]` with `"role"`/`"content"` keys — matching the
   intent's own `m["content"]` / `m["role"]` example. If the real Protocol differs, the
   recording-based tests (C123–C125) and the not-called assertions (C126–C129) need the
   method name adjusted. C121/C122 use the real `test_provider` fixture and are unaffected.
2. **C125 strength.** I asserted the weaker "verbatim range content appears" invariant
   rather than the stronger `/include` file-content-vs-"Included:"-label form, because
   setting up a real included file blind is fiddly. The stronger assertion is preferred if
   an included-file fixture can be confirmed.
3. **C133 untested.** Creating a `compression`-type node requires `commit_compression`,
   whose exact signature I cannot verify code-blind, so I left C133 as a documented clause
   without a test rather than risk an implementation-coupled setup.
