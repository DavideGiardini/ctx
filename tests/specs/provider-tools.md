# Provider seam: tool calls

The seam under test is `Provider.stream` in `ctx/core/provider.py` — the single place
where the app talks to an LLM backend. This change widens it so a *tool request* can
cross it: the model may end a response by asking to call `search(query)` or
`fetch(url)`, and the caller one layer up dispatches those. That dispatch loop is out
of scope here; only the crossing is specified below.

Two shapes govern everything in this file:

- The token stream stays `str`. A tool-call batch is only complete when the response
  ends, so tool calls are never interleaved mid-stream events — they arrive out-of-band
  through `on_tool_calls`, exactly as exact token counts already arrive through
  `on_usage`.
- No backend type crosses the seam. litellm reports tool calls as a stream of partial
  fragments keyed by `.index`, with `.id`/`.function.name` present only on the fragment
  that opens a call and `.function.arguments` split arbitrarily across chunks. The
  adapter reassembles those into complete, frozen `ToolCall` domain objects before
  anything upstream sees them.

Test seams: the real adapter is isolated by monkeypatching
`ctx.core.provider.acompletion` with an async callable that returns an async iterator of
fake chunk objects (`types.SimpleNamespace`), so no test touches the network. The second
real implementation of the seam, `TestProvider`, is exercised directly — it ships in the
product package and is what the app's own harness injects, so its scripted-replay
behavior is product behavior, not scaffolding.

Scoped deliberately: this is a ~60-line widening of an existing module, so the contract
covers only the new tool-calling surface. Pre-existing plain-text streaming, `on_usage`
semantics in isolation, and `ProviderError` wrapping already have their own suite and are
not re-specified here.

---

**T1. A scripted tool round reports its calls exactly once, out-of-band.**
Given a `TestProvider` scripted with one `ScriptedRound` whose `tokens` are ordinary
prose and whose `tool_calls` is a single `ToolCall` for `search`, streamed with an
`on_tool_calls` callback. Expect the stream to yield exactly the round's tokens, each a
plain `str` and nothing else — the tool call never appears in the token sequence — and
`on_tool_calls` to be invoked exactly once, after the tokens, with a list equal to the
round's `tool_calls` (same `id`, `name`, and raw `arguments` string, unparsed).

**T2. A plain text turn never reports tool calls.**
Given a `TestProvider` in its plain single-round form (`TestProvider(tokens=[...])`), and
separately a `TestProvider` scripted with a round whose `tool_calls` is empty, both
streamed with an `on_tool_calls` callback supplied. Expect the yielded tokens to be
exactly the scripted tokens and `on_tool_calls` to never be invoked — not even with an
empty list. A turn that settles in text must be indistinguishable, from the caller's
side, from the world before tool calling existed.

**T3. The new parameters are inert when omitted.**
Given callers written against the old signature that call `stream(messages, model)` with
no `tools` and no `on_tool_calls`. Expect, for a `TestProvider` whose script *does* end
in a tool call, that the stream still yields the round's tokens and completes without
raising — a missing callback is silently accepted, never an error. Expect, for
`LiteLLMProvider`, that the request forwarded to the backend offers no tools at all
(`tools` absent, or `None`) rather than an empty list, since an empty tool list is not
the same request as no tool list, and that the yielded tokens are the response text
unchanged.

**T4. The adapter reassembles fragments into one `ToolCall` per index.**
Given a stubbed litellm chunk sequence for a response that emits some text and then asks
for two calls: a role-only chunk carrying neither text nor tool calls; a text chunk; then
tool-call fragments in which one call's `arguments` are split across three chunks, the
opening fragment of a call carries *no* `id`/`name` (they arrive on a later fragment for
the same `.index`), fragments for the two indexes are interleaved, and the final chunk
has an **empty** `choices` list carrying only `.usage`. Expect: the stream yields exactly
the text chunk's content as `str` (chunks with `content is None` contribute nothing);
`on_tool_calls` is invoked exactly once with two `ToolCall`s, one per `.index`, ordered
by index, each carrying the `id` and `name` from whichever fragment supplied them and
`arguments` equal to the full concatenation of its fragments in arrival order, with no
JSON parsing or validation applied; `on_usage` is invoked exactly once with the `Usage`
from the final chunk; and the empty-`choices` chunk does not raise — indexing
`choices[0]` unconditionally is the known trap, and a crash there would break every turn,
tools or not.

**T5. The adapter does not report tool calls for a text-only response.**
Given a stubbed chunk sequence with text chunks, a role-only chunk, a final
empty-`choices` usage chunk, and no `tool_calls` anywhere, streamed with an
`on_tool_calls` callback supplied. Expect the callback to never be invoked. Firing it
with an empty list at end-of-response is the plausible regression, and it would make the
caller's dispatch loop treat every ordinary reply as a tool turn.

**T6. Consecutive streams replay consecutive rounds, and the last round repeats.**
Given a `TestProvider` scripted with two rounds — round 1 is prose plus a `search` tool
call, round 2 is the plain-text answer — driven as the dispatch loop would drive it:
first `stream` with the search tool offered, second `stream` with `tools=None` because
tools are withheld on the final round. Expect the first stream to yield round 1's tokens
and report round 1's tool calls once; the second stream to yield round 2's tokens and
report nothing further; a third `stream` past the end of the script to yield round 2's
tokens again and still report nothing, since the last round repeats rather than raising
or going silent; and `tools_seen` to record the `tools` argument of each call in order
(`[[search_tool], None, None]`), so the caller's offer/withhold decisions are observable
without reaching inside the provider.

---

## Assumptions / ambiguities flagged

- **Ordering of simultaneous calls.** The docstring says calls arrive "in the order the
  provider indexed them." For real backends, first-appearance order and index order
  coincide, so T4 emits index 0's opening fragment before index 1's; that keeps the test
  honest for both an index-sorted and an arrival-ordered implementation. If reversed
  arrival (index 1 opening first) must sort back to index order, say so and the test can
  be tightened — as written it does not pin that case.
- **Callback timing relative to the stream.** Intent says "when the response ends," so
  T1/T4 assert `on_tool_calls` has fired by the time the stream is exhausted, and T1
  additionally asserts it had not fired before the last token. Whether it fires on the
  final `__anext__` or after `StopAsyncIteration` is treated as an implementation detail.
- **`tools_seen` when `tools` is omitted entirely.** T6 assumes an omitted `tools`
  argument is recorded as `None` (the parameter default) rather than skipped, since the
  point of the list is a per-call record aligned with the rounds.
- **Empty-`choices` chunks mid-stream.** Only the documented *final* usage chunk is
  covered; whether a mid-stream empty-`choices` chunk is possible is a backend question
  left open.
