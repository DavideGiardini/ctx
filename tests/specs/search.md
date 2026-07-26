# Behavioral contract — `ctx/core/search.py`

Derived from the PRD task + ADR-0018 §5. Deliberately scoped: this is ~90 lines of
product code whose whole job is (a) wrapping litellm's search call so no backend type
escapes, (b) mapping normalized results into domain hits, (c) an env-driven availability
check, (d) a no-network test double, (e) one new config section. The items below are the
ones a realistic regression to *this* code could break. I did **not** enumerate dataclass
field storage, `Protocol` conformance, or type-level guarantees mypy already enforces.

---

C1. Any backend failure surfaces as `SearchError` with the original chained
  Given:    `LiteLLMSearch().search("who won the 2026 tour de france")` where the bound
            litellm entry point (`ctx.core.search.asearch`) raises an arbitrary
            exception type this module has never heard of.
  Expect:   `SearchError` is raised (not the backend exception), and
            `exc.__cause__` is the exact exception instance the backend raised.
  Rationale: ADR-0018 §5 and the `ProviderError` discipline: the rest of ctx must never
            import or catch a litellm/httpx type, so the seam must translate *every*
            failure, including unknown ones — a `except (litellm.X, httpx.Y)` style
            guard would leak the next unfamiliar error straight to the UI. Chaining is
            what preserves the diagnostic for the log.

C2. A successful search yields domain hits, backend order preserved, dates optional
  Given:    the stubbed backend returns two normalized results in a definite order
            (best first), the first with a publication date, the second without one.
  Expect:   `search()` returns a `list` of exactly two objects, every one an instance of
            `SearchHit` (no backend/litellm object passed through); `[0]` carries the
            first result's title/url/snippet and its date string; `[1]` carries the
            second result's fields with `date is None`; the returned order equals the
            backend's order.
  Rationale: The module's value is normalizing into domain types while staying a
            faithful ranker-preserving pipe — reordering or dropping results would
            silently degrade answer quality, and letting a backend object through would
            break the "no backend type escapes" invariant just as surely as an
            exception would.

C3. The configured provider and result count are honoured per call
  Given:    a user config that sets `search.provider` to a non-default backend and
            `search.max_results` to a non-default number, then one `search()` call.
  Expect:   the values handed to the litellm search call include that configured
            provider name, that configured result count, and the caller's query string.
  Rationale: "read per call so editing one config line swaps backends with no restart" —
            if the adapter hardcoded the backend, or snapshotted config at import time,
            the documented no-restart behavior would be a lie.
  Note:     asserted on the *values* passed to the stub, not on parameter names, since
            litellm's exact kwarg spelling is not part of this module's contract.

C4. An empty result set is a successful empty list, not an error
  Given:    the stubbed backend returns a normalized response whose results are empty.
  Expect:   `search()` returns `[]` and raises nothing.
  Rationale: "found nothing" is a legitimate answer the model must be able to relay;
            turning it into `SearchError` would make the tool loop retry or apologize
            for a working search.
  Status:   no separate test — it is C2's mapping path with zero items, and C3's stub
            already returns an empty response without raising. Pruned by the deletion
            test rather than left as a shallow duplicate.

C5. `search_available()` follows the environment for the configured provider, uncached
  Given:    the default configuration (provider `tavily`, whose key is
            `TAVILY_API_KEY`), and a single process in which that variable is first
            absent, then set, then removed again.
  Expect:   `False`, then `True`, then `False` — each call reflecting the environment at
            the moment it is called.
  Rationale: Tools must never be offered to the model when the key is missing, or the
            model promises a search it cannot run. No caching, because the user may
            export the key after launch and expects search to light up.

C6. An unrecognized provider name reports unavailable
  Given:    a user config setting `search.provider` to a name litellm does not know,
            with no relevant key in the environment.
  Expect:   `search_available()` returns `False`.
  Rationale: Fail closed on a typo'd config value: reporting available would offer the
            model a tool whose every call is guaranteed to fail.

C7. `TestSearch` is the deterministic no-network double
  Given:    `TestSearch(hits=[...])` searched with two different queries; and
            separately `TestSearch(error=RuntimeError(...))`.
  Expect:   the hits instance returns exactly the canned hits for either query; the
            error instance raises that exact exception instance from `search()`.
  Rationale: The later tool loop is only testable if the double is query-independent and
            can be driven into the failure branch on demand.

C8. The `search` config section defaults, and partial overrides merge
  Given:    `get_config()` with no user config file; and again with a user config file
            that sets only `search.provider`.
  Expect:   with no file, `config["search"] == {"provider": "tavily", "max_results": 5,
            "max_tool_calls": 12}`; with the partial file, the overridden `provider`
            takes the user's value while `max_results` and `max_tool_calls` keep the
            defaults `5` and `12`.
  Rationale: Every other section in `get_config()` merges rather than replaces; a
            replace here would blank `max_results`/`max_tool_calls` for anyone who only
            wanted to change backend, breaking search for the users most likely to
            touch the setting.

---

## Intent ambiguities I had to assume past (flag for a human)

- **litellm's call shape.** I was told `asearch` is awaited and returns an object with
  `.results`. I do not know the parameter names it takes for provider/query/result
  count, so C3 asserts only that the configured *values* reach the call — it will not
  catch passing `max_results` where litellm expects e.g. `num_results`.
- **Whether `get_config()` memoizes.** I assume it re-reads `CONFIG_PATH` per call (the
  harness note says monkeypatching the path controls the result). If it were cached,
  C8's second case would need a cache reset.
- **Key names beyond tavily.** Only `TAVILY_API_KEY` is specified, so C5 pins the
  default provider only; per-backend key mapping for the other thirteen backends is
  untested here.
- **Does `search()` itself pre-check the key?** Unspecified. C1–C4 keep a dummy key in
  the environment so the tests exercise the mapping/wrapping path either way.
