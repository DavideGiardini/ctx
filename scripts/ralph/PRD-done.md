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
