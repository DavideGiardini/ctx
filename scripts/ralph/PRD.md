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

- [ ] **4 — Provider seam grows function calling** — In `ctx/core/provider.py`
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

- [ ] **5 — Tool dispatch: a `ToolCall` becomes a node** — In
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

- [ ] **6 — The tool loop in `ConversationCore.stream()`** — Inject a
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

- [ ] **7 — The window-wall guard and its breadcrumb** — Before a fetched page is
      handed back to the model, estimate the resulting request with
      `tokens.count_messages` against `tokens.model_window(self.model)`. If it
      would overflow, the tool returns "this page is too large for the remaining
      context window" instead of the page (the same shape as a failed tool, D8)
      **and** a durable system breadcrumb is recorded via `add_system_message` so
      the user can see why the answer came up short (D11). Pages are otherwise
      uncapped — do **not** truncate (D10). Honest limitation to preserve, not
      fix: `model_window()` returns `None` for models litellm has no metadata for,
      including the current default Gemma; when the window is unknown the guard is
      skipped and the turn falls back to the provider's own error via
      `end_turn(error=…)`. Ref: plan §4.6, D10, D11. Depends on task 6.
      _Acceptance:_ `check.sh` green. Tests show that with a known small window a
      fetch that would overflow returns the refusal string, appends the durable
      system breadcrumb, and lets the turn continue to an answer; that the page is
      never truncated on the success path; and that with `model_window()` returning
      `None` the guard is skipped and the fetch proceeds.

- [ ] **8 — Harness and test doubles for a driveable tool turn** — Extend
      `tools/agent/harness.py` so `HarnessApp` wires a `TestSearch` alongside its
      `TestProvider`, and give `ChatApp.__init__` a `search=` injection parameter
      mirroring `provider=`/`workspace=`/`storage=`. Script the harness provider by
      **trigger word in the submitted message**, so qa-tester steps are
      deterministic: `SEARCH` → round 1 emits `"Let me look that up. "` plus a
      `search` tool call, round 2 emits the canned answer; `FETCH` → round 1 a
      `search` call, round 2 a `fetch` call on the first hit's URL, round 3 the
      answer; `SEARCHFAIL` → the search tool raises `SearchError`; `SEARCHLOOP` →
      the model requests a search every round, forever. A message with no trigger
      word behaves exactly as today. Add the matching doubles/fixtures to
      `tests/conftest.py` next to the existing `app_factory`, `test_provider` and
      `BlockingProvider`. Nothing here ships: `tools/` stays outside the `ctx`
      package (ADR-0012). Ref: plan §5.2. Depends on tasks 4 and 6.
      _Acceptance:_ `check.sh` green. A Pilot test drives `SEARCH …` through the
      app factory and asserts the resulting node sequence is user → assistant →
      search → assistant. No test and no harness run touches the network.

- [ ] **9 — Mount tool nodes mid-turn in the UI** — In `ctx/ui/app.py` pass an
      `on_node` callback from `_stream_response` into `core.stream()` that mounts
      each appended node with `_mount_node`, refreshes the token UI, and — when the
      new node is an assistant node — retargets the live-stream pointers
      (`_streaming_node`, `_stream_to_inspector`) at it, so text from rounds 2+
      streams into the right row and, in Insert mode, into the locked inspector.
      Then fix the invalidated one-node-per-turn assumptions: route
      `_refresh_token_ui`'s node iteration through `_visible_nodes()` (today it
      reads `self.core.nodes` directly, and `zip(..., strict=True)` will blow up
      the moment the two disagree), and make `_visible_nodes()` drop **zero-content
      assistant nodes that are not the live streaming target** — a turn opening
      with a silent tool call leaves the `submit()`-created assistant node empty,
      and the append-only graph cannot remove a node from the middle of the line
      (ADR-0018 Consequences). This generalizes the phantom-row rule task 48
      established for zero-token cancels; it is a **view** rule, so no graph
      mutation. `describe_state` reads `_visible_nodes()` already, so its indices
      and the weights stay in agreement. Ref: plan §4.5. Depends on tasks 6 and 8.
      _Acceptance:_ qa-tester (verify-feature) on `tools.agent.harness:HarnessApp`:
      submitting `SEARCH what is ctx0` shows the search node in the snapshot's
      `nodes` **while `streaming=yes`**, not only after the turn settles; the
      settled snapshot shows user → assistant → `node_type="search"` → assistant in
      that order; every node carries a non-null `weight_pct` and the search node's
      is non-zero; no empty assistant node appears; `textual_check_errors` reports
      no crashes or worker errors. `check.sh` green.

- [ ] **10 — Render the search node in the high-ground view** — Give the new node
      kind its place in the right pane and the inspector. In `ctx/core/config.py`
      add a `colors.search` entry and a `ui.truncation_lines.search` entry (2
      lines, matching the other first-class turns). In
      `ctx/ui/widgets/message_row.py` add `"search"` to `_TRUNCATION_KEY` and
      `_TALL_ROLES` and give it a kind glyph in `_KIND_GLYPH` (`⌕`), the way
      `compression` carries `Σ`. In `ctx/ui/widgets/message_list.py` map
      `_SIDE["search"] = "assistant"` — a search is model-invoked, so it belongs to
      the assistant's pass, unlike a `/include`d context node — and make the side
      lookup treat a `context` node with `meta["origin"] == "model"` (a fetched
      page, task 3) as assistant-side too, so neither opens a spurious new pass
      mid-turn. Add `"search"` to `_SPLIT_VIEW_TYPES` in
      `ctx/ui/widgets/detail_inspector.py` and a `search` branch to `_node_view` in
      `ctx/ui/app.py` putting the query in the Prompt split and the rendered
      results in the Source split (Output stays empty and hides, exactly as a
      verbatim `/include` collapses). Add a `search-turn` state to
      `tools/agent/visual.py`'s `STATES` covering a settled `SEARCH` turn. Ref:
      plan §4.4, ADR-0018 §4. Depends on task 9.
      _Acceptance (visual — you must look, per PROMPT.md step 7):_ render
      `search-turn` with `tools/agent/visual.py` and judge against this sentence —
      *"the search row sits flush inside the assistant's turn with no blank line
      splitting it off, carries its own distinctly-colored left bar and a ⌕ glyph
      in the meta slot, and is clamped to two lines with its weight % on the right
      edge."* Verify your eye in both directions on a forced-defect variant before
      trusting a PASS, and record the state, the intent and the verdict in
      `PROGRESS.md`. _Deterministic floor:_ `check.sh` green plus unit tests that
      `truncation_key("search") == "search"`, that `_pass_starts` puts **no**
      separator before a search node following an assistant node nor before a
      `context` node with `meta["origin"] == "model"` (and still puts one before a
      `/include`d context node), and a snapshot assertion that a selected search
      node reports `detail.view == "context"` with the prompt and content splits
      visible.

- [ ] **11 — End-to-end verification of the phase** — Run the full ten-step
      qa-tester brief in `docs/ctx0 Phase 4 Plan — Web search.md` §5.2 verbatim
      (verify-feature mode on `tools.agent.harness:HarnessApp`), including both
      negative probes: a second submit during a research turn must be refused with
      the typed text preserved and no new user node, and `/new` mid-research-turn
      must clear the list with no stuck `streaming=yes`. Address any FAIL by fixing
      it in this task. Then confirm the phase's own done-criteria: tool output is
      compactable (step 4) and expandable (step 5) like any other node, and the
      backend is swappable by editing `search.provider` in config with no code
      change. Ref: plan §5.2, roadmap Phase 4 "Done". Depends on all above.
      _Acceptance:_ all ten steps match their expected snapshots, both negative
      probes behave, `textual_check_errors` clean throughout, and `check.sh` green.
      Record the qa-tester verdict in `PROGRESS.md`. **Note for the human, not this
      loop:** a manual live smoke against a real provider with a real
      `TAVILY_API_KEY` (plan §5.3) is still owed before the phase is called done —
      the harness proves the machinery but cannot prove a real model calls these
      schemas.

## Completed

Full bodies live in `scripts/ralph/PRD-done.md`; task numbers are preserved so
`deps:` / "task-N" references still resolve.

- [x] 1 — Search backend seam + litellm `search` adapter
- [x] 2 — `fetch(url)` on the search backend
- [x] 3 — `Node.search` and its model-facing form

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
