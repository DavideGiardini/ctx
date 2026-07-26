# PRD — ctx0 Phase 4: built-in web search

## Goal
Give the model the ability to reach the web during a turn, with everything it
pulls back landing in the conversation as real nodes — visible in the right pane,
weighted in the gauge, inspectable in the left pane, and compactable like any
other node. Two model-callable tools: `search(query)` returns ranked extracts,
`fetch(url)` returns the full text of one page. The user never invokes them
directly; there is no `/search` command.

Phase 4 is done when a question that needs the web gets a researched answer, the
searches and pages that produced it are visible as nodes with weights, and the
search backend is swappable by editing one config line.

**Design authority — read both before starting any task:**
- `docs/decisions/0018-tool-calling-on-the-provider-seam.md` — the two rules that
  outlive the phase (callback seam; tool history replayed as text).
- `docs/ctx0 Phase 4 Plan — Web search.md` — the full plan: decisions D1–D13 with
  rationale, the design, and the end-to-end qa-tester brief used by task 11.

## Constraints / notes
- **litellm already ships the search abstraction.** `await litellm.asearch(query,
  search_provider=…, max_results=…, api_key=…)` returns a `SearchResponse` whose
  `.results` are objects with `.title/.url/.snippet/.date`, with 14 backends
  bundled (tavily, brave, exa_ai, perplexity, duckduckgo, searxng, …), each
  resolving its own env key. **Do NOT write per-backend adapters of our own** —
  that would be a shallow module wrapping a wrapper (ADR-0018 §5). Verified
  present in the pinned litellm 1.87.1.
- **Do NOT gate on `litellm.supports_function_calling()`.** It returns `False` for
  the default OpenRouter Gemma slug because the bundled cost map is stale, while
  the model does support tool calling. Offer the tools; let the provider reject.
- **`end_turn` stays the single owner of how a turn ends** (ctx0 Phase 1). The
  tool loop lives *inside* `ConversationCore.stream()`; it must never stamp
  `interrupted`/`error` itself, never touch the `streaming` flag, and never
  persist. Every ending still converges in `on_worker_state_changed`.
- **The graph is append-only** (ADR-0016). A turn now appends several nodes; none
  of them may be mutated or deleted. In particular you cannot remove a node from
  the *middle* of the line — see task 9's zero-content rule for the consequence.
- **Reuse, don't reinvent:** `Node` factory classmethods are the single source of
  truth for each kind's shape (ADR-0014); `model_facing_form` in
  `ctx/core/context.py` is the single definition of what a node looks like to the
  model; `tokens.weight_pct`/`count_messages` already work over `build_context`
  output, so a new model-facing node kind gets weights for free.
- **Core stays framework-free.** `ctx/core/search.py` imports no `textual`. `ctx`
  must never import from `tools/`.
- **Task 6 is the largest.** Tasks 1–5 exist to make it fit one session; if it
  still doesn't, do the loop without the round cap, commit, and leave the cap as a
  new task rather than half-finishing.
- Tasks 1–7 are pure core with no UI surface: per PROMPT.md step 7 they need **no
  `qa-tester` and no rendering** — the authored tests plus a green gate are the
  verification. Tasks 9–11 are the ones that drive the app.

## Tasks

*(none — every task in this PRD is complete. One item is owed by the **human**,
not this loop: the manual live smoke of plan §5.3 against a real provider with a
real `TAVILY_API_KEY`. The harness proves the machinery; it cannot prove a real
model calls these schemas.)*

## Completed

Full bodies live in `scripts/ralph/PRD-done.md`; task numbers are preserved so
`deps:` / "task-N" references still resolve.

- [x] 1 — Search backend seam + litellm `search` adapter
- [x] 2 — `fetch(url)` on the search backend
- [x] 3 — `Node.search` and its model-facing form
- [x] 4 — Provider seam grows function calling
- [x] 5 — Tool dispatch: a `ToolCall` becomes a node
- [x] 6 — The tool loop in `ConversationCore.stream()`
- [x] 7 — The window-wall guard and its breadcrumb
- [x] 8 — Harness and test doubles for a driveable tool turn
- [x] 9 — Mount tool nodes mid-turn in the UI
- [x] 10 — Render the search node in the high-ground view
- [x] 11 — End-to-end verification of the phase

<!-- As tasks complete, the loop PRUNES them (PROMPT.md step 8): the finished
task's full body is cut from here and moved to `PRD-done.md`, leaving a one-line
entry under a "## Completed" ledger below. This keeps the live PRD lean because the
loop re-reads the whole file every iteration. -->

## Out of scope
- **A `/search` command or any user-invoked search** (D1). Search is model-called
  only; adding a fifth verb is not this phase.
- **Citation behavior and the system prompt** (D5). Phase 5 owns "one system
  prompt actually reaching the LLM"; Phase 4 ships neutral tool descriptions and
  no citation instruction.
- **Announcing that search is unavailable.** With no backend key the tools are
  simply never offered (D4); discoverability belongs to Phase 5's README and
  install story. Do not add a startup breadcrumb.
- **Any tool beyond `search` and `fetch`** — no tool registry, no MCP, no plugin
  system, no `/`-invocation framework (concept §8).
- **Per-backend adapters of our own** — litellm is the abstraction (ADR-0018 §5).
- **Truncating fetched pages** (D10) and **auto-compacting to make room** (D11).
- **Solving `model_window() is None`** for models litellm has no metadata for; the
  guard is skipped there by design (task 7).
- **An approval gate before results reach the model** (D3), and **retrying a
  failed tool call** (D8).
- Changing the append-only graph, the compression event model (K/E), `end_turn`'s
  ownership of turn endings, or the detail inspector's 3-split shape.
