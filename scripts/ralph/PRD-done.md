# PRD-done — ctx0 Phase 4: built-in web search

Finished tasks, cut verbatim from `scripts/ralph/PRD.md` as each one shipped
(PROMPT.md step 8). The live PRD keeps only a one-line ledger entry per task, so
the loop re-reads a lean worklist; the full body — acceptance criteria and all —
stays here for anyone auditing what a commit was supposed to do.

## Phase 4

- [x] **1 — Search backend seam + litellm `search` adapter** — Create
      `ctx/core/search.py` (framework-free, no `textual`). Define: a frozen
      `SearchHit(title, url, snippet, date)` dataclass; a `SearchError` domain
      exception; a `SearchBackend` Protocol with `async search(query: str) ->
      list[SearchHit]`; `LiteLLMSearch` implementing it over `litellm.asearch`,
      reading `provider`/`max_results` from config and wrapping **every** backend
      exception as `SearchError` (chained via `from exc`, same discipline as
      `ProviderError` in `ctx/core/provider.py`); `TestSearch`, a canned-hits
      double taking a `list[SearchHit]` or an exception to raise; and
      `search_available() -> bool`, true when the configured backend's API key is
      present in the environment. Add a `"search": {"provider": "tavily",
      "max_results": 5, "max_tool_calls": 12}` section to `_DEFAULTS` in
      `ctx/core/config.py` with the same re-merge treatment the other sections get
      in `get_config()`. Ref: ADR-0018 §5, plan §4.3, §4.7.
      _Acceptance:_ `check.sh` green. Unit tests show that a `LiteLLMSearch` whose
      underlying call raises any exception surfaces `SearchError` and that no
      litellm type escapes the module; that `search_available()` flips with the
      env var for the configured provider; that `TestSearch` returns its canned
      hits; and that `get_config()["search"]` merges a partial user override
      without losing the other keys.

- [x] **2 — `fetch(url)` on the search backend** — `uv add trafilatura httpx`
      (never hand-edit `uv.lock`). Add `async fetch(url: str) -> str` to the
      `SearchBackend` Protocol, to `LiteLLMSearch` (httpx GET with a timeout, then
      Trafilatura extraction to markdown, main content only — nav/ads/sidebars
      stripped), and to `TestSearch` (canned page text). litellm has **no**
      page-extraction API, which is why this is ours; do not reach for a
      backend-specific extract endpoint, because fetch must keep working whichever
      search backend is configured (D13). No length cap — the whole extracted page
      is returned (D10); the overflow guard is task 7's job, not this one's. Every
      failure (HTTP error, timeout, unparseable page, empty extraction) raises
      `SearchError`. Ref: plan §4.3, D10, D13. Depends on task 1.
      _Acceptance:_ `check.sh` green. Unit tests show that a fetch whose HTTP layer
      raises surfaces `SearchError` (no `httpx` type escapes), that a page yielding
      no extractable content raises `SearchError` rather than returning `""`, and
      that a successful fetch returns the extracted body. Use a stubbed HTTP
      transport — no test may touch the network.

- [x] **3 — `Node.search` and its model-facing form** — In
      `ctx/models/nodes.py` add a `Node.search(query, results, conversation_id)`
      classmethod: `role` and `node_type` both `"search"`, `content` = the
      rendered results block the model receives, `meta["query"]` = the query and
      `meta["hits"]` = the structured hit list. Add `"search"` to
      `goes_to_model()`. Also add an `origin: str = "user"` parameter to the
      existing `Node.context` factory, stamping `meta["origin"]` only when it is
      `"model"` — a page the model fetched is a context node, and task 10 needs to
      tell it apart from a `/include`d file. In `ctx/core/context.py` add the
      `search` branch to `model_facing_form` (a search node contributes its
      content under the `user` role; empty content contributes nothing) and wrap
      its body in `<search_results query="…">\n…\n</search_results>` in
      `build_context`, alongside the existing `<context_import>` /
      `<conversation_summary>` wrappers. Ref: ADR-0018 §4, plan §4.4.
      _Acceptance:_ `check.sh` green. Contract tests show the factory's shape and
      meta vocabulary; `goes_to_model()` true for a search node; the
      `<search_results>` wrapper appears with the query in its attribute; a search
      node adjacent to user content **merges into the same user message** so the
      role-alternation invariant in `build_context` still holds; an empty search
      node contributes nothing; and `Node.context(origin="model")` stamps
      `meta["origin"]` while the default does not.

- [x] **4 — Provider seam grows function calling** — In `ctx/core/provider.py`
      add a frozen `ToolCall(id, name, arguments)` dataclass (`arguments` is the
      raw JSON string exactly as the model emitted it) and widen the seam to
      `stream(messages, model, on_usage=None, tools=None, on_tool_calls=None)`.
      **`stream` keeps yielding plain `str`** — do NOT widen the element type to a
      union; ADR-0018 §1 records why, and every existing caller must be unaffected
      when `tools` is omitted. `LiteLLMProvider` passes `tools` through to
      `acompletion`, accumulates `chunk.choices[0].delta.tool_calls` deltas
      internally (they arrive index-keyed with `arguments` concatenated across
      chunks), and fires `on_tool_calls([...])` **exactly once** when the response
      ends in tool calls — never when it doesn't. No litellm type crosses the seam.
      `TestProvider` gains scripted per-round behavior so a turn can be driven with
      text and/or tool calls and no network. Ref: ADR-0018 §1, plan §4.2.
      _Acceptance:_ `check.sh` green, including mypy on the widened signature.
      Tests show a scripted `TestProvider` fires `on_tool_calls` once with the
      right `ToolCall`s; a plain text turn never fires it; existing
      `stream(messages, model)` callers behave identically. For `LiteLLMProvider`,
      a test over a stubbed chunk sequence shows argument fragments split across
      chunks are reassembled into one `ToolCall` per index, and that the
      empty-`choices` usage chunk still doesn't crash the loop.

- [x] **5 — Tool dispatch: a `ToolCall` becomes a node** — In
      `ctx/core/search.py` add the tool-protocol surface: `TOOL_SCHEMAS`, the
      OpenAI-format definitions for `search(query)` and `fetch(url)` with
      **neutral** descriptions (plain capability statements — no "you should
      search when…" guidance; D6, and the exact wording is in plan §D6's preview),
      and a dispatch function taking a `ToolCall`, a `SearchBackend` and a
      conversation id, returning `(node, result_text)` where `result_text` is what
      goes back to the model in the `role="tool"` message. A `search` call builds
      a `Node.search`; a `fetch` call builds `Node.context(page, source_path=url,
      origin="model")` — a fetched page is an import whose source is a URL, not a
      new node kind (ADR-0018 §4). **Every failure path returns an error string to
      the model rather than raising** (D8): unknown tool name, malformed or
      missing JSON arguments, and any `SearchError`. No retries. The failed call
      still produces a node so nothing is hidden from the user. Ref: ADR-0018 §4,
      plan D8. Depends on tasks 1–3.
      _Acceptance:_ `check.sh` green. Tests show a `search` call produces a
      `node_type="search"` node plus result text; a `fetch` call produces a
      `node_type="context"` node whose `source_path` is the URL and whose
      `meta["origin"]` is `"model"`; a backend raising `SearchError` yields an
      error string and a node, never an exception; malformed JSON arguments and an
      unknown tool name each yield an error string, never an exception.

- [x] **6 — The tool loop in `ConversationCore.stream()`** — Inject a
      `SearchBackend` into `ConversationCore.__init__` (defaulting to
      `LiteLLMSearch()`, alongside the existing `provider`/`storage`/`workspace`
      seams) and add an optional `on_node` async callback to `stream()` so a
      caller learns about each node the turn appends. Turn `stream()` into the
      round loop: offer `TOOL_SCHEMAS` only when `search_available()`; per round,
      stream text into the current assistant node and, if the round ended in tool
      calls, dispatch each one (task 5), append its node, `await on_node(node)`,
      and go again — up to `search.max_tool_calls` (D7), after which one final
      round runs with `tools=None`. **`stream()` keeps yielding plain `str`.**
      Within the turn the round-trip uses the native protocol (an assistant
      message carrying `tool_calls`, then `role="tool"` messages keyed by
      `tool_call_id`); build the base context **once** from the nodes that existed
      before the turn and append round-trip messages to a **turn-local list**, so
      `build_context`'s role-alternation invariant is never violated by
      re-deriving them from the graph. Historical tool nodes are replayed as text
      by `model_facing_form`, never natively — ADR-0018 §3 records why, and it is
      not optional. Rounds 2+ create their assistant node **lazily on first
      token** (via `Node.assistant` + the existing line-append path) so a silent
      round leaves no empty bubble; `on_node` fires for those too. `ctx_hash` is
      still stamped once, on the first round's context. Ref: ADR-0018 §2–3, plan
      §4.5, D7, D9, D12. Depends on tasks 1–5.
      _Acceptance:_ `check.sh` green. Tests driven with a scripted `TestProvider` +
      `TestSearch` show: a turn with no tool call behaves exactly as before (same
      nodes, same yielded tokens); a scripted `search` call appends a search node
      mid-turn, fires `on_node`, and runs a second round; text from rounds 1 and 2
      lands in **two separate assistant nodes in chronological order** with the
      search node between them; a round that produces no text creates no assistant
      node; the cap stops the loop and the final round is sent with no tools; with
      no search key available no tools are offered at all and the turn is an
      ordinary chat turn; and cancelling mid-loop leaves the already-appended nodes
      in the graph with `end_turn` still the only thing that marks the ending.
