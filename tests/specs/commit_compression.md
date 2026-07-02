# Behavioral contract — `ConversationCore.commit_compression` (+ `current_view` folding)

Numbered from **C91** to avoid colliding with the existing C1–C90 in the
conversation module. Derived purely from the stated intent (PRD task + ADR-0016),
not from any implementation.

Domain shorthand: a "line" is the active conversation built by `submit`/`stream`;
its last node is the **tip** (active leaf). `commit_compression(start, end, summary,
prompt="")` folds the contiguous run `start..end` into a single **compression node K**.

---

## Happy path

### C91. Tip commit folds a contiguous suffix into one K
Given: a line `[u1, a1, u2, a2]` (tip = `a2`), then
`commit_compression(u2.id, a2.id, summary, prompt)`.
Expect: `current_view()` becomes `[u1, a1, K]` — exactly one node fewer per folded
child collapse, with a single new compression node in the range's slot. `u2` and `a2`
no longer appear in the view; `K` occupies their position (last). Return value is `K`.
Rationale: intent — K appears in place of the folded range; folded children leave the
view; the preceding nodes still precede K.

### C92. K carries the correct compression fields
Given: after the C91 commit with `summary="..."` and `prompt="..."`.
Expect: the returned `K` (and the `K` in `current_view()`) has `role == "compression"`,
`node_type == "compression"`, `content == summary`, `meta["prompt"] == prompt`, and
`meta["range"] == [u2.id, a2.id]` (the folded ids in view order, oldest-first).
Rationale: intent — K's shape and its ordered range record.

### C93. `prompt` defaults to the empty string
Given: `commit_compression(start, end, summary)` with no `prompt` argument.
Expect: the returned `K` has `meta["prompt"] == ""`.
Rationale: intent — `prompt` defaults to `""`.

### C94. Single-node fold (start == end == tip)
Given: line `[u1, a1, u2, a2]`, `commit_compression(a2.id, a2.id, summary)`.
Expect: `current_view()` becomes `[u1, a1, u2, K]`; `K.meta["range"] == [a2.id]`; only
`a2` is folded. Return value is `K`.
Rationale: intent — "if start==end==tip, a single node folds into K."

### C95. Nodes before the range are unchanged and still precede K
Given: line `[u1, a1, u2, a2]`, commit `(u2.id, a2.id, ...)`.
Expect: `current_view()[:-1]` is exactly `[u1, a1]` — same ids, same order, same
`content`/`role`/`node_type` as before the commit; K is appended after them.
Rationale: intent — the prefix outside the range is untouched.

---

## Non-destructive persistence

### C96. Folded children are preserved in storage (not deleted)
Given: after committing `(u2.id, a2.id, ...)`.
Expect: the folded nodes `u2` and `a2` are NOT removed from storage — reloading the
conversation into a fresh core (same repo) still yields a projected view containing K
(children folded), i.e. the commit did not require deleting the children to remove them
from the view. (Observable proxy: the reload in C97 reproduces the identical view,
which is only possible if K + `compressed_into` pointers persisted rather than the
children being destroyed.)
Rationale: intent — non-destructive; children remain in storage.

### C97. Save → reload round-trip reproduces the identical view
Given: commit `(u2.id, a2.id, summary, prompt)`; then build a second core on the same
repo, `setup()`, `resume_conversation(conversation_id)`.
Expect: `core2.current_view()` node ids and `node_type`s equal `core.current_view()`'s —
`[u1, a1, K]` with the last node being a `"compression"` node whose `content == summary`,
`meta["prompt"] == prompt`, and `meta["range"] == [u2.id, a2.id]`.
Rationale: intent — K and the `compressed_into` pointers round-trip through storage.

---

## Rejections — each raises `ValueError` BEFORE any mutation

For every rejection below, additionally: `current_view()` is unchanged (same ids/order)
and no node in the view has `node_type == "compression"` that wasn't there before
(no K created), and nothing new is persisted.

### C98. Tip guard — end not at the tip is rejected
Given: line `[u1, a1, u2, a2]`, `commit_compression(u1.id, a1.id, ...)` (end = `a1`,
mid-conversation, not the tip).
Expect: raises `ValueError`; view still `[u1, a1, u2, a2]`; no compression node exists.
Rationale: intent — in this phase only a range ending exactly at the tip may compress.

### C99. Flat guard — a compression node inside the range is rejected
Given: first commit `(u2.id, a2.id, ...)` → view `[u1, a1, K]` (tip = K). Then
`commit_compression(u1.id, K.id, ...)` — the range now contains the existing
compression node K.
Expect: raises `ValueError`; view still `[u1, a1, K]`; no second compression node
appears (exactly one compression node — the original K — remains).
Rationale: intent — you may not compress a range that already contains a compression.

### C100. Streaming guard — commit during a live stream is rejected
Given: a turn is actively streaming (`core.streaming` is True — one token yielded, the
provider blocked). `commit_compression(...)` for an otherwise-valid tip range.
Expect: raises `ValueError`; no compression node is created (checked after closing the
stream); the view is unchanged.
Rationale: intent (H2 invariant) — no commit may mutate the graph mid-turn.

### C101. Unknown start_id is rejected
Given: `commit_compression("does-not-exist", a2.id, ...)`.
Expect: raises `ValueError`; view unchanged; no compression node created.
Rationale: intent — both ids must be present in `current_view()`.

### C102. Unknown end_id is rejected
Given: `commit_compression(u2.id, "does-not-exist", ...)`.
Expect: raises `ValueError`; view unchanged; no compression node created.
Rationale: intent — both ids must be present in `current_view()`.

### C103. Reversed order (start after end) is rejected
Given: line `[u1, a1, u2, a2]`, `commit_compression(a2.id, u2.id, ...)` — start ordered
after end.
Expect: raises `ValueError`; view unchanged; no compression node created.
Rationale: intent — start_id must be at or before end_id (a forward slice).

---

## Assumptions / ambiguities resolved

1. **`setup()` vs `__init__`**: the sample flow calls `core.setup()` after construction;
   I treat that as required initialization and always call it. (The interface lists only
   `__init__`; the harness instructions supply `setup`/`submit`/`stream`/`resume_conversation`.)
2. **"range in order" ordering**: I assume `meta["range"]` is oldest-first (view order,
   root→tip), matching `current_view()`'s "root-first" projection and the phrase "folded
   nodes in view order."
3. **C96 observability**: I cannot inspect storage directly through the given interface,
   so "children preserved" is verified via the reload round-trip (C97) — a destructive
   delete could not reproduce the same view after resume. This is the strongest
   interface-level oracle available.
4. **Reversed-order isolation**: with the tip guard also in force, a reversed slice whose
   end is not the tip trips two rules at once. The contract only asserts `ValueError` is
   raised (the intent groups "reversed" under invalid slice); I do not assert *which*
   guard fired.
5. **"no node in the slice is a compression"**: C99 constructs the case by first creating
   a real K at the tip, then including it in a new range — the only way to get a
   compression node into a candidate slice given the tip-only rule.
