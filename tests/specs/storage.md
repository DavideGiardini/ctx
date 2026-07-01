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

### Cross-conversation isolation & combined update

**C25. Re-saving one conversation does not disturb another's nodes.**
*(The node-replacement on save (C6) is scoped to the saved conversation; a save must never
delete or alter nodes belonging to a different conversation.)*
Given `"conv-a"` (nodes A) and `"conv-b"` (nodes B) both saved, then `"conv-a"` re-saved
with a new node set A2 → `load("conv-b")` still returns exactly nodes B (unchanged), and
`load("conv-a")` returns exactly A2. (Guards against an unscoped node-delete.)

**C26. A single re-save updates title, recency, and nodes together.**
Given `"conv-x"` saved with title `"T1"` and nodes N1, then re-saved with title `"T2"` and a
different node set N2 → afterward, in one consistent state: `list()` contains exactly one
`"conv-x"` dict whose `title=="T2"`; `"conv-x"` is at the head of `list()` / is `get_last()`
(most-recent); and `load("conv-x")` returns exactly N2 (N1 fully superseded). (The three
effects of an update co-occur; a mutant updating only one is caught.)

**C27. An empty-string title is stored and returned verbatim.** *(resolves A3 observably.)*
Given a conversation saved with `title==""` and ≥1 persistable node → `list()` contains that
conversation with `title==""` (the empty string, not a substitute), and re-saving it later
with a non-empty title overwrites it to that value.

## Append-only conversation graph (ADR-0016)

New persistence behaviors for the append-only node graph: `save()` now stores the FULL node
set (every line + compression children, not just the active view) including each node's
`prev_id`/`compressed_into` edges, plus the conversation's `active_leaf_id` tip; `get_active_leaf`
reads that tip back; and `init()` migrates a pre-graph flat DB in place (chaining nodes into the
degenerate single path by insertion/rowid order). All Expect clauses are observable through
`load()` (asserting on returned Nodes' `prev_id`/`compressed_into`), `get_active_leaf()`, `list()`,
`get_last()` — never storage format.

**C28. save persists `prev_id` verbatim and round-trips.**
Given a conversation with two nodes `n1` (`prev_id=None`) and `n2` (`prev_id=n1.id`) saved together
→ `load(cid)` returns two Nodes; the one with `id==n1.id` has `prev_id is None`, the one with
`id==n2.id` has `prev_id == n1.id`; each loaded Node equals its saved Node (dataclass `==`, including
`prev_id` and `id`). The graph topology (the `prev_id` edges) survives save/load.

**C29. save persists `compressed_into` verbatim and round-trips.**
Given a summary node `s` and a folded child `c` with `c.compressed_into = s.id` saved together →
`load(cid)` returns both; the node `id==c.id` has `compressed_into == s.id`, the node `id==s.id` has
`compressed_into is None`; loaded Nodes equal saved Nodes (dataclass `==` including `compressed_into`).

**C30. save persists the FULL node set — abandoned tails survive.**
Given a node set with a branch that is NOT the active tip — `n1` (root), `n2` (`prev_id=n1.id`), and
`n3` (`prev_id=n1.id`, an abandoned sibling) — saved with `active_leaf_id=n2.id` → `load(cid)` returns
all three nodes (by id); the abandoned `n3` is still retrievable with `prev_id == n1.id`. No node is
dropped merely because it is off the active line (non-destructive graph).

**C31. `active_leaf_id` is stored and retrieved via `get_active_leaf`.**
Given `save(cid, title, nodes, active_leaf_id=X)` where `X` is one of the saved node ids →
`get_active_leaf(cid) == X`.

**C32. `active_leaf_id` need not be the last node (rewind case).**
Given nodes `n1,n2,n3` saved in that insertion order but with `active_leaf_id=n2.id` (a middle node —
the tip after a rewind) → `get_active_leaf(cid) == n2.id` (NOT `n3.id`), and `load(cid)` still returns
all three in insertion order `[n1, n2, n3]`. The stored tip is exactly the id the caller passed,
independent of which node was created last.

**C33. `active_leaf_id` defaults to `None` when the kwarg is omitted.**
Given `save(cid, title, nodes)` with nodes present but WITHOUT the `active_leaf_id` kwarg →
`get_active_leaf(cid) is None` (the tip is recorded only when explicitly provided).

**C34. `get_active_leaf` returns `None` for an unknown conversation.**
Given no conversation ever saved under `"does-not-exist"` → `get_active_leaf("does-not-exist") is None`
(symmetric with `get_model`).

**C35. `get_active_leaf` reflects the most recent save (overwrite).**
Given `save(cid, ..., active_leaf_id=n2.id)` then a later `save(cid, ..., active_leaf_id=n3.id)` for
the same id → `get_active_leaf(cid) == n3.id`.

**C36. Re-save with `active_leaf_id=None` clears the previously stored tip.** *(adjudicated ambiguity 1:
"reflects the most recent save" applies to `None` too — a deliberately-unset tip overwrites a prior one.)*
Given `save(cid, ..., active_leaf_id=n2.id)` then a later `save(cid, ..., active_leaf_id=None)` (nodes
still present) → `get_active_leaf(cid) is None` after the second save.

### Migration of a pre-graph flat DB on init()
A "pre-graph" legacy DB is built directly via `sqlite3` (as the existing `_PRE_MODEL_SCHEMA` tests do):
`conversations` has a `model` column but NO `active_leaf_id`; `nodes` has NO `prev_id`/`compressed_into`.
Rows are inserted in a known order, a `ConversationRepository` is pointed at that file, and `init()` is
called (which must migrate in place).

**C37. Migration chains a multi-node conversation into a single `prev_id` line by insertion order.**
Given a legacy conversation with three nodes inserted in order `a, b, c` → after `init()`, `load(cid)`
returns `[a, b, c]` in insertion order with `a.prev_id is None` (root), `b.prev_id == a.id`,
`c.prev_id == b.id`. Content preserved.

**C38. Migration sets `active_leaf_id` to the last node (by insertion order).**
Given the migrated multi-node conversation from C37 → `get_active_leaf(cid) == c.id` (the last-inserted
node is the tip of the degenerate linear conversation).

**C39. Migration preserves existing content/order, loses no rows, and leaves `compressed_into` NULL.**
Given a legacy conversation of several nodes with distinct id/role/content/node_type/meta → after
`init()`, `load(cid)` returns the same count in the same insertion order with those fields unchanged;
only `prev_id`/`compressed_into` are newly populated, and every migrated node has `compressed_into is None`
(a pre-graph DB had no folds).

**C40. Migration edge case — single-node conversation.**
Given a legacy conversation containing exactly one node `x` → after `init()`, `load(cid)` returns `[x]`
with `x.prev_id is None` (its own root) and `get_active_leaf(cid) == x.id` (its own tip).

**C41. Migration edge case — zero-node conversation.**
Given a legacy conversation ROW with no node rows → `init()` completes without error; `load(cid)` returns
`[]`; `get_active_leaf(cid) is None` (no last node to point at); the conversation still appears in `list()`
(the row is not lost).

**C42. Migration is idempotent across repeated `init()`.**
Given a legacy multi-node conversation, `init()` once (state captured via `load` + `get_active_leaf`), then
`init()` a second and third time → after each extra call, `load(cid)` and `get_active_leaf(cid)` are
identical to the post-first-init state (same nodes, order, `prev_id` chain, tip); no error, no duplicate
columns.

**C43. The rowid-chaining backfill runs EXACTLY ONCE — a post-migration NULL-tip conversation is not
re-chained.** *(adjudicated ambiguity 2: the "already migrated" discriminator is schema-level — once the
graph columns exist the backfill never re-runs; the probe is a sibling topology a wrongful re-run would
rewrite. This item must start from a GENUINELY migrated legacy DB so it proves the backfill already ran
once and will not run again — not merely that a fresh-schema DB never migrates.)*
Given a legacy DB migrated by a first `init()`, then a NEW conversation saved normally with a
non-linear topology and `active_leaf_id=None` while nodes are present — `n1` (root), `n2` (`prev_id=n1.id`),
`n3` (`prev_id=n1.id`, a sibling, NOT chained after `n2`) — then `init()` is called again → after the extra
`init()`, `load(cid)` still shows `n3.prev_id == n1.id` (the sibling edge is unchanged, NOT rewritten to
`n2.id` as a rowid re-chain would produce) and `get_active_leaf(cid) is None` (not backfilled to the last
node). A conversation saved after migration with a NULL tip is never re-chained by a later `init()`.

**C44. After a one-time migration the repo is a normal graph store (migrated + fresh edges coexist).**
*(adjudicated: `save()` persists the FULL node set it is given and replaces the prior set (C6/C25) — it
does NOT append. So "extend a migrated conversation" means the caller loads the migrated nodes, adds the
new one, and re-saves the whole list. A save of only the new node would correctly delete the migrated ones.)*
Given a DB migrated from a pre-graph legacy DB (nodes `a→b→c` chained by migration): `load(cid)` the migrated
nodes, append a NEW node whose `prev_id` is the migrated tip (`c.id`), and `save(cid, title, [a, b, c, new],
active_leaf_id=new.id)` (the full set) → `load(cid)` returns all four nodes with the migration's `prev_id`
chain intact (`a.prev_id is None`, `b.prev_id == a.id`, `c.prev_id == b.id`) plus the new node with
`prev_id == c.id`, and `get_active_leaf(cid) == new.id`. Migrated and freshly-saved edges coexist.

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
- **A8 (graph ambiguity 1 — clear-on-None):** `save(active_leaf_id=None)` on an existing
  conversation overwrites (clears) a previously stored tip → C36. Literal "most recent
  save" reading; the deliberately-unset tip wins.
- **A9 (graph ambiguity 2 — "runs exactly once" discriminator):** the migration/backfill is
  gated on a schema-level marker (the graph columns being absent), so once they exist the
  rowid-chaining backfill never re-runs — regardless of any conversation's tip being NULL or
  its topology being a branch. C43 probes this with a sibling edge (`n3.prev_id==n1.id`) that a
  wrongful re-run would rewrite to `n2.id`, and requires a genuinely migrated legacy DB so the
  "already ran once" precondition is real. Save preserves any caller-supplied `prev_id`
  (including a branch) verbatim (consistent with C30).
- **A10 (graph ambiguity 3 — node-less row listable):** a migrated node-less conversation row
  survives and appears in `list()` (C41); "no rows lost".
- **A11 (graph ambiguity 4 — migrated `compressed_into`):** all migrated nodes get
  `compressed_into is None` (a pre-graph DB had no folds) → C39.
- **A12 (graph ambiguity 5 — insertion==rowid order):** post-migration setups (C43/C44) rely on
  the existing guarantee (C12) that nodes saved in list order load back in that order, so the
  "sibling vs chain" observable in C43 is unconfounded.

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
**After the ADR-0016 graph additions (C28–C44): 230 mutants, ~176 killed, 53 survived + 1
"no tests" — every survivor documented-equivalent, none behavioral.** The module grew (the
`_migrate`/`_backfill_graph` migration, `get_active_leaf`, and the `prev_id`/`compressed_into`/
`active_leaf_id` columns in `save`/`load`), so there are more mutants than the pre-graph baseline
(115), but the survivor *classes* are unchanged:

- **SQL keyword/identifier case-flips (the bulk)** — e.g. `SELECT`→`select`, `PRAGMA
  table_info(...)`→`pragma table_info(...)`, `ALTER TABLE … ADD COLUMN`→lowercase, `UPDATE
  nodes SET prev_id`→lowercase, uppercased identifiers — across `_connect`/`_migrate`/
  `_backfill_graph`/`save`/`load`/`get_model`/`get_active_leaf`/`list`/`get_last`. SQLite treats
  both keywords and identifiers case-insensitively, so no assertion can distinguish them.
  Genuinely equivalent.
- **1 timezone mutant** — `save`: `datetime.now(UTC)`→`datetime.now(None)` (local-naive vs
  UTC-aware). The contract pins only *relative* recency ordering (preserved under either clock)
  and deliberately does not assert the timestamp's zone/format. Equivalent w.r.t. this contract.
- **1 "no tests"** — `StoragePort.save`: the `Protocol` method body is `...` (an abstract stub),
  not executable code; expected non-target.

Spot-verified that behavior-changing mutants in the NEW graph code are KILLED: the
`prev_id`/`compressed_into`/`active_leaf_id` SQL *value bindings* and the migration's rowid-chaining
logic have no surviving behavioral mutant (only case-flips survive on those lines) — C28–C44 pin them.
No survivor stems from a weak test or a real bug.
