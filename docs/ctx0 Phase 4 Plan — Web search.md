# ctx0 Phase 4 — Built-in web search

Planning session: 2026-07-26. Design settled; not yet decomposed into tasks.
Roadmap: `docs/ctx0 Roadmap.md` §5 Phase 4. Concept: `docs/ctx0_Product_Concept.md`
§4.4, §7.

## 1. Goal

The model can reach the web on its own during a turn, and everything it pulls
back becomes a real node in the high-ground view — visible in the right pane,
weighted in the gauge, inspectable in the left pane, and compactable like any
other node. Two tools, not one: `search(query)` returns ranked extracts,
`fetch(url)` returns the full text of a single page.

Phase 4 is done when a question that needs the web gets a researched answer, the
searches and pages that produced it are visible as nodes with weights, and the
search backend is swappable by editing one config line.

## 2. Research notes

Checked against the live web and against the installed package on 2026-07-26,
because two of these had moved since the training cutoff.

**litellm already ships the search abstraction the concept asks for.** §7 of the
concept specifies "one internal abstraction — `search(query) -> results` — with
two or three concrete backends behind it, selected by a single config line plus
an API key." The pinned litellm (1.87.1, verified by introspection, not just
docs) exposes `await litellm.asearch(query, search_provider=..., max_results=...,
search_domain_filter=..., country=..., api_key=...)` returning a normalized
`SearchResponse` whose `results` are `SearchResult(title, url, snippet, date,
last_updated)`. Fourteen backends are bundled — Tavily, Brave, Exa, Perplexity,
DuckDuckGo, SearXNG, Serper, Firecrawl, Google PSE, Parallel, DataForSEO, Linkup,
You.com, SearchAPI — each resolving its own key from the environment
(`TAVILY_API_KEY`, etc.) exactly the way the LLM key already resolves. **We adopt
this abstraction rather than build one.** That removes the entire "swappable
backend" half of the phase and is why the L estimate should come down.
Sources: [litellm search docs](https://docs.litellm.ai/docs/search/), local
introspection of `litellm/llms/{tavily,brave,exa_ai,duckduckgo,searxng}/search/`.

**litellm has no page-extraction API.** Its web-search *interception* feature
(`web_search_options`, provider-native `web_search` tools) is a proxy-server
feature and returns results the app never sees as data — unusable here, since
the whole point is that results become nodes. So `fetch(url)` is ours to build.
Sources: [litellm web search](https://docs.litellm.ai/docs/completion/web_search),
[websearch interception](https://docs.litellm.ai/docs/integrations/websearch_interception).

**Snippet-only search is measurably weaker than full-page reading.** 2026
benchmarks consistently show full-page context winning on questions where the
answer is buried in one document, and the emerging practice is not "always fetch"
but "let the model decide when the extract is not enough" — which is a second
tool, not a bigger first one. This is what motivated the two-tool shape.
Sources: [Firecrawl, best web search APIs 2026](https://www.firecrawl.dev/blog/best-web-search-apis),
[Firecrawl, agentic search](https://www.firecrawl.dev/blog/agentic-search).

**Trafilatura is still the extraction quality leader.** Mean F1 ≈ 0.937 with
native markdown output, strips nav/ads/sidebars; readability-lxml is more
predictable but emits cleaned HTML only, and newspaper4k is news-specific.
Sources: [Trafilatura vs Readability vs Newspaper4k](https://www.contextractor.com/trafilatura-vs-readability-vs-newspaper/),
[Trafilatura evaluation](https://trafilatura.readthedocs.io/en/latest/evaluation.html).

**The default model does support function calling.** Gemma 4 26B A4B has native
function calling, configurable thinking, and structured output. Note that
`litellm.supports_function_calling()` returns `False` for it — the bundled cost
map is stale for OpenRouter slugs, so **do not gate the feature on that helper**;
offer the tools and let the provider reject if it must.
Source: [OpenRouter model page](https://openrouter.ai/google/gemma-4-26b-a4b-it).

**Backend economics, for the config default.** Tavily free tier 1,000
searches/month, then ~$0.008/search; Exa 1,000 free credits with a much larger
request allowance; Brave removed its free plan in Feb 2026 (now $5 starter
credit), $5–9 per 1,000. Tavily is the common default for agent retrieval because
it returns LLM-shaped extracts rather than raw SERP metadata.
Sources: [Tavily pricing](https://coldiq.com/blog/tavily-pricing),
[Brave, best search APIs 2026](https://brave.com/learn/best-search-api-2026/).

## 3. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **Model-invoked only.** No `/search` command. | Matches concept §4.4 exactly and adds no fifth verb to ctx0's surface. |
| D2 | **Two tools: `search(query)` and `fetch(url)`.** | Snippet-only search underperforms on deep questions; letting the model escalate to a full page is the 2026 practice. Each produces its own node. |
| D3 | **No approval gate.** Results flow straight back and the turn keeps streaming. | Control is exercised *after* the fact — every result is a visible, weighted, compactable node. Gating would split a streaming turn in half for little gain. |
| D4 | **Search is off until a backend key is present.** Default backend `tavily`. | With no key the tools are never offered to the model, so it can never promise a search it cannot run. No key management inside ctx (concept §8). |
| D5 | **No citation instruction in Phase 4.** | Deferred to Phase 5, which owns the system prompt. URLs are visible in the result nodes regardless. **This changes the roadmap's Phase 4 done-criterion** — see §7. |
| D6 | **Neutral tool descriptions.** Plain capability statements, no "you should search when…" guidance. | Keeps the model's own judgment unbiased; revisit in Phase 5 if the model under-calls in practice. |
| D7 | **Cap of 12 tool calls per turn.** | Room for genuine multi-step research. On exhaustion the model is told no more tools are available and must answer from what it has. |
| D8 | **A failing tool returns an error string to the model; the turn continues.** No retry. | A transient blip still produces an answer. The failed call is recorded as a visible node, so nothing is hidden. |
| D9 | **Interleaved, chronological nodes.** Each burst of model text is its own assistant node, sitting in time order between the tool nodes. | Reads as it happened; each piece is separately selectable and compactable. Silent rounds produce no bubble. |
| D10 | **Fetched pages are uncapped** — the whole extracted page reaches the model. | Maximum fidelity; the gauge and compaction are the user's lever, not a hidden truncation. |
| D11 | **A fetch that would overflow the model's context window is refused**, returning an explanation to the model *and* dropping a durable system breadcrumb for the user. | The one place D10 can hard-fail a turn. Refusing one fetch is the same class of event as a failed search (D8), so the turn still answers — and the user is told why the answer is thin. |
| D12 | **Ctrl+C mid-loop keeps completed nodes**, drops only the in-flight call. | Consistent with the append-only graph and with Phase 1's cancel semantics. |
| D13 | **`fetch` builds a page with Trafilatura, not a backend extract endpoint.** | Works regardless of which search backend is configured, needs no second key, and keeps D4's swappability promise honest. |

## 4. Design

### 4.1 Where things live

- `ctx/core/search.py` — **new**, framework-free. The web-reaching deep module.
- `ctx/core/provider.py` — the seam grows function calling.
- `ctx/core/conversation.py` — owns the tool loop inside `stream()`.
- `ctx/core/context.py` — one new `model_facing_form` branch.
- `ctx/models/nodes.py` — one new `Node.search` factory.
- `ctx/core/config.py` — a `search` section, a `search` color, a truncation key.
- `ctx/ui/` — mount tool nodes mid-turn; render the new node kind.
- New runtime deps: `trafilatura`, `httpx` (already transitive; declare it).

### 4.2 The provider seam — the shape change

This is the first change to the seam since ADR-0015, and that ADR anticipated it:
*"if a future need arises for multiple mid-stream signals (e.g. tool-call events),
revisit."* Having looked, the callback shape still wins, for a reason specific to
tool calls: **a tool-call batch is complete at the end of a response**
(`finish_reason == "tool_calls"`), so like `Usage` it is an at-most-once
out-of-band value, not a genuine mid-stream event stream.

```
Provider.stream(messages, model, on_usage=None,
                tools=None, on_tool_calls=None) -> AsyncIterator[str]
```

`LiteLLMProvider` accumulates `chunk.choices[0].delta.tool_calls` deltas by index
internally and fires `on_tool_calls([ToolCall(id, name, arguments)])` exactly once
if the response ended in tool calls. **The yielded type stays `str`** — the UI's
`async for token` path is untouched, and no consumer pays a union tax. A new
frozen `ToolCall` dataclass is the domain type; litellm's chunk objects never
cross the seam, same discipline as `Usage`.

`TestProvider` gains scripted per-round behavior (text tokens and/or tool calls)
so the whole loop is exercisable with no network.

### 4.3 The search seam

`ctx/core/search.py` defines a `SearchBackend` Protocol with two methods —
`search(query) -> list[SearchHit]` and `fetch(url) -> FetchedPage` — plus
`LiteLLMSearch` (the real adapter: `litellm.asearch` + httpx/Trafilatura) and
`TestSearch` (canned hits, no network). Two real implementations, so the seam
earns its keep by the repo's own rule; it is injected into `ConversationCore`
exactly like `Provider` and `Workspace` are.

Deliberately **not** built: any per-backend abstraction of our own. litellm *is*
the backend abstraction; a `TavilyBackend`/`BraveBackend` layer on top of it would
be a shallow module wrapping a wrapper. Swapping backends is one config line.

The module also owns `TOOL_SCHEMAS` (the OpenAI-format tool definitions with the
neutral D6 descriptions) and `search_available()`, which reports whether the
configured backend's key is in the environment.

### 4.4 Node kinds — one new, one reused

**`search` is a new node type.** A query plus a ranked hit list is a genuinely
new shape in the graph, and the high-ground view needs to distinguish a search
from a file import at a glance. `Node.search(query, results, conversation_id)`
joins the factory family (ADR-0014): `role`/`node_type` both `"search"`,
`content` = the rendered results block the model receives, `meta["query"]` and
`meta["hits"]` = the structured results. It is added to `goes_to_model()`, gets a
`colors.search` entry and a 2-line truncation key, and its model-facing form is
`<search_results query="…">…</search_results>`. In the 3-split inspector the
query lands in the Prompt split and the results in the Source split, so the
existing context-node inspector shape is reused unchanged.

**`fetch` reuses the existing `context` node.** A fetched page is literally an
import whose source happens to be a URL rather than a file: same shape, same
content-on-node storage, same `<context_import source="…">` wrapper, same green
role bar, same inspector, same weight accounting. `Node.context(page_markdown,
source_path=url, conversation_id)` — zero new node type, zero new rendering. The
asymmetry with `search` is principled, not lazy: a page *is* an import; a result
set is not.

### 4.5 The tool loop, and why history is replayed as text

`ConversationCore.stream()` becomes the loop owner (it already owns node creation
and the `ctx_hash` stamp). Per round: build the request, stream text into the
current assistant node, and if the round ended in tool calls, execute them, append
their nodes, and go again — up to D7's cap, after which one final round runs with
`tools=None`.

**Within the live turn**, the round-trip uses the native protocol: an assistant
message carrying `tool_calls`, followed by `role="tool"` result messages.
Strict-alternation providers (the Anthropic family) *require* every `tool_use` id
to be answered by a matching `tool_result`, so there is no choice here. To keep
`build_context`'s role-alternation invariant intact, the loop builds the base
context once from the nodes that existed *before* the turn, and appends the
round-trip messages to a turn-local list rather than re-deriving them from the
graph.

**On every subsequent turn**, those same nodes are replayed as ordinary
XML-wrapped user content via `model_facing_form` — never as native tool messages.
That is a deliberate choice, and the deciding argument is compaction: if history
were replayed natively, compacting a search node would leave an assistant
`tool_call` with no matching `tool_result` and the next request would be rejected
outright. Rendering history as text keeps every tool node exactly as
foldable, expandable and editable as an import. It is also the more ctx-shaped
answer — a search result is context you control, not an opaque protocol artifact.

**Node mounting mid-turn.** `stream()` takes an `on_node` async callback (the same
out-of-band shape as `on_usage`) that the UI supplies to mount each newly appended
node and refresh weights as the turn progresses. `stream()` keeps yielding `str`.

**The empty-first-round case** is the one lifecycle subtlety worth flagging for
implementation. `submit()` creates the round-1 assistant node up front, but a turn
that opens with a silent tool call leaves it empty, and the append-only graph
cannot remove a node from the middle of the line. Resolution: rounds 2+ create
their assistant node lazily on first token, and the view drops zero-content
assistant nodes that are not the live streaming target — a generalization of the
phantom-row rule task 48 already established for zero-token cancels. This
requires routing `_refresh_token_ui` through `_visible_nodes()` so weights and
`describe_state` indices cannot desync.

### 4.6 The window wall (D11)

Before a fetched page is handed back, the loop estimates the resulting request
against `tokens.model_window(model)`. Over the line: the tool returns "this page
is too large for the remaining context window", and `add_system_message` records a
durable breadcrumb so the user can see why the answer came up short. Honest
limitation to note: `model_window()` returns `None` for models litellm has no
metadata for — **including the current default Gemma** — and the guard is
necessarily skipped there, so those turns fall back to the provider's own error
via Phase 1's `end_turn(error=…)`. That gap is the north-star parking-lot item
"header gauge for models with no window metadata" and is not solved here.

### 4.7 Config

```json
"search": { "provider": "tavily", "max_results": 5, "max_tool_calls": 12 }
```

Keys come from the environment per backend, like the LLM key. Accepted gap: with
no key, search is silently absent rather than announced — discoverability belongs
to Phase 5's README and install story.

## 5. Test plan

### 5.1 Deterministic gate — `bash scripts/check.sh`

ruff + mypy green; no weakening of the gate. Code-blind contract tests via
`/write-tests` for the framework-free core:

- **`ctx/core/search.py`** — the pure surface: results-to-text rendering, tool
  schema shape, `search_available()` against a given config + environment, and
  the mapping of every backend failure onto the domain `SearchError` (no litellm
  or httpx type escapes the module).
- **`ctx/models/nodes.py`** — the `Node.search` factory's shape and meta
  vocabulary; `goes_to_model()` true for `search`.
- **`ctx/core/context.py`** — the `<search_results query="…">` wrapper; a search
  node coalescing into an adjacent user run without breaking the
  role-alternation invariant; an empty search node contributing nothing.
- **`ctx/core/conversation.py`** — the loop, driven by `TestProvider` +
  `TestSearch`: one round with no tool call behaves exactly as today; a scripted
  tool call appends a search node and runs a second round; the D7 cap stops the
  loop and the final round carries no tools; a raising `TestSearch` yields an
  error string to the model and a node, not an exception; a fetch over the window
  is refused and breadcrumbed; cancellation mid-loop leaves completed nodes and
  no partial one; `end_turn` remains the single owner of every ending.

Pilot-driven pytest for the UI layer: tool nodes mount mid-turn (not only at turn
end), interleaved assistant bubbles appear in chronological order, weights refresh
after each appended node, and a zero-content round-1 assistant node never renders.
Spacing/layout invariants stay in unit tests, never in qa-tester.

### 5.2 Behavioral QA — the `qa-tester` brief

Hand the subagent this verbatim.

> **Mode:** verify-feature.
>
> **Setup:** launch `tools.agent.harness:HarnessApp`. The harness is wired with a
> `TestProvider` that scripts tool-call turns and a `TestSearch` returning canned
> hits — no network. Trigger words in a submitted message drive the script:
> `SEARCH` → round 1 emits "Let me look that up. " plus a `search` tool call, round
> 2 emits the canned answer. `FETCH` → round 1 emits a `search` call, round 2 a
> `fetch` call on the first hit's URL, round 3 the answer. `SEARCHFAIL` → the
> search tool raises. `SEARCHLOOP` → the model requests a search on every round,
> forever.
>
> **Steps and expected results** — each is drive X → expect `ctx_snapshot` Y:
>
> 1. Type `SEARCH what is ctx0` and submit. While streaming, expect `streaming=yes`.
>    After it settles: `streaming=no`, and `nodes` contains, in order, a `user`
>    node, an `assistant` node whose content is "Let me look that up.", a node with
>    `node_type="search"` whose content includes the canned hit titles and URLs,
>    and a second `assistant` node with the canned answer. Chronological order is
>    the assertion — a search node appearing after both assistant nodes is a fail.
> 2. On that same snapshot, every node has a non-null `weight_pct`, and the search
>    node's is non-zero. `context_gauge.pct` is not null.
> 3. Press `Escape` to enter edit mode, navigate with `Up` to the search node.
>    Expect `selected_role="search"` and `detail.node_role="search"`, with
>    `detail.splits_visible` containing the prompt and content splits — the query
>    in one, the results in the other.
> 4. With the search node selected, press `c`, then `Ctrl+S` after typing a
>    summary. Expect `compression_editor.open=true` at the first checkpoint, then
>    after commit a node with `node_type="compression"` where the search node was,
>    and the search node gone from `nodes`. This proves tool output is compactable
>    like any other node.
> 5. Press `x` on that compression node. Expect the search node restored in place.
> 6. Type `FETCH the ctx docs` and submit. Expect the settled `nodes` to contain a
>    `search` node followed by a `node_type="context"` node whose `source_path` is
>    an `http`/`https` URL, followed by an `assistant` node.
> 7. Type `SEARCHFAIL anything` and submit. Expect `streaming=no`, a node
>    recording the failed search, and a final `assistant` node with content — the
>    turn must still produce an answer. No `error` mark on the assistant node.
> 8. Type `SEARCHLOOP forever` and submit. Expect the turn to terminate on its own
>    with `streaming=no` and at most 12 `search` nodes in `nodes`.
> 9. Type `SEARCH something slow` and submit, then press `Ctrl+C` while
>    `streaming=yes`. Expect `streaming=no`, any already-completed search node
>    still present in `nodes`, and the app still running (Ctrl+C must cancel the
>    turn, never quit).
> 10. Type a plain message with no trigger word and submit. Expect exactly the
>     pre-Phase-4 behavior: one user node, one assistant node, no search node.
>
> **Negative / edge probes:** submit a second message while a research turn is
> streaming — expect a refusal hint, the typed text preserved in `input`, and no
> new user node. Run `/new` mid-research-turn and confirm the node list clears
> with no stuck `streaming=yes`. Run `/resume` on a conversation containing search
> nodes and confirm they come back with the right `node_type` and weights. After
> every step, `textual_check_errors` reports no crashes and no worker errors.
>
> **Pass condition:** all ten steps match, both negative probes behave, and
> `textual_check_errors` is clean throughout. Report any step where node ordering,
> node type, or `streaming` differs from the expectation, with the snapshot excerpt.

### 5.3 Live smoke (manual, once)

The harness proves the machinery; it cannot prove the tool schemas are accepted
by a real provider or that Gemma actually calls them. One manual run against
OpenRouter with a real `TAVILY_API_KEY`, asking something genuinely post-cutoff,
before the phase is called done.

## 6. Out of scope

- A `/search` command or any user-invoked search (D1).
- Citation behavior and the system prompt — Phase 5.
- Any tool beyond `search` and `fetch`; no tool registry, no MCP, no plugin
  system (concept §8).
- Our own per-backend adapters — litellm is the abstraction (§4.3).
- Search over the conversation history or the KB — north-star RAG, deferred.
- Solving `model_window() is None` for metadata-less models (§4.6).

## 7. Doc-sync items

Two places where these decisions diverge from what is written down, both needing
the user's call before editing:

1. **Roadmap Phase 4 done-criterion** says "a searched, **cited** answer".
   D5 defers citation to Phase 5. Proposed: drop "cited" from Phase 4 and add
   "the system prompt instructs citation" to Phase 5's criteria.
2. **Concept §4.4 and §8** describe search as a single built-in tool
   (`search(query)`, "one built-in, backend-swappable search"). D2 makes it two
   tools. Proposed: reword §4.4 to describe one verb — reach the web — with a
   search step and a read step, and update §8's cut-list line to "two built-in,
   backend-swappable web tools".
