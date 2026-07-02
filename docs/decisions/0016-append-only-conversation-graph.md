# 0016 — Conversation state is an append-only node graph (no op log, no soft-delete)

**Status:** Accepted (governs Sprint 2; not yet implemented)

## Context

Today a conversation is a flat, ordered `list[Node]` persisted by a full-replace
`save()` (`ctx/core/storage.py` — DELETE-all-then-INSERT), and the `nodes` table has
no edges. The Product Concept requires four capabilities that this model cannot carry:
compression (§4 — collapse a range into one node the model sees instead), branching &
sub-chats (§5), import snapshots & staleness (§3.3), and reversibility with "nothing is
truly deleted" (§4.3). ADR-0006 #2 anticipated the horizon as *soft-delete + a node
graph + an append-only operation log*.

This ADR was produced during sprint planning (see `docs/Sprint Roadmap.md`, Sprint 2),
after working through what those features actually demand. The central question was the
**source of truth** for conversation state and how to represent the passage of
operations over time — because it is the most expensive thing to change later and it
shapes compression (S3), branching (S4), and snapshots (S5).

## Decision

Conversation state is an **append-only, non-destructive node graph** — git-like: the
past is immutable, the conversation only ever changes *going forward*, and divergence
forks a branch. **This single structure IS the history.** There is no separate undo
subsystem, no operation log, and no event-sourcing.

### Schema (three fields, nothing more)
- `nodes.prev_id TEXT NULL` — predecessor on the line; NULL = root. **Siblings (same
  `prev_id`) are branches.** Rewind moves the active tip; diverging from a tip creates a
  sibling.
- `nodes.compressed_into TEXT NULL` — if set, this node is a child subsumed by that
  compression node: it leaves the active line but is **preserved** (reachable via
  deep-dive / `expand`).
- `conversations.active_leaf_id TEXT NULL` — the current tip; walking `prev_id` from it
  to root yields the active line. Today's linear conversation is the degenerate
  single-path case (tip = last node).

### The invariant this buys (the crux)
The ancestor path of any node is a faithful, permanent record of exactly what that node
saw when it was generated — for free, with no extra bookkeeping. The structure *is* the
record. Every downstream decision below follows from protecting this invariant.

### Reversibility = navigate or fork, not undo
- *Edit a past message*, or *refresh an import to new content* → **fork a branch** (turns
  after it depended on the old text; a new line is the only coherent outcome). The old
  line is preserved.
- *Delete a middle message* → identical to **rewind**: fork from the node before it.
  There is no "excise a node but keep its dependent tail" — that is incoherent.
- *Delete the last n messages* → **rewind** the active tip.
- *Compress a range* / *`expand` it back* → **forward, non-destructive**, in place; the
  children are always preserved under the compression node, so `expand` needs no log
  (it forks a branch only if the conversation already continued past the compressed node).
- *Delete a whole branch / conversation* → the **only** true row-deletion; permanent, no
  trash for now (trash is a clean future add).

### Persistence & projection
- A `current_view() -> list[Node]` projection (walk the active line, resolving
  compression) lets the UI and `build_context` consume exactly today's shape; the graph
  lives behind that one method. `ConversationCore`'s in-memory state grows from a list to
  the whole graph (all lines + compression children).
- `StoragePort.save` changes to persist the **full node set** (not just the active view);
  `load()` reconstructs the graph. The `SaveCountingStorage` double
  (`tests/test_conversation.py`) must move in lockstep. A `PRAGMA table_info` migration
  (like the existing `_migrate`) chains existing flat DBs by `rowid`, sets
  `active_leaf_id` to the last node, and leaves `compressed_into` NULL.

## Alternatives rejected (do not re-litigate)

1. **Event-sourcing** (the op log is the truth; state is a fold/projection over events).
   Gives history and "nothing deleted" by construction, but it is a large mental-model
   shift for the entire core, every read needs a projection, and it re-stores what the
   graph structure already holds. The append-only graph delivers the same guarantees
   without the machinery.

2. **State + an inverse-undo operation log** (mutable state as truth, a journal recording
   how to invert each op). Rejected because reversibility here is *navigate/rewind/fork*,
   not ctrl+z. Once "undo" is gone, the journal has no job: compression is non-destructive
   (children preserved), branches persist, and the only real deletion is a whole-branch
   hard delete. A log would be bookkeeping kept in sync for nothing.

3. **A mutable per-node `in_context` / "mute" flag** (toggle a node out of context going
   forward, in place, no branch). Rejected: a mutable, time-varying flag **breaks the
   ancestor-path invariant** — a past turn's context could no longer be reconstructed
   without recording the flag's value *at every generation point*, i.e. per-turn temporal
   versioning, which drags back exactly the mutable model this ADR removes. It also risks
   confusing the model (information appearing/vanishing/reappearing across turns) and its
   use case is already served by rewind/branch/compression. If per-node exclusion is ever
   genuinely needed, the only append-only-safe form is a **forward-only exclusion marker**
   placed on the line — never a mutable flag.

## Consequences

- **Revises ADR-0006 #2:** the anticipated soft-delete + operation-log design is not
  adopted; the append-only graph replaces both. (0006 is a Notes ADR and is left intact
  per the supersede-don't-rewrite rule; this ADR is the current decision of record.)
- **No "History & reversibility" sprint.** §4.3 reversibility is inherent to the graph. A
  chronological text `:history` readout was considered and dropped as marginal. The
  spatial *graph-map* visualization is spun out to a separate, lowest-priority,
  beyond-spec sprint (Roadmap S10).
- **Compression (S3)** sets `compressed_into` and extends `build_context`
  (`ctx/core/context.py`, already routing through `Node.goes_to_model()`) so a compressed
  node reaches the model and its children do not; `expand` is the non-destructive inverse.
- **Branching (S4)** is the sibling `prev_id` edges plus active-line switching; per-message
  delete/edit surface here as rewind/fork.
- **Import snapshots (S5)** store immutable content on the context node — consistent with
  the model; re-import forks a branch rather than mutating in place.
- **No `deleted_at`, no `operations` table, no `in_context` column** ever get added for
  these features; a graph field is added only when a feature needs it.

## Amendment #1 — compression model: any-range, immutable events, per-turn context reconstruction

The Decision above described compression as splicing K into the line (`K.prev = A`,
`G.prev = K`). That is correct only for a range at the **tip**. Working through
mid-conversation compression (see `docs/Sprint Roadmap.md` S3 refinement) settled a fuller
model. This amendment is the model of record for compression.

### Any contiguous range is compressible, including the middle
Users can compress **any contiguous range** (per §4.1 "select a range"), not just the tip
— including a range with live assistant turns after it. This is compression's main job
(shrink an old section of a long conversation, keep recent turns verbatim). Non-contiguous
"scattered" selections are not allowed (they would interleave summarized and unsummarized
content and break linear reading).

### Compression is an immutable event with a creation order — not a positional fold
A compression is recorded as an immutable node K that (a) references the contiguous range
it folds (children carry `compressed_into = K`; K sits **off** the `prev_id` line, so it
never reads as a branch sibling) and (b) carries a **creation order** (rowid today; likely
promoted to an explicit `created_seq`/timestamp for robustness and branch-safety). The
`prev_id` transcript chain is **never mutated**.

### Per-turn context is reconstructed by creation order
The rule for building the context of any turn T:

> walk T's ancestors and apply **only the compressions created before T**.

Consequences:
- A turn generated **before** a compression event sees the folded range **in full** (the
  compression is not yet in effect for it). A turn generated **after** sees the summary.
- **Generation** (of a new turn) uses the *current* view = all compressions applied.
- This restores an honest, deterministic ancestor-path invariant *per turn* without any
  mutable state: each compression is an immutable, creation-ordered record; nothing is
  lost; "what did turn T see" is always exactly recomputable. For branches (S4), the rule
  is ancestry **plus** creation order (a compression applies to T iff it is in T's line and
  predates it) — precise branch rule deferred to S4.

### Coherence is mitigated by a default prompt + made safe by reversibility — not guaranteed
Compressing a middle range means a later verbatim turn can sit atop a *summary* of what it
depended on (concern "a": the model may work from a summary while a verbatim turn cites
dropped specifics). This is the same tradeoff automatic summarization makes; we accept it,
mitigated three ways:
1. **A preserve-info default compression prompt** (project/assistant-level, §6.1): the
   one-keystroke path injects *"preserve the facts, decisions, entities, and open threads
   needed for the conversation to continue coherently."* Users may **opt out** via config
   to get full prompt control — and then information loss is the user's responsibility
   ("power over protection"). Tip compression needs no such instruction (no later turn
   depends on it).
2. **Reversibility** — compression is non-destructive and `expand` is a pure toggle, so a
   bad compression is never permanent (expand and re-compress, or rewind/branch to redo).
3. **Preview + edit before commit** (§4.1), shown against the originals in the 3-split
   inspector.

### Concern "b" is solved by a git-diff context view (an on-brand signature feature)
The TUI signals when a response was generated under a context different from the current
one. Today the left detail pane is 3-split for context nodes and full for AI nodes. For an
**AI node whose generation context differs from now** — i.e. some compression created
*after* it folds something in its ancestry — the AI node's left pane gains an extra
(openable) split showing a **git-diff-style view**: *this turn's context as it was at
generation* (left) vs *that same prefix as it stands now* (right, folded). This makes
"what did this response actually see" first-class. Diff is against the turn's own ancestor
prefix (not the whole current transcript). In a heavily compressed conversation many turns
legitimately show this indicator — keep it subtle and config-toggleable.

### Not a reopening of the rejected mute flag
This is consistent with the original Decision's note that per-node exclusion, *if ever
needed, must be a forward-only append-only marker, never a mutable flag*.
Compression-as-immutable-events **is** that marker form: durable, creation-ordered,
lossless, deterministically reconstructable. Mute was rejected as a *mutable flag* of low
value; this is neither.

### Schema unchanged
Still `prev_id` + `compressed_into` + `active_leaf_id`; the only addition is reliance on
**creation order** (rowid, or an explicit `created_seq`/timestamp). The earlier splice
description and the "expand forks if the conversation continued past the node" clause are
retracted — `expand` is a pure, non-destructive toggle at any position.

## Amendment #2 — compression is an *event-node* model; discovery is by enumeration, not pointers

Amendment #1 named `compressed_into`-on-children as *the* mechanism ("children carry
`compressed_into = K`") and said the schema was unchanged bar "reliance on creation order."
Working through Sprint 3b during the S3 grill (2026-07-01) — per-turn reconstruction, `:expand`,
re-compression, and the diff view — showed that a **pointer-following** model cannot carry those
features. This amendment is the model of record for how compressions are stored and resolved.
(Sprint 3a, which never reconstructs history or re-compresses, may keep the simpler pointer-run
resolution; it is the degenerate case of what follows.)

### The problem with pointer-following
`compressed_into` on a child answers only "what does this node fold into *now*." It cannot answer
two questions 3b needs:
1. **History** — "what did turn `T` see," when a compression was created *after* `T` (so `T` saw
   the range verbatim) or a `K` active at `T` was later expanded.
2. **Re-compression** — after `:expand K`, compressing an overlapping range into a new `K'`
   **overwrites** the children's single `compressed_into` pointer, orphaning `K` from the line.
   Following pointers would then either lose `K` entirely or attribute its children to `K'`.

### The model: two off-line event-node types, resolved by enumeration
Every node carries an explicit **`created_seq`** (monotonic, assigned at creation, **never
reassigned** — unlike rowid, which the full-replace `save()` re-assigns). Two node types record
*events* rather than conversation content, both **off the `prev_id` line** (`prev_id = None`):

- **Compression `K`** — `K.meta` stores its **own** folded range (the ordered child ids). `K`
  goes to the model (wrapped user-role summary); its children do not.
- **Expand `E`** — `node_type = "expand"`, `E.meta = {"target": K.id}`, does **not** go to the
  model. `:expand K` **appends an `E`**; that node is what carries the deactivation's `created_seq`.

**Resolution — both the now-view and per-turn reconstruction — enumerates these event nodes; it
never follows child pointers.** For a turn `T`:

> Walk `prev_id` from `T` for the raw ancestor sequence `L`. Then, for every compression node `K`
> in the graph, apply it (replace its stored range within `L` with `K`) iff
> `created_seq(K) < created_seq(T)` **and** no expand `E` with `E.meta.target == K.id` has
> `created_seq(E) < created_seq(T)`.

The **now-view** is the "`T` = present" case: apply `K` iff no `E` targets it at all. **Generation
always uses the now-view; reconstruction is on-demand, read-only, and feeds only the diff view** —
the live context pipeline is unchanged.

### Consequences
- **`K` is never lost.** It is a persisted graph node found by *enumeration*; re-compression
  overwriting a child's `compressed_into` is irrelevant to discovery.
- **Re-compression after expand is allowed** — `K'` owns its own range; the old `K` persists as
  history. **Active compressions never overlap** (you cannot compress already-folded nodes), so
  the qualifying set at any time-slice partitions the line cleanly.
- **`compressed_into` on children is demoted** to a fast now-view / UI convenience. The **source
  of truth is the event nodes + `created_seq`.**
- **Diff view** ("concern b", A#1): because every shared node is byte-identical (immutable
  content; imports render identically on both sides), the context-drift diff is a **structural,
  block-alignment** diff (a verbatim run ⟷ a summary `K`), never an intra-block text diff.
  Source-*file* drift is a separate concern (staleness `~` / `gd`/`gD`, S5), not this view.

### Schema (columns still unchanged; two additions ride existing fields)
Columns remain `prev_id` + `compressed_into` + `active_leaf_id`. The additions are: an explicit
**`created_seq`** column (added in 3b; A#1's "rowid or created_seq" is resolved to the explicit
column, because full-replace `save()` reassigns rowid); the **`"expand"` `node_type`**; and `K`'s
range stored in **`K.meta`**. This **revises** Amendment #1's "children carry `compressed_into = K`
[as the mechanism]" and its "schema unchanged bar reliance on creation order." The append-only
invariant and the per-turn reconstruction rule are preserved and sharpened, not changed.
