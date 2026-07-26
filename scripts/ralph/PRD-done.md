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
