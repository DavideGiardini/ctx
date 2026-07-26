# Spec: search nodes and how they reach the model

Modules under contract:
- `ctx/models/nodes.py` — `Node.search()`, `Node.context(origin=...)`, `Node.goes_to_model()`
- `ctx/core/context.py` — `model_facing_form()`, `build_context()`

**PRD acceptance floor.** Every item below (S1–S7) is the floor for the task
"search node kind + how it reaches the LLM". Nothing here is optional and
nothing beyond it is in scope: the contract is deliberately sized to the ~40
lines of product code this task adds, so it does *not* re-cover the shapes of
`Node.user`/`.assistant`/`.system`/`.compression`, the compression wrapper, the
legacy `load_file` path, or dataclass field defaults — those are contracted
elsewhere.

Two deliberate non-goals, so a future reader does not "fix" their absence:

- **No byte-exact rendering template.** The rendered results block is pinned by
  what it must *carry* (rank order, title, url, snippet, date-when-present),
  never by whitespace, separators, or numbering style. A test that breaks when
  the block gains a blank line would be a defect.
- **No new node kind for fetched pages.** A fetched page is an import whose
  source is a URL, so it stays a `context` node; only the `origin` marker is
  new (S7).

---

S1. `Node.search` shape and meta vocabulary
  Given:    `Node.search(query="textual reactive watch method", results=[two ranked hits], conversation_id="conv-7f3a")`
  Expect:   the returned node has `role == "search"` and `node_type == "search"`;
            `meta["query"]` is the query string exactly as passed; `meta["hits"]`
            is the structured hit list as passed (same dicts, same order), so the
            individual hits are recoverable without re-parsing `content`.
  Rationale:A search is its own kind because a query plus a ranked hit list is a
            different shape from a file snapshot, and the high-ground view must
            tell them apart at a glance. The two meta keys are the canonical
            vocabulary every consumer (view layer, inspector, token gauge)
            reads, so their names and contents are the interface.

S2. The rendered block faithfully carries the hits, in ranked order
  Given:    a search node built from three hits, best hit first, where the first
            hit has a `date`, the second omits the `date` key entirely, and the
            third has `date=None`.
  Expect:   `content` contains every hit's title, url and snippet; the three
            hits appear in `content` in the order they were given (best first);
            the first hit's date string appears in `content`; the block renders
            without raising for the date-less hits and no placeholder date value
            (e.g. the literal `None`) leaks into the text.
  Rationale:`content` is what the model actually reads, so the ranking and the
            per-hit facts are the payload — the model cannot rank or cite what
            is not there. Backends differ on whether they report a date, so a
            missing or null date is normal input, not an error case, and must
            not surface as a rendering artefact.

S3. A search node reaches the model
  Given:    a search node with at least one hit.
  Expect:   `goes_to_model()` returns `True`.
  Rationale:`goes_to_model()` is the single source of truth for which nodes are
            sent to the LLM. Search history must be replayed, otherwise the
            model loses the evidence it just gathered on the next turn.

S4. `build_context` wraps the block in `<search_results query="…">` as user text
  Given:    a single search node with hits, passed to `build_context`.
  Expect:   exactly one message dict is produced; its `role` is `"user"`; its
            content contains the opening tag `<search_results query="<the exact
            query>">` and the closing tag `</search_results>`, and the rendered
            block's hit material sits inside that wrapper. `model_facing_form`
            reports the same node under the `"user"` role with the rendered
            block as its body.
  Rationale:Search history is replayed as ordinary XML-wrapped *user text*, not
            as a native tool-protocol message, precisely so a search node can be
            folded into a summary later; a native tool call would leave a
            dangling reference and the provider would reject the very next
            request. The query lives in the attribute so the model can tell
            which question a hit list answers.

S5. Search material merges into adjacent user material (role-alternation invariant)
  Given:    the node list `[user turn, search node A, assistant turn, search
            node B, user turn]`.
  Expect:   `build_context` returns exactly three messages with roles
            `["user", "assistant", "user"]` — no two adjacent messages share a
            role. The first message carries both the user's text and search A's
            `<search_results>` block, with the user text followed by a `\n\n`
            separator and then the wrapper. The trailing message carries both
            search B's block and the final user text (search material after an
            assistant turn starts a fresh user message rather than a second one).
  Rationale:Strict role-alternation providers reject consecutive same-role
            turns, so user-role material following an already-emitted user
            message must be merged, never appended as a second user dict. A
            search node is user-role material like an import, so it inherits
            that merging — this is the whole point of not making it a tool
            message, and the invariant is what keeps a request valid.

S6. An empty search contributes nothing
  Given:    `Node.search(query="quantum error correction 2026 benchmarks", results=[], conversation_id=...)`,
            and the node list `[user turn, that empty search node]`.
  Expect:   the node's `content` is empty; `model_facing_form` returns `None`
            for it; `build_context` returns exactly one message (the user turn),
            whose content contains no `<search_results` wrapper.
  Rationale:A search that found nothing has no evidence to offer, and emitting
            an empty wrapper would spend tokens on noise and risk an empty
            user turn. This is the same rule an empty context import already
            follows, so the two kinds stay consistent.

S7. `origin` marks a model-fetched import and only that
  Given:    two context nodes for the same URL-sourced page — one built with
            `origin="model"`, one built with the default origin.
  Expect:   the `origin="model"` node has `meta["origin"] == "model"`; the
            default node has no `"origin"` key in `meta` at all (`"origin" not
            in node.meta`), while both keep `role`/`node_type == "context"` and
            their `meta["source_path"]`.
  Rationale:A fetched page is an import whose source is a URL, so it must not
            become a new node kind. The view layer only needs to answer "did the
            model pull this in?", and stamping nothing in the default case means
            the key's mere presence answers it — and hand-driven `/include`
            nodes plus everything already stored stay byte-identical to today.

---

## Intent ambiguities I assumed past (flag for a human)

1. **Date rendering location and format.** The docstring says the date is
    "shown when the hit has one" but not where or in what format. S2 only
    asserts the date string appears somewhere in the block, so any placement
    passes.
2. **`meta["hits"]` identity vs. copy.** "the structured hit list" does not say
    whether the factory stores the caller's list object or a copy. S1 asserts
    value equality only, so either is fine.
3. **Query escaping in the XML attribute.** Nothing states how a query
    containing a `"` or `&` is escaped, so S1/S4 use plain queries and the
    contract stays silent on escaping. If the model can produce such queries,
    that needs its own decision and item.
