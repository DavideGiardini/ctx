# Contract — mid-turn node mounting, stream retargeting, empty-row filtering

Scope: the `ChatApp` turn-streaming view (`ctx/ui/app.py`) once a single submit can
append several nodes (search, context, system breadcrumb, extra assistant rounds).
This is a scoped contract for a ~35-line change, not full coverage of `ChatApp`.
Behaviors that predate the change (ordinary two-node turn, cursor movement, header
gauge) are deliberately out of scope: a regression in *this* change cannot reach them
without also breaking the clauses below.

Terms: *graph* = `app.core.nodes`, the raw append-only node list. *Visible* = what
`_visible_nodes()` returns, which is what the message pane, cursor navigation, the
per-node weights and `describe_state()["nodes"]` all read.

---

C1. A node appended mid-turn is mounted while the turn is still live
  Given:    a turn submitted with a search trigger, observed *before* the worker
            finishes (`app.core.streaming` is still `True`), after the model's
            round-1 lead-in text and its search call.
  Expect:   at an instant when `app.core.streaming is True` and a node with
            `node_type == "search"` is present in the graph, the message pane already
            contains exactly one row with DOM id `f"msg-{search_node.id}"`, and that
            row's rendered content contains the first hit's URL.
  Rationale:Intent 1 — the user watches a research turn build up. Nodes reach the view
            through the `on_node` callback as the turn runs, not in a batch at the end.
            Asserting only after the turn settles would pass for a build-at-the-end
            implementation, which is exactly the regression this guards.

C2. Round-2 text renders in its own row, never appended to round 1's row
  Given:    a completed search turn: round 1 streams the lead-in text and then calls
            the search tool; round 2 streams the canned answer.
  Expect:   the graph holds two assistant message nodes. The row for the first
            contains the lead-in text and does **not** contain the round-2 answer
            text; the row for the second contains the round-2 answer text. The two
            rows are distinct DOM nodes.
  Rationale:Intent 2 — the live-stream pointers retarget to the assistant node created
            lazily on round 2's first token. If they do not retarget, round-2 tokens
            land on round 1's widget and the second row stays empty (or never mounts);
            asserting on node content alone would miss that, because the core nodes are
            correct either way. The oracle is therefore the *widget* text.

C3. An empty assistant node survives in the graph but is dropped from the view
  Given:    a completed fetch turn that opens on a silent tool call, so the assistant
            node `submit()` created for round 1 never receives a token and keeps
            `content == ""`; a later round streams the answer.
  Expect:   at least one assistant message node with `content == ""` is still present
            in `app.core.nodes` (nothing was mutated or removed), and
            `describe_state()["nodes"]` contains **no** entry with
            `role == "assistant"` and `content == ""`. The fetched page
            (`node_type == "context"`) and a non-empty assistant answer are both still
            visible.
  Rationale:Intent 3 — the graph is strictly append-only (ADR-0016), so the fix is a
            view filter, not a deletion. Both halves must hold: deleting the node would
            break the graph invariant, keeping it visible would leave a blank row.

C4. Weights are computed over the visible list and pair with it by index
  Given:    the same completed fetch turn, whose graph contains at least one filtered
            empty assistant node.
  Expect:   `len(describe_state()["nodes"]) == len(app.core.nodes) - <number of empty
            assistant nodes filtered>`; the `"index"` values are exactly
            `range(len(visible))`; every `"weight_pct"` is either `None` or an int in
            `0..100`; and building the snapshot raises nothing.
  Rationale:Intent 4 — if weights were still computed over the raw graph while the view
            filtered, the by-index pairing would be off by one (a row showing its
            neighbour's percentage) or the zip/index would blow up. Contiguous indices
            plus an exact visible-count are what catch the off-by-one.

C5. Two empty assistant nodes stay visible: the currently-streaming one, and one
    carrying a durable `meta["error"]`
  Given:    (a) mid-turn, the assistant node the turn is streaming into before its
            first token; (b) after a failed turn, the assistant node marked with an
            error.
  Expect:   both remain in `_visible_nodes()` / `describe_state()["nodes"]`, so the
            row being streamed into is not yanked out from under the user and the
            "Error: …" row remains the only trace a failed turn leaves.
  Rationale:The filter is "empty *and* uninteresting", not "empty". Over-filtering here
            is a visible regression (a row disappearing mid-stream).
  Status:   **Not tested** under this scope budget. (a) needs a third mid-turn
            observation test whose window is one token wide and therefore flaky; (b)
            needs a durable-error fixture the harness triggers do not obviously
            provide — the `SEARCHFAIL` trigger produces a *system breadcrumb* node,
            which is a different node kind than an error-marked assistant node. Flagged
            for the human: if a durable assistant error mark is reachable from the
            harness, C5(b) is worth one more test.

C6. A silent round gives up its caret row before its tool runs
  Given:    a fetch turn whose round 1 streams no text and asks for a search,
            observed while the search backend is still blocked — so
            `app.core.streaming` is `True` and the search has produced no node yet.
  Expect:   the empty round-1 assistant node has **no** row in the message pane
            (`#msg-<id>` matches nothing) and no entry in
            `describe_state()["nodes"]`.
  Rationale:The `▌` caret means "an answer is being typed". Retiring the row when the
            *tool node lands* would be too late: that node does not exist until the
            search has already returned, so the caret would stand in for a
            never-coming answer for the whole wait. The observation window is
            therefore mid-search, which is what makes this clause distinct from C3
            (same node, asserted after the turn settles). Answers A1: the row is
            unmounted, not merely un-rendered.

---

## Ambiguities (assumed past, please confirm)

A1. **Does the row for a now-invisible node get unmounted?** — **Answered: yes**, and
    C6 now asserts it. The empty round-1 row is reconciled out of the DOM at
    `on_tool_round`, before the tool runs.

A2. **Exact count of empty assistant nodes in the fetch flow.** I assumed the middle
    (fetch) round produces no assistant node at all, since a round's node is created
    lazily on its first token and that round streams no text. C4 is written to be
    robust to this: it counts the empty assistant nodes actually present rather than
    hard-coding one.

A3. **Whether `describe_state()` content is truncated.** The snapshot carries a
    `"truncated"` flag, so long content may be elided. Assertions on the answer text
    therefore use the widget's `._content` (C2) or a non-emptiness check (C3), never an
    exact equality against the full canned answer inside the snapshot.

A4. **Timing of the mid-turn observation (C1).** I assume the answering round streams
    enough tokens that a bounded `wait_until` spin can observe the live state; the
    predicate checks "streaming is True *and* the row exists" atomically inside one
    poll so a fast-completing turn fails the test rather than passing it vacuously.
