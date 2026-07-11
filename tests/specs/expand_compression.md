# Behavioral contract — `expand_compression` (+ `Node.expand`)

Covers `ConversationCore.expand_compression` (in `ctx.core.conversation`) and the
`Node.expand` factory (in `ctx.models.nodes`). Derived from the PRD Sprint 3 task +
ADR-0016 (append-only conversation graph: no op-log / soft-delete / mute; the
inverse of compression is a non-destructive *expand event*, K is kept as an
off-line orphan). Numbering continues after the commit_compression contract
(which ended at C103).

`expand_compression` is the safe, non-destructive inverse of `commit_compression`.
Assertions are on observable API (`current_view()` ids / roles / node_types, the
returned compression nodes, `core.streaming`) — never on private internals.

---

C104. View restores folded children in place
  Setup:  Line `[u1,a1,u2,a2]`; `commit_compression(u2.id, a2.id, summary)` → view `[u1,a1,K]`.
  Action: `expand_compression(K.id)`.
  Expect: `current_view()` ids == `[u1.id, a1.id, u2.id, a2.id]` in that order; no
          node in the view has `node_type == "compression"`.
  Rationale: Expand is the inverse of compression — it must undo the fold and
             restore the children exactly, since ADR-0016 makes it non-destructive.

C105. Expand clears `compressed_into` on every folded child
  Setup:  As C104, folded to `[u1,a1,K]` (u2, a2 carry `compressed_into == K.id`).
  Action: `expand_compression(K.id)`.
  Expect: In the restored view, the child nodes (u2, a2) appear as themselves — i.e.
          the same ids reappear and no compression node stands in their place;
          each restored child's `compressed_into` is `None` (observable because
          they are once again projected individually by `current_view()`).
  Rationale: The docstring states every folded child read from `K.meta["range"]`
             has `compressed_into` cleared so the view restores them in K's place.

C106. Expand event effect persists across reload
  Setup:  Line `[u1,a1,u2,a2]`; commit → `[u1,a1,K]`; `expand_compression(K.id)`.
  Action: On a second core `core2.resume_conversation(core.conversation_id)`.
  Expect: `core2.current_view()` ids == `[u1.id, a1.id, u2.id, a2.id]`; no
          compression node in the reloaded view.
  Rationale: The mutation is persisted; the expand (a real graph event that cleared
             the folds) must survive a reload, confirming the E node's *effect*
             (children restored) round-trips even without a public off-line accessor.

C107. K survives expand (kept as off-line orphan, not deleted) — re-compression works
  Setup:  Line `[u1,a1,u2,a2]`; commit → K; `expand_compression(K.id)`.
  Action: `commit_compression(u2.id, a2.id, summary2)` again.
  Expect: The second commit succeeds and returns a compression node `K2`
          (`K2.node_type == "compression"`), and `current_view()` folds to
          `[u1.id, a1.id, K2.id]`.
  Rationale: Expand keeps K in the graph (never row-deletes), so the graph stays
             consistent and the same range can be re-compressed afterward.

C108. Re-compression yields a fresh, distinct K′
  Setup:  As C107, after expand restores `[u1,a1,u2,a2]`.
  Action: `K2 = commit_compression(u2.id, a2.id, summary2)`.
  Expect: `K2.id != K.id`; `K2.content == summary2`;
          `K2.meta["range"] == [u2.id, a2.id]`; view folds to `[u1,a1,K2]`.
  Rationale: Each compression is a new event node; re-compressing after expand must
             produce a genuinely new node, not resurrect the old K.

C109. Expanding an already-expanded K raises ValueError, view unchanged
  Setup:  Line `[u1,a1,u2,a2]`; commit → K; `expand_compression(K.id)` (K now inactive).
  Action: `expand_compression(K.id)` a second time.
  Expect: raises `ValueError`; `current_view()` ids still == `[u1,a1,u2,a2]`
          (unchanged from the first, successful expand).
  Rationale: An already-expanded K is inactive (no node carries
             `compressed_into == K.id`), so it must be rejected, and rejection is a
             no-op on the view.

C110. Expanding an unknown id raises ValueError
  Setup:  Line `[u1,a1,u2,a2]`; commit → view `[u1,a1,K]`.
  Action: `expand_compression("does-not-exist-0000")`.
  Expect: raises `ValueError`; `current_view()` still `[u1,a1,K.id]` (still folded).
  Rationale: An unknown id names no active compression → inactive → ValueError, and
             rejection must not mutate the view.

C111. Expanding a non-compression node id raises ValueError
  Setup:  Line `[u1,a1,u2,a2]`; commit → view `[u1,a1,K]`.
  Action: `expand_compression(a1.id)`  (a plain assistant node still in the view).
  Expect: raises `ValueError`; `current_view()` still `[u1,a1,K.id]` (still folded).
  Rationale: Only a compression node can be expanded; a non-compression id is
             inactive-by-type → ValueError, no mutation.

C112. Streaming guard — expand rejected while a turn is live, no mutation
  Setup:  Line `[u1,a1,u2,a2]`; commit → K. Kick off a new turn with a blocking
          provider and pull one token so `core.streaming` is True.
  Action: `expand_compression(K.id)` while the stream is live.
  Expect: raises `ValueError`; after closing the stream, K is still folded — K
          appears in `current_view()` and its children (u2, a2) do not. (The live
          turn's u3/a3 are appended by `submit()` and are incidental; the invariant
          under test is that the rejected expand restored no children.)
  Rationale: Compression ops must refuse to mutate mid-stream to avoid racing an
             in-flight turn; rejection is a no-op.

C113. Successful expand does not itself set `core.streaming`
  Setup:  Line `[u1,a1,u2,a2]`; commit → K (no turn in flight).
  Action: `expand_compression(K.id)`.
  Expect: returns `None`; `core.streaming is False` before and after.
  Rationale: Expand is pure/deterministic domain logic with no network; it neither
             requires nor sets streaming state.

C114. `Node.expand` factory builds a well-formed expand event node
  Setup:  Call `Node.expand(target_id="k-123", anchor_id="leaf-9", conversation_id="conv-1")`.
  Action: inspect the returned node.
  Expect: `role == "expand"`; `node_type == "expand"`; `content == ""`;
          `prev_id is None`; `compressed_into is None`;
          `conversation_id == "conv-1"`; `meta["target"] == "k-123"`;
          `meta["anchor"] == "leaf-9"`; `goes_to_model() is False`;
          `id` is a non-empty string.
  Rationale: The docstring fixes every field: an event (not content) node off the
             prev_id line that never reaches the model, carrying canonical
             target/anchor meta keys.

C115. `Node.expand` tolerates a None anchor
  Setup:  Call `Node.expand(target_id="k-123", anchor_id=None, conversation_id="conv-1")`.
  Action: inspect the returned node.
  Expect: `meta["anchor"] is None`; `meta["target"] == "k-123"`;
          `node_type == "expand"`; `goes_to_model() is False`.
  Rationale: `anchor_id` is typed `str | None`; a None anchor must be recorded
             verbatim (forward-compat, ignored today) without error.

C116. `Node.expand` gives distinct ids to distinct events
  Setup:  Two calls `Node.expand("k","a","c")`.
  Action: compare their ids.
  Expect: the two `id`s differ (auto uuid hex).
  Rationale: Each expand is a distinct event node and must be independently
             addressable.

---

## Ambiguities assumed past (flag for human)

- **A1 — restored child `compressed_into` accessor (C105).** The intent says the
  child's `compressed_into` is cleared. There is no stated public accessor for a
  node's `compressed_into` once it's back in the view. C105's test asserts the
  *observable* consequence (children reappear individually, no K node) and treats
  `compressed_into` as observable only if `current_view()` returns the actual node
  objects. If it returns copies/projections, the test still holds via the "children
  reappear, no compression node" assertion. Flagged in case a stricter field check
  is desired and a public accessor exists.
- **A2 — E node direct field assertions (C114/C115).** Per the task, E's fields are
  verified through the `Node.expand` factory directly (pure domain object, no private
  core access) rather than by fishing E out of `core._graph`. The end-to-end presence
  of E after `expand_compression` is verified only via its persisted *effect* (C106).
  If a public "all nodes" accessor is later added, C106 could additionally assert
  E's `node_type`/`meta` on the reloaded graph.
- **A3 — return type of `expand_compression`.** Signature says `-> None`; C113
  asserts the return is `None`. If a future revision returns the E node, update C113.
