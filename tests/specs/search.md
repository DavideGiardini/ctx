# Behavioral contract — `ctx/core/search.py`

Derived from the PRD task + ADR-0018 §5. Deliberately scoped: this is ~90 lines of
product code whose whole job is (a) wrapping litellm's search call so no backend type
escapes, (b) mapping normalized results into domain hits, (c) an env-driven availability
check, (d) a no-network test double, (e) one new config section. The items below are the
ones a realistic regression to *this* code could break. I did **not** enumerate dataclass
field storage, `Protocol` conformance, or type-level guarantees mypy already enforces.

The module's *tool-protocol* surface — `TOOL_SCHEMAS` and `dispatch_tool_call()` — has
its own contract in `tests/specs/search-dispatch.md` (PRD task 5); nothing about it is
restated here.

C9–C13 were added when `fetch(url)` joined the seam (PRD task 2, plan D10/D13): the
page-extraction half is ours rather than litellm's, so its failure translation and its
no-truncation promise are the parts a regression could break.

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

C9. `fetch()` returns the whole readable body, boilerplate stripped, never truncated
  Given:    `LiteLLMSearch(transport=...).fetch(url)` where the stub transport serves a
            realistic article page: a `<header>`/`<nav>`, an `<aside>` of unrelated
            promo links (including a "Subscribe to the newsletter" item), a `<footer>`,
            and an `<article>` of five paragraph-length prose paragraphs.
  Expect:   a non-empty `str` containing distinctive sentences from the article body —
            from the **first** paragraph, from a middle paragraph, and from the **last**
            paragraph — while the navigation and sidebar strings ("Skip to main
            content", "Subscribe to the newsletter") are absent.
  Rationale: The method's product promise is "the page body a reader would care about,
            uncapped". The last-paragraph assertion is the truncation guard: a hidden
            length cap is a settled non-goal, because the user's levers for an oversized
            page are the token gauge and manual compaction, so silently dropping the
            tail would remove exactly the content the model was asked to read. The
            boilerplate assertions are what distinguishes extraction from a raw GET.
  Note:     nothing is asserted about markdown syntax or whitespace — that is
            Trafilatura's business, not this module's contract.

C10. The GET follows redirects
  Given:    the fetched URL is an `http://` short link whose first response is a `301`
            pointing at the `https://` canonical article URL, which the stub transport
            then serves as the article page of C9.
  Expect:   `fetch()` returns the extracted article body (not an error and not the
            redirect's empty body), and the transport sees a second request for the
            canonical URL.
  Rationale: Short links and `http`→`https` upgrades are the normal shape of a URL a
            model lifts out of a search result; without redirect following every one of
            them would come back as a non-2xx `SearchError` and web search would look
            broken for the majority of real links.
  Status:   no separate test — folded into C9's test, since the observable outcome is
            the same returned body and splitting it would duplicate the whole page
            fixture for one extra assertion.

C11. Every fetch failure raises `SearchError`, with the library exception chained
  Given:    (a) a transport that raises `httpx.ConnectError` (connection refused / DNS
            failure / timeout all arrive here), and (b) a transport that answers `404`.
  Expect:   both raise `SearchError` and nothing else — no `httpx` type escapes; in case
            (a) `exc.__cause__` is the exact `httpx` exception instance raised.
  Rationale: Same seam invariant as C1: the tool loop and the UI must be able to report
            "that page could not be read" without importing `httpx`. A dead host and a
            deleted page are both ordinary, expected outcomes of following a link the
            model found, so neither may crash the turn with a library traceback; the
            chain is what keeps the real cause in `~/.local/state/ctx/ctx.log`.

C12. An empty extraction is a failure, not a successful fetch of nothing
  Given:    a page with no extractable prose at all — nav, a couple of empty `<div>`s
            and a footer of links (a client-rendered app shell, in practice).
  Expect:   `SearchError` is raised rather than `""` returned, and `exc.__cause__` is
            `None` (there is no library exception to chain in this branch).
  Rationale: Returning an empty string would tell the model the fetch succeeded while
            handing it nothing, and the model would then answer *about* a page it never
            read. Failing loudly lets the loop try another result instead. The absent
            `__cause__` pins that this is the module's own judgement call, not a
            swallowed library error.

C13. Each fetch carries the explicit `FETCH_TIMEOUT_SECONDS` bound
  Given:    the successful fetch of C9, inspecting the request the stub transport
            received.
  Expect:   the request's effective read timeout equals the module constant
            `FETCH_TIMEOUT_SECONDS`.
  Rationale: "an explicit timeout so a hung host cannot hold a conversation turn open
            forever" — an unbounded (or library-default) fetch means one slow host can
            freeze the conversation with no way out, which is the worst failure mode of
            a tool call the user did not explicitly request.
  Status:   asserted inside C9's test rather than as its own test; it needs a successful
            request and nothing more.

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
- **How the timeout is expressed (C13).** The interface gives a single
  `FETCH_TIMEOUT_SECONDS` float, so I assume it becomes the request's read timeout
  (whether set on the client or per call — both land in `request.extensions["timeout"]`).
  If the intent is a split budget — say a short connect timeout and a longer read one —
  C13 needs restating in those terms.
  Resolved: the implementation passes the one float as the client's whole timeout, so
  every component (connect/read/write/pool) equals it; the read component is asserted.
- **Whether a non-2xx chains a cause (C11).** Raising via `response.raise_for_status()`
  chains an `httpx.HTTPStatusError`; checking the status code by hand chains nothing.
  Both satisfy the stated intent, so C11 asserts the chained cause only for the
  transport-error case and just the `SearchError` type for `404`.
- **What "a page Trafilatura cannot parse" looks like.** I could not construct HTML that
  reliably makes the extractor *raise* rather than return nothing, so that branch is
  covered only through C12's empty-extraction outcome; if Trafilatura can genuinely
  raise on malformed input, that path is untested.
