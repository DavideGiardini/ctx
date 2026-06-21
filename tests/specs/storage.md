# Behavioral contract — `ctx/core/storage.py` :: `ConversationRepository`

The oracle of record for the `StoragePort` implementation
(`init` / `save` / `load` / `list` / `get_last`). Authored code-blind from intent
(see `.claude/skills/write-tests`), then human-adjudicated. Tests in
`tests/test_storage.py` cite these item ids. **When behavior changes, update this
contract first**, then the tests.

`ConversationRepository` is durable persistence for conversations and their `Node`s,
backed by SQLite. The interface is small while the implementation hides all SQL
mechanics, connection lifecycle, and JSON serialization. All "Expect" clauses describe
observable behavior (returned `Node`s / dicts / ids, counts, ordering, field equality),
never storage format.

Tests use the `repo` fixture (a temp-**file** SQLite DB, already `init()`-ed) and the
`make_node` factory. Tests must **not** construct a `":memory:"` repo — the repository
opens a fresh connection per method, so an in-memory DB would be private per call and
lose all state between `init()`/`save()`/`load()`.

Unless an item says otherwise, every `Node` passed to `save(cid, …)` has
`conversation_id == cid` (the normal usage; the `make_node` default `conversation_id`
must be overridden to match the save id). Round-trip equality is dataclass `==` over all
`Node` fields, including `id` (ids are preserved, not regenerated). *(resolves A5, A6)*

## Contract

### init()

**C1. `init()` is idempotent and non-destructive.**
Given the `repo` fixture (already `init()`-ed) holding a saved conversation with nodes →
calling `init()` one or more further times raises nothing, and the conversation is still
loadable with the same nodes and still reported by `list()` (no data wiped, no error).

**C2. After `init()`, save/load works.**
Given an `init()`-ed `repo` → a `save()` followed by `load()` of that conversation
succeeds and returns the saved nodes (the schema exists and is usable).

### save() — create / update semantics

**C3. Saving a new conversation creates it.**
Given an empty repo and `save("conv-alpha", "Project kickoff", nodes)` with ≥1
persistable node → `load("conv-alpha")` returns those nodes; `list()` contains exactly
one dict with `id=="conv-alpha"` and `title=="Project kickoff"`; `get_last()=="conv-alpha"`.

**C4. Re-saving an existing conversation overwrites its title in place (no duplicate).**
*(adjudicated: a later save with a changed title overwrites — confirmed product decision.)*
Given `"conv-alpha"` saved with title `"Draft"` (≥1 node), then re-saved with the same id
and title `"Final"` → `list()` contains exactly **one** dict with `id=="conv-alpha"`, and
its `title=="Final"`. Title is overwritten, not appended; no duplicate conversation.

**C5. Re-saving advances update-recency.**
Given `"conv-a"` then `"conv-b"` saved (each with nodes) so `get_last()=="conv-b"`, then
`"conv-a"` re-saved → `get_last()=="conv-a"` and in `list()` the `"conv-a"` dict precedes
the `"conv-b"` dict (most-recently-updated first).

**C6. Re-saving REPLACES nodes (no accumulation / duplication).**
Given `"conv-alpha"` saved with 3 distinct persistable nodes, then re-saved with a
different list of 2 distinct persistable nodes → `load("conv-alpha")` returns exactly the
2 second-save nodes (count 2) and none of the first-save nodes. The first set is fully
superseded, not merged.

**C7. Re-saving with an empty node list empties the conversation's nodes.**
Given `"conv-alpha"` saved with several nodes, then re-saved with `nodes==[]` →
`load("conv-alpha")` returns `[]` (the node set is replaced by nothing). (Listing
consequences: see C18.)

### save() — persistability filter

**C8. Nodes with empty `conversation_id` are not persisted.**
Given a save whose node list is solely nodes built with `conversation_id==""` (transient
system notices) → `load(id)` returns `[]`; none of those nodes were stored.

**C9. A mixed list stores only the persistable nodes, in their relative order.**
Given a save whose node list interleaves persistable nodes (`conversation_id` set) and
non-persistable ones (`conversation_id==""`), e.g. `[p1, empty, p2, empty]` → `load(id)`
returns only `p1, p2`: count equals the number of persistable inputs, no returned node has
`conversation_id==""`, and their relative order matches the input (see C12).

### Round-trip fidelity

**C10. A persisted node round-trips with every field preserved.**
Given a node with concrete non-default values for `id`, `conversation_id`, `role`
(e.g. `"assistant"`), `content` (non-trivial string), `node_type` (e.g. `"tool_call"`),
and a non-empty `meta` → after save + load, the loaded `Node` equals the input on all of
`id`, `conversation_id`, `role`, `content`, `node_type`, `meta` (dataclass `==`).

**C11. `meta` survives serialization including nested structures.**
Given a node whose `meta` nests dicts, lists, strings, ints, floats, booleans, and `None`
(e.g. `{"tokens": 42, "tags": ["a","b"], "nested": {"ok": True, "ratio": 0.5, "x": None}}`)
→ after save + load, the loaded `meta` equals the original exactly: structure, types, and
values preserved (bools stay bools, `None` stays `None`, lists stay lists, ints stay ints).

### load() — ordering and isolation

**C12. `load()` returns nodes in original insertion order.** *(adjudicated: insertion
order is a guaranteed part of the contract — callers may rely on a conversation replaying
in the order its nodes were appended.)*
Given a conversation saved with persistable nodes in a known order (e.g. content
`c1, c2, c3, c4`) → `load(id)` returns them in that same order (output element i
corresponds to input element i).

**C13. `load()` of an unknown conversation returns `[]`.**
Given a repo where `"never-saved"` was never saved → `load("never-saved")` returns `[]`
(empty list, not `None`, no error).

**C14. `load()` is isolated per conversation.**
Given two conversations `"conv-a"` (nodes A) and `"conv-b"` (nodes B) saved →
`load("conv-a")` returns exactly nodes A (none of B) and `load("conv-b")` returns exactly
nodes B (none of A).

### list()

**C15. `list()` returns one correctly-shaped dict per conversation.**
Given two conversations saved (each with nodes) → `list()` has length 2; each element is a
dict whose keys are exactly `{"id", "title", "updated_at"}`; the set of `id` values equals
the set of saved ids; each `title` matches the last title saved for that id.

**C16. `list()` is ordered most-recently-updated first.**
Given conversations saved in order `"first"`, `"second"`, `"third"` (each a distinct update
event, each with nodes) → the `id` order in `list()` is `["third","second","first"]`.

**C17. `list()` reflects re-ordering after an update.**
Given `"a"`, `"b"`, `"c"` saved in that order (initial list order `c, b, a`), then `"a"`
re-saved → `"a"` is now first: `list()` ids are `["a","c","b"]`.

**C18. A conversation with no persisted nodes is not listed. — CONTRACT VIOLATION (BUG-1),
test quarantined `xfail(strict=True)`.**
*(adjudicated A4: a conversation is a first-class entity only while it has ≥1 persisted
node; an empty/all-filtered save must not appear in `list()` or be returned by
`get_last()`.)* Given a `save(id, title, nodes)` where the save results in zero persisted
nodes — either `nodes==[]` or every node has `conversation_id==""` — then the conversation
must NOT appear in `list()` and must not be returned by `get_last()` (while `load(id)` is
`[]`, per C7/C8). The current implementation inserts the conversation row regardless of
nodes, so the test fails and is quarantined as `xfail(strict)` — see
`tests/specs/FOUND-BUGS.md` (BUG-1). Tests assert the intended behavior, not the current
behavior.

**C19. `list()` on an empty repo returns `[]`.**
Given an empty repo → `list()` returns `[]`.

### get_last()

**C20. `get_last()` returns the most-recently-updated conversation id.**
Given `"old"` then `"new"` saved (each with nodes) → `get_last()=="new"`.

**C21. `get_last()` follows update recency, not creation order.**
Given `"a"` then `"b"` saved, then `"a"` re-saved → `get_last()=="a"`.

**C22. `get_last()` returns `None` on an empty repo.**
Given an empty repo → `get_last()` returns `None`.

**C23. `get_last()` agrees with `list()`'s head.**
Given any repo with ≥1 listed conversation → `get_last() == list()[0]["id"]`.

### Strict recency ordering

**C24. Same-instant saves are still ordered most-recently-saved-first. — CONTRACT
VIOLATION (BUG-2), test quarantined `xfail(strict=True)`.** *(adjudicated A1/A2: recency
ordering must be strict even when two saves land at the same wall-clock instant; the
most-recently-saved conversation comes first.)*
With the repository's update clock frozen so two saves receive an identical `updated_at`,
save `"a"` then `"b"` → intent requires `get_last()=="b"` and `"b"` to precede `"a"` in
`list()`. The current implementation orders by `updated_at` alone with no tiebreak, so
same-instant order is undefined; the test fails and is quarantined as `xfail(strict)` —
see `tests/specs/FOUND-BUGS.md` (BUG-2). (To freeze the clock: the repository stamps `updated_at`
via `datetime.now(UTC)`, where `datetime` is imported into module `ctx.core.storage`;
monkeypatch `ctx.core.storage.datetime` so `now(UTC)` returns a fixed instant for both
saves. This is the dependency seam — the *expected value* comes from intent, not the code.)

## Adjudication notes
- **A3 (empty/duplicate title):** `title` is a `str`; empty string is valid and stored
  verbatim; duplicate titles across conversations are allowed. Not separately asserted —
  C4/C15 cover verbatim title storage.
- **A4 (conversation with no nodes):** resolved as "listed only if it has ≥1 persisted
  node" → C18 (currently a bug; test left failing).
- **A5 (node equality):** dataclass `==` over all fields including `id`; ids preserved,
  not regenerated → C10.
- **A6 (node `conversation_id` vs save id):** normal usage aligns them; mismatch is not a
  product requirement and is out of scope (tests set node `conversation_id` to match).
- **A7 (duplicate node ids in one save):** `id` is a primary key; not a product scenario,
  out of scope.
- **A1/A2 (ordering ties):** resolved as "strict ordering required" → C24 (currently a
  bug; test left failing). Distinct-save ordering (C5/C16/C17/C20/C21) uses naturally
  distinct timestamps — real back-to-back saves are milliseconds apart, far above the
  microsecond timestamp resolution, so those tests are not flaky.

## Contract violations found (quarantined `xfail(strict=True)`, logged in FOUND-BUGS.md)
- **BUG-1 (C18):** `save()` creates/keeps a conversation row even when it has zero
  persisted nodes, so empty/all-filtered conversations leak into `list()`/`get_last()`.
- **BUG-2 (C24):** `list()`/`get_last()` order by `updated_at` with no tiebreak, so two
  saves at the same instant have undefined order.
Production code is untouched; both are deferred to a separate, human-reviewed fix per the
maintainer's decision. `strict=True` means each test XPASSes (fails) when its bug is fixed,
forcing removal of the marker.

## Mutation testing (mutmut)
Focused run: `bash scripts/mutate.sh run 'ctx.core.storage.*'`.
**115 mutants, 90 killed, 25 survivors — all 25 equivalent.** Every behavior-changing
mutant is killed (spot-verified: `now=None`, `conn=None`, and SQL-string→`None` all
killed). The 25 survivors fall into two documented-equivalent classes:

- **24 SQL keyword/identifier case-flips** (e.g. `SELECT`→`select`, `PRAGMA journal_mode=WAL`
  →`pragma journal_mode=wal`, uppercased table/column identifiers in every statement of
  `_connect`/`save`/`load`/`list`/`get_last`). SQLite treats both SQL keywords and
  identifiers case-insensitively, so these mutations cannot change behavior — no assertion
  can distinguish them. Genuinely equivalent.
- **1 timezone mutant** — `save_2`: `datetime.now(UTC)` → `datetime.now(None)`, which makes
  the stored `updated_at` local-naive instead of UTC-aware. The contract pins only *relative*
  update-recency ordering (C5/C16/C17/C20/C21), which is preserved under either clock, and
  deliberately does **not** assert the timestamp's zone or string format (asserting that would
  couple the tests to an implementation detail — same stance as `context.py`'s logger-arg
  survivors). Equivalent *with respect to this contract*. Re-triage only if `updated_at`'s
  zone/format ever becomes contractual (e.g. surfaced to the user or compared across
  processes).

No survivor stems from the C18/C24 quarantined-bug lines: those lines are also exercised by
passing tests (C3, C16, C20…), so their behavior-changing mutants are killed; only the
case-flip mutants on them survive as equivalent.
