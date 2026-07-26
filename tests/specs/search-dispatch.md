# Behavioral contract — tool dispatch for the model's web tools

Scope: `TOOL_SCHEMAS` and `dispatch_tool_call(call, backend, conversation_id)` in
`ctx/core/search.py`. The rest of the module (backend seam, litellm adapter,
`Node.search`) is covered by `tests/specs/search.md`.

This is a scoped contract for ~70 lines of new product code, deliberately sized to
the change: it enumerates only what a realistic regression to *this* code could
break. Behaviors already guaranteed elsewhere — dataclass field storage, `Protocol`
conformance, the exact rendering `Node.search` produces, JSON-schema plumbing — are
out of scope on purpose.

---

C1. A successful `search` call becomes a search node carrying the backend's ranking
  Given:    a `ToolCall(name="search", arguments='{"query": "<q>"}')`, a backend whose
            `search` returns three `SearchHit`s in a definite order (one of them with
            `date=None`), and `conversation_id="conv-1"`.
  Expect:   returns `(node, result_text)` where `node.node_type == "search"`,
            `node.role == "search"`, `node.conversation_id == "conv-1"`,
            `node.meta["query"] == "<q>"` exactly as the model wrote it, and
            `node.meta["hits"]` equals `[{"title": h.title, "url": h.url,
            "snippet": h.snippet, "date": h.date} for h in backend_hits]` — same
            length, same order, plain dicts with exactly those four keys, and
            `json.dumps`-able. `result_text == node.content` and is non-empty.
  Rationale:The ranking belongs to the backend, so dispatch must neither reorder nor
            trim it. The graph is persisted to SQLite, so hits have to leave this
            function as JSON-able data rather than live `SearchHit` objects or they
            could not survive a resume. Model and user must see the same result
            block, hence `result_text` is the node's own rendered content.

C2. A successful `fetch` call becomes a model-origin context import of the whole page
  Given:    a `ToolCall(name="fetch", arguments='{"url": "<u>"}')` and a backend whose
            `fetch` returns a long page body (many thousands of characters).
  Expect:   `node.node_type == "context"`, `node.meta["source_path"] == "<u>"`,
            `node.meta["origin"] == "model"`, `node.meta["prompt"] == ""`,
            `node.content` equals the page body byte-for-byte (no truncation, no
            cap), `node.conversation_id == "conv-1"`, and the full page body is
            present in `result_text`.
  Rationale:A fetched page is an import whose source happens to be a URL, not a new
            node kind — reusing `Node.context` is what gives it the same storage,
            wrapper, inspector and weight accounting as a hand-imported file. The
            `origin="model"` stamp is the only thing that answers "did the model pull
            this in?". No length cap here is an explicit product decision, so a
            truncating regression must fail. `prompt == ""` marks a verbatim import.

C3. A malformed or unknown call never raises, never reaches the backend, and yields a
    durable system breadcrumb
  Given:    any of these, with a backend that records every call it receives:
            (a) an unknown tool name, e.g. `name="browse_web"`;
            (b) `name="search"` with arguments that are not valid JSON (a truncated
                blob such as `'{"query": "atlantic overturning circu'`);
            (c) `name="fetch"` with valid JSON that lacks the required argument
                (e.g. `'{"link": "https://…"}'`);
            (d) `name="search"` with a non-string in the required argument
                (e.g. `'{"query": 42}'`).
  Expect:   no exception escapes; the backend records zero `search` and zero `fetch`
            invocations; `node.node_type == "system"`, `node.role == "system"`,
            `node.conversation_id == "conv-1"` (durable, so the attempt survives a
            resume), `node.goes_to_model() is False`; `result_text` is non-empty,
            appears inside `node.content` (the user gets the same explanation the
            model got), and names the offending thing — the bad tool name for (a),
            JSON for (b), the missing argument's name for (c), the argument's name
            for (d).
  Rationale:Tool calls are speculative: the model can hallucinate a tool name or emit
            a truncated arguments blob on a perfectly good day. Raising would kill a
            turn the user is watching stream, so the failure must come back as text
            the model can act on. A number where the query belongs must not be handed
            to the backend at all. And the failure must still leave a node, or the
            user sees a silently thinner answer with no trace of the attempt; a
            *system* node specifically, because a system node never reaches the model
            and so the error text does not linger in context on every later turn.

C4. A `SearchError` from either backend method is reported, not raised
  Given:    a backend whose `search` and `fetch` both raise
            `SearchError("search backend returned 429 Too Many Requests")`, and a
            well-formed call — once for `search`, once for `fetch`.
  Expect:   in both cases no exception escapes; `result_text` is non-empty and
            contains the error's own message text so the model can tell what went
            wrong; the node is the same durable, non-model-facing system breadcrumb
            as C3 (`node_type == "system"`, `goes_to_model() is False`,
            `conversation_id == "conv-1"`, `result_text in node.content`).
            Nothing is retried: the backend is invoked at most once per call.
  Rationale:Rate limits, outages and 404s are ordinary weather for a web tool. The
            model is free to try a different query, a different URL, or answer from
            what it already has — which it can only do if it is told why the call
            failed rather than having the turn die.

C5. `TOOL_SCHEMAS` offers exactly `search(query)` and `fetch(url)` with neutral prose
  Given:    `TOOL_SCHEMAS` as offered to the provider.
  Expect:   exactly two tool definitions, named `search` and `fetch`; `search`
            declares one required string parameter `query` and `fetch` one required
            string parameter `url`; every description is non-empty and contains no
            usage guidance — no "when you", "if you", "you should", "always",
            "never", "prefer", "make sure to".
  Rationale:The parameter names are the wire contract with the model: rename one and
            every real call arrives as a missing-argument failure (C3c). The
            neutrality of the descriptions is a deliberate product decision — the
            schemas state the capability and say nothing about *when* to search, so
            the model's own judgment stays unbiased.

---

## Intent ambiguities I had to assume past (flag for a human)

1. **`result_text` for a successful `fetch`.** The intent fixes it for `search`
   (identical to the node's rendered block) and says the page goes to the model
   "whole", but not whether the tool result is the bare page or the page inside a
   small wrapper (e.g. a "Fetched <url>" header). C2 therefore asserts the page is
   *contained in* `result_text` rather than equal to it. Tighten to equality if the
   bare page is the intended answer.
2. **What the error text must name.** The prose says only "explanatory". C3/C4 assert
   the offending token appears (bad tool name, the word JSON, the argument name, the
   `SearchError` message) and never assert exact prose. If the message deliberately
   withholds, say, the argument name, C3 needs adjusting.
3. **Neutrality as a testable property.** "Neutral capability statement" has no
   mechanical definition, so C5 uses a small blocklist of guidance phrases. It can
   only catch the obvious regression (someone adding "use this whenever the user asks
   about current events"), not subtle steering.
4. **The failing node's `role`.** `Node.system` sets `role` and `node_type` both to
   `"system"`, so C3 asserts both; if a failure node is ever meant to carry a
   different role while staying non-model-facing, `goes_to_model() is False` is the
   assertion that actually matters.
5. **A backend that fails on only one of the two methods** is not distinguished from
   one that fails on both; C4 uses a both-methods-fail backend, which is sufficient
   to cover each call path once.
