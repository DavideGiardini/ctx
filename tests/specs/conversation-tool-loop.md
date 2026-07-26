# Behavioral contract — the tool-calling round loop in `ConversationCore.stream()`

Scope: **only** the round loop added by this change (~90 lines). The rest of
`ConversationCore` — `submit()`, `end_turn()`, persistence, context building,
usage accounting — is covered elsewhere and is deliberately *not* re-specified
here. Items below are the behaviors a realistic regression to *this* change
could break; each maps to one clause of the acceptance criterion (C8 is the one
addition, because "a failing tool call must not blow up the turn" is called out
as load-bearing in the intent and is the only error path the loop owns).

The loop's one *other* guard — the window wall, which refuses a fetched page that
would not fit the model's input window — has its own contract in
`tests/specs/conversation-window-wall.md`.

Domain terms used throughout:

- **round** — one provider request. A turn is one or more rounds.
- **settling** — a round that ends with text and no tool calls; the turn is over.
- **budget** — `search.max_tool_calls` from config (default 12), the maximum
  number of tool calls a single turn may execute.
- **the line** — `core.nodes`, the active conversation line, root-first.

---

C1. A turn with no tool call is an ordinary one-round chat turn
  Given:    search is available (a backend key is in the environment), and a
            provider scripted with a single text round `["The Rhine ", "is 1,230 km long."]`.
            The caller does `user, assistant = core.submit(...)` then drains
            `core.stream(assistant)`.
  Expect:   `stream()` yields exactly `["The Rhine ", "is 1,230 km long."]` in order;
            the line from the user node onward is exactly
            `[("message","user"), ("message","assistant")]` with the assistant node's
            `content == "The Rhine is 1,230 km long."`; exactly **one** provider
            request was made (`len(provider.tools_seen) == 1`); `on_node` is never
            awaited (round 1's assistant node came from `submit()`).
  Rationale:Adding tool calling must be invisible to a turn that doesn't use them.
            Offering tools is allowed here — what must not change is the node shape,
            the token stream, and the request count.

C2. A scripted `search` call appends a search node mid-turn, announces it, and a second round runs
  Given:    search available; a `TestSearch` returning two `SearchHit`s; a provider
            scripted as round 1 = some text + one `ToolCall(name="search",
            arguments='{"query": "..."}')`, round 2 = plain text (settles).
  Expect:   a node with `node_type == "search"` is on the line; its `meta["query"]`
            equals the query the model emitted; its `meta["hits"]` holds the two hits
            the backend returned; its `content` is a non-empty rendered block.
            `on_node` is awaited with that exact node (same `id`) before the turn ends.
            `provider.tools_seen` has length 2 — a second round really ran — and
            `tools_seen[0] == TOOL_SCHEMAS` (both web tools were offered on round 1).
  Rationale:The whole point of the loop: a tool call becomes a durable node on the
            append-only graph, the caller is told about it while the turn is still
            running so it can mount it, and the model gets another turn with the
            result in hand.

C3. Round 1 and round 2 text land in two separate assistant nodes, chronologically, with the tool node between them
  Given:    the same two-round script as C2.
  Expect:   the line from the user node onward reads exactly
            user → assistant → search → assistant, and the two assistant nodes hold
            round 1's text and round 2's text respectively (not concatenated into one
            node, not reordered). The yielded strings are round 1's tokens followed by
            round 2's tokens, and nothing else — no tool output is yielded as text.
  Rationale:The graph is append-only and chronological: a reader scrolling the
            conversation must see what the model said, then what it looked up, then
            what it concluded. And `stream()` yields plain `str` only — tool results
            reach the caller as nodes via `on_node`, never inlined in the token stream.

C4. A round that produces no text creates no assistant node; a `fetch` call becomes a context node
  Given:    search available; a `TestSearch` whose `page` is a fetched document; a
            provider scripted as round 1 = text + `search` call, round 2 = **no
            tokens at all** + a `fetch` call for a URL, round 3 = text (settles).
  Expect:   exactly **two** assistant message nodes exist from the user node onward
            (round 1's, from `submit()`, and round 3's) — the silent round 2 adds no
            empty bubble. The line reads user → assistant → search → context →
            assistant. The fetch node has `node_type == "context"`, `content` equal to
            the fetched page, `meta["source_path"]` equal to the URL the model asked
            for, and `meta["origin"] == "model"`. `on_node` is awaited exactly three
            times: search node, context node, round 3's assistant node, in that order.
  Rationale:Rounds after the first create their node lazily on first token, so a round
            that is nothing but a tool call leaves no trace of itself; an empty
            assistant bubble in the middle of a turn is a visible defect. And a fetched
            page is context the model pulled in, so it is a context node attributed to
            the model, not to the user.

C5. The budget stops the loop, and the final round is sent with no tools
  Given:    search available; `config.json` sets `search.max_tool_calls = 2`; a
            provider scripted so that **every** round ends in another `search` call
            (a model that would search forever).
  Expect:   the turn terminates. Exactly three provider requests are made:
            `tools_seen[0]` and `tools_seen[1]` are non-`None`, and
            `tools_seen[-1] is None` — the last round offers no tools, forcing the
            model to answer from what it has. Exactly **two** search nodes were
            appended: the budget is a hard ceiling on executed calls, not a suggestion.
  Rationale:The loop must always terminate; an unbounded model must not be able to
            burn tokens or hang the UI forever. Withdrawing the tools rather than
            hard-erroring keeps the turn useful.

C6. With no backend key, no tools are offered at all
  Given:    the search backend key is absent from the environment (config isolated,
            provider `tavily`, `TAVILY_API_KEY` deleted); a provider scripted with a
            single text round.
  Expect:   every entry of `provider.tools_seen` is `None`, there is exactly one
            provider request, the yielded tokens are the scripted ones, and the line
            from the user node onward is user → assistant with the full text.
  Rationale:Tools the app cannot actually execute must never be advertised to the
            model — otherwise it calls them and the turn dead-ends. With no key the
            feature is simply absent and behavior matches the pre-feature app.

C7. A consumer that stops mid-loop leaves the appended nodes behind, and only `end_turn` ends the turn
  Given:    a two-round script (round 1 = text + `search` call, round 2 = text); the
            caller consumes tokens until round 2 has started (so the search node is
            already appended), then stops consuming and closes the generator.
  Expect:   the search node is still on the line (nothing is rolled back);
            `core.streaming` is still `True` and the assistant node's `meta` carries
            neither `"interrupted"` nor `"error"` — `stream()` stamped nothing.
            After the caller calls `core.end_turn(assistant, cancelled=True)`,
            `core.streaming` is `False` and `assistant.meta["interrupted"] is True`.
  Rationale:The graph is append-only, so a half-finished turn keeps its nodes; and
            `end_turn` is the single door every ending passes through, so `stream()`
            owning any part of "how a turn ended" would give two sources of truth.

C8. A failing tool call becomes a durable breadcrumb and the turn continues
  Given:    search available; a `TestSearch` configured to raise
            `SearchError("...")`; a provider scripted with round 1 = text + two calls
            — a `search` (which the backend fails) and a `fetch` with malformed JSON
            arguments — and round 2 = text (settles).
  Expect:   nothing propagates out of `stream()`; the generator drains normally and
            yields both rounds' text. Two `node_type == "system"` breadcrumb nodes are
            on the line between the two assistant nodes, each with a non-empty
            explanation, and `on_node` was awaited for both. A second round ran
            (`len(provider.tools_seen) == 2`); no tool call is retried.
  Rationale:A flaky search backend or a malformed argument blob from the model is an
            ordinary event, not a crash: the model is told what went wrong so it can
            adapt in the next round, and the user gets a durable record of why the
            answer has no sources. Retrying silently would double-spend the budget.

---

## Ambiguities I assumed past — please confirm

1. **Import path of the unit under test.** I assumed
   `from ctx.core.conversation import ConversationCore`. If the class lives in a
   different module, only the import line changes.
2. **Tool argument key names.** I assumed the `search` tool takes `{"query": ...}`
   and `fetch` takes `{"url": ...}`, since those are the parameter names in the
   domain API. If `TOOL_SCHEMAS` names them differently, the scripted `arguments`
   strings must match the schemas.
3. **Partial `config.json` merges with defaults.** C5 writes only a `search` block;
   I assumed unspecified keys fall back to defaults rather than the config being
   rejected as incomplete.
4. **Budget semantics = executed tool calls, not rounds.** C5 assumes
   `max_tool_calls = 2` permits two executed calls (spread over two rounds here)
   before tools are withdrawn. If the intent were "two tool-calling *rounds*", the
   arithmetic is the same for this script but would differ for a round that emits
   two calls at once.
5. **Search node `meta["hits"]`.** I assert only its length, not the element type
   (`SearchHit` vs. serialized dict), because the intent doesn't pin the
   serialization.
6. **Not covered on purpose** (out of scope for this change's budget): the
   `on_usage` first-round-only anchor and the single `ctx_hash` stamp. Both are
   stated in the intent but are not clauses of the acceptance criterion and are
   covered by the existing single-round streaming tests; say the word and I'll add
   two more items.
