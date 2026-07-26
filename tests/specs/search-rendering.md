# Contract — rendering the web-tool nodes (search + model-fetched page)

Scope: the *view* side of Phase 4's two web tools. A `search` node is a new node
kind (`role == node_type == "search"`); a page the model fetched is an ordinary
`context` node stamped with `meta["origin"] == "model"`. This task only gives
those two node shapes their place in the right-pane conversation list and in the
left-pane Detail Inspector. Deliberately scoped down (~45 lines of product code,
mostly new rows in existing role→config tables): the clauses below are the ones a
realistic regression to *this* change could break. Plain table lookups beyond one
representative case, anything `mypy`/`ruff` already enforces, and colors/geometry
are out of scope on purpose.

## C1. A search node truncates on its own config key

- **Given:** the role string `"search"`, passed to
  `ctx.ui.widgets.message_row.truncation_key`.
- **Expect:** it returns exactly `"search"`, and that value is *different* from
  `truncation_key("system")` (which returns `"system"`). So the two roles read
  two different `ui.truncation_lines` entries.
- **Rationale:** `search` is a first-class turn with its own 2-line compact row.
  If it fell through to the catch-all `"system"` key it would silently clamp to 1
  line. Because this function is the single source of truth shared by the row's
  own rendering and `describe_state`'s `truncated` flag, a wrong key doesn't just
  mis-render — it makes the headless snapshot disagree with the screen.

## C2. Neither tool node opens a spurious turn boundary

- **Given:** one ordered node list standing in for a complete research turn
  followed by the start of the next human turn — `context("notes.md", user)`,
  `user`, `assistant` (lead-in), `search`, `context(origin="model")`,
  `assistant` (final answer), `context("handbook.md", user)`, `user`
  (follow-up) — passed to `ctx.ui.widgets.message_list._pass_starts`.
- **Expect:** `[False, False, True, False, False, False, True, False]`.
  Concretely: the first node is never a pass start; a user query sits in the same
  pass as the context file it was `/include`d with; the assistant's lead-in opens
  exactly one new pass; the `search`, the model-fetched page and the assistant's
  final answer all sit *flush* inside that same assistant pass; a file the *user*
  included does start a new pass even directly after an assistant reply; and the
  user's follow-up query joins that new human pass.
- **Rationale:** `MessageList` puts exactly one blank-line `Separator` before
  each pass start, so this list *is* the visible "one blank line between turns,
  none within a turn" rule. Both tool nodes are model-invoked, so they belong to
  the assistant's pass; treating them as pass starts visibly shatters one
  research turn into three fake turns. The contrast case matters just as much: a
  page the model fetched and a file the user included are the same `context` node
  kind, and only `meta["origin"]` distinguishes them — the user's action is still
  a human pass and must still detach.

## C3. A selected search node renders in the inspector's 3-split view

- **Given:** a real app driven headlessly through one scripted research turn
  (four visible nodes: `user`, `assistant`, `search`, `assistant`), in Edit mode,
  with the cursor moved onto the `search` row (index 2).
- **Expect:** from `describe_state()`: `selected_index == 2`,
  `nodes[2]["role"] == "search"` and `nodes[2]["node_type"] == "search"`,
  `detail["node_index"] == 2`, `detail["node_role"] == "search"`,
  `detail["view"] == "context"` (the 3-split shape) and
  `detail["splits_visible"] == ["prompt", "content"]` — the query in Prompt, the
  rendered hit list in Source, Output empty and therefore hidden.
- **Rationale:** a search has a distinct input (the query) and output (the ranked
  hits), so it belongs to the 3-split family alongside context imports and
  compression summaries rather than the flat Markdown view. With no Output the
  split collapses to two, exactly as a verbatim `/include` does.

## C4. Ordinary turns keep the plain Markdown inspector

- **Given:** the same app state as C3, with the cursor moved on one row further
  to the trailing `assistant` node (index 3).
- **Expect:** `detail["node_role"] == "assistant"`, `detail["view"] ==
  "standard"` and `detail["splits_visible"] == []`.
- **Rationale:** adding `search` to the 3-split family must not widen it. This is
  the negative half of C3 — without it, a table edit that turned *every* role
  into a 3-split view would pass C3 unnoticed.

## Ambiguities (assumed past — worth a human confirming)

1. **A second assistant node inside one assistant pass.** The intent says an
   assistant pass is "the reply, the searches it ran and the pages it fetched"
   and that getting this wrong "visibly splits one research turn into three fake
   turns". A scripted turn is `assistant` → `search` → `assistant`, and three
   fake turns is exactly that triple, so I assumed the *trailing* assistant node
   is flush (not a pass start) — i.e. consecutive assistant nodes group. If a
   post-tool assistant node is meant to open its own pass, C2's index 5 flips.
2. **Order inside a human pass.** I assumed a user-origin `context` node and the
   `user` query adjacent to it are one pass in *either* order (C2 index 1 has the
   query after the include). The intent phrases the pass as "the user's query
   plus the context files they `/include`d" without fixing an order.
3. **The catch-all's reach.** I only pin `truncation_key("search") == "search"`
   and `truncation_key("system") == "system"`. Whether an *unrecognized* role
   also returns `"system"` (versus raising) is not stated, so it is untested.
4. **Not testable from the interface alone:** the second half of C1's rationale —
   that the row's own clamping and `describe_state`'s `truncated` flag agree in
   pixels — would require asserting concrete configured line counts against
   rendered content height. The shared-key assertion is the observable proxy.
