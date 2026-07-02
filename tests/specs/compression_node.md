# Behavioral contract — compression node factory & rendering

Scope: `Node.compression(...)` in `ctx/models/nodes.py`, the `goes_to_model()`
predicate for compression nodes, and `build_context(...)` rendering of compression
nodes in `ctx/core/context.py`. Derived purely from stated intent.

## Factory — `Node.compression(summary, conversation_id, range_ids, prompt="")`

C1. Canonical field combination
  Given:    `Node.compression("SUMMARY", "conv-1", ["a", "b"])`
  Expect:   the returned node has role == "compression", node_type == "compression",
            content == "SUMMARY", conversation_id == "conv-1",
            meta == {"prompt": "", "range": ["a", "b"]} (exactly those keys),
            prev_id is None, and compressed_into is None.
  Rationale:The factory is the single source of truth for the compression node kind;
            the docstring fixes each of these field values precisely.

C2. prompt is stored, default is empty
  Given:    `Node.compression(..., prompt="Summarize the debugging session")` versus
            the same call with prompt omitted.
  Expect:   meta["prompt"] equals the passed prompt string when given, and equals ""
            when omitted (a hand-written/manual summary).
  Rationale:meta["prompt"] records the instruction that produced the summary; "" is
            the documented default for a manual summary.

C3. range order is preserved verbatim
  Given:    `Node.compression("s", "conv-1", ["z", "a", "m"])`
  Expect:   meta["range"] == ["z", "a", "m"] (same elements, same order, no sort).
  Rationale:meta["range"] is the *ordered* ids of the folded children; order carries
            meaning (contiguous conversation range) and must not be reordered.

C4. Fresh id and non-aliased meta per call
  Given:    two independent `Node.compression(...)` calls.
  Expect:   the two nodes have different `id` values, and their `meta` are distinct
            dict objects (mutating one node's meta does not affect the other).
  Rationale:Each node gets a fresh unique id; mutable-default aliasing across calls
            is an explicit anti-requirement for all sibling factories.

## Predicate — `goes_to_model()`

C5. Compression node reaches the model
  Given:    a node built via `Node.compression(...)`.
  Expect:   goes_to_model() is True.
  Rationale:A compression node stands in for the folded originals and its summary is
            sent to the LLM.

C6. Predicate unchanged for existing kinds (regression guard)
  Given:    a user node, an assistant node, a context node, and a system node.
  Expect:   goes_to_model() is True for user, assistant, and context; False for system.
  Rationale:Adding compression must not disturb the existing single-source-of-truth
            predicate for the other kinds.

## Rendering — `build_context(nodes, load_file)`

C7. Lone compression node renders one wrapped user dict, no preamble
  Given:    `build_context([K], loader)` where K summarizes some range with a distinct
            summary string.
  Expect:   exactly one message dict, role == "user", whose content starts with
            "<conversation_summary>", ends with "</conversation_summary>", contains the
            summary text, and adds no extra preamble/framing beyond that wrapper.
  Rationale:Compression summaries are USER-role material wrapped exactly in the
            documented tags with no additional framing.

C8. Compression then user coalesce into one user dict (summary first)
  Given:    `[K, user_turn]` with distinct summary and user text.
  Expect:   exactly one user dict; its content contains both the wrapped summary and
            the user text, with the wrapped summary appearing before the user text.
  Rationale:Adjacent USER-role material is coalesced into one user message; a summary
            merges like an import, preserving source order.

C9. User then compression coalesce into one user dict (user text first)
  Given:    `[user_turn, K]` with distinct summary and user text.
  Expect:   exactly one user dict; its content contains both the user text and the
            wrapped summary, with the user text appearing before the wrapped summary.
  Rationale:Same coalescing rule, order preserved with the user turn first.

C10. Assistant turn splits coalescing
  Given:    `[K1, assistant_turn, K2]` (or user/compression on either side) with a
            non-empty assistant turn between two user-side items.
  Expect:   the message list contains two separate user dicts (one per user-side item)
            with the assistant dict between them; the two summaries are not merged into
            a single user dict.
  Rationale:An assistant turn between user-side items breaks coalescing into separate
            user messages.

C11. Dropped system node still splits coalescing
  Given:    `[K1, system_node, K2]` where the system node never reaches the model.
  Expect:   the message list contains two separate user dicts (one per compression
            summary), no system message, and the two summaries are NOT merged.
  Rationale:A system node is dropped from output but still acts as a boundary that
            breaks user-side coalescing.

C12. Ordering across mixed types preserved
  Given:    `[user u1, assistant a1, compression K]` with distinct texts.
  Expect:   three message dicts in order: user dict containing "u1", assistant dict
            containing "a1", user dict containing the wrapped summary.
  Rationale:build_context preserves source order across node kinds.

C13. Folded children content does not leak via K
  Given:    child nodes with distinct bodies are compressed; K carries only the summary,
            and `build_context([K], loader)` is rendered.
  Expect:   the rendered content contains the summary text but none of the child bodies.
  Rationale:K stands in for the originals — the LLM sees the summary instead of the
            folded child contents.

## Intent ambiguities assumed past (flag for human)

- A1. Whether the coalesced user content joins the wrapped summary and adjacent user
  text with a newline, space, or other separator is not specified. Tests assert only
  relative ordering and substring presence, not the exact joiner.
- A2. Whether an *empty*-content compression node (content == "") produces a message is
  not specified by the docstring (the empty-node rule is stated for user/assistant).
  Not tested; flagged.
- A3. C11 assumes a system node with non-empty content still yields zero output messages
  and acts purely as a boundary; the docstring says system nodes never reach the model,
  which we read as "produces no dict but still separates neighbors".
