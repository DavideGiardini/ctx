# ctx — Domain Glossary

> Canonical vocabulary for the ctx conversation IDE. Glossary only — no
> implementation detail. See `docs/Product Concept.md` for vision,
> `docs/decisions/` for ADRs, `docs/Sprint Roadmap.md` for the plan.

## Conversation graph

- **Node** — one unit on the conversation graph: a user turn, assistant turn,
  context import, system breadcrumb, or compression node.
- **Line** — the chain of nodes reachable by walking `prev_id` from a tip to the
  root. The *active line* (from `active_leaf_id`) is what the UI shows.
- **Branch** — two nodes sharing a `prev_id` (siblings); divergence forks a line.
- **Active leaf / tip** — the current end of the active line (`active_leaf_id`).
- **Rewind** — moving the tip back to an earlier node on the active line; the
  abandoned tail is preserved (append-only), not deleted.
- **current_view()** — the projection of the active line into the flat
  `list[Node]` the UI and `build_context` consume.

## Branching & sub-chats (Sprint 4)

- **Branch** — a sibling `prev_id` line *within one conversation* (all nodes
  share `conversation_id`; the conversation has one `active_leaf_id` that
  selects the active branch). A branch is **not** a separate conversation.
  (Supersedes the terse entry above.)
- **Import node** — a node that materializes **external** content as a
  self-contained snapshot **on the current line** (content-on-`content`, source
  reference in `meta`). Distinct from a **branch**: a branch is *your own* line
  diverging; an import is *someone else's* content copied in. One concept, three
  sources — a **file**, a **sibling branch** (sub-chat), or (future) **another
  conversation**. Never a graft of the source's live nodes.
- **Sub-chat** — a branch that is later **re-imported** into the parent line as
  an import node holding a (usually AI-drafted) *summary* of that branch. The
  branch stays live and browsable (as its tab); the import node is the summary
  snapshot. Re-import is the **import** primitive, **not** compression: it
  reuses S3's draft-with-prompt *engine* but emits an import node, sharing
  nothing with `K` / `compressed_into` / event-enumeration.
- **Indexed** *(deferred — see Future Sprints)* — **automatic-import scope
  control**: the fence defining what the assistant may draw from *on its own*,
  as opposed to **manual** import (always allowed for any supported source). It
  is **access control** (kin to §3.1 Access modes), *not* conversation
  archiving. Only meaningful once automatic import/retrieval exists (S6+); pulled
  from S4.
- **Branch delete** — the whole-branch hard delete (ADR-0016's *one* true
  row-deletion), reachable as a fast verb on an abandoned tail. Distinct from
  **rewind** (non-destructive). Backed by **session undo**.
- **Session undo** — a single-step, session-scoped, this-op-only undo of a branch
  delete: a one-slot in-memory stash of the last-deleted subgraph, re-inserted on
  undo. *Not* a general undo stack and *not* durable across restart (that would be
  the deferred trash/soft-delete). Cheap because the graph is in-memory and
  `save()` is full-replace.

## Compression (Sprint 3)

- **Compression node (`K`)** — an immutable node holding an (AI-drafted,
  user-edited) summary of a contiguous range of nodes it *folds*. Sent to the
  model **instead of** the nodes it folds. Lives **off** the `prev_id` line: it
  has no `prev_id` and is discoverable only via the back-pointers of its
  children. Never appears as a tip or a branch sibling.
- **Fold / folded children** — the contiguous range of nodes a compression node
  subsumes. Each carries `compressed_into = K`. They stay on the `prev_id` line
  (the chain is never mutated) but are hidden from the resolved view and from
  the model; reachable via deep-dive / inline folding / expand.
- **Resolving a compression** — in `current_view()`, replacing a maximal
  contiguous run of nodes sharing `compressed_into = K` with `K`, in place.
- **Draft** — the AI-generated (or blank, for manual) candidate summary shown in
  the compression editor before commit. Streamed from the active model; discarding
  it mutates nothing.
- **Commit** — the single graph mutation that turns a draft into a real
  compression node `K` and sets `compressed_into` on the folded range.
- **Compression editor** — the left-pane surface for *creating* a compression:
  a **2-split** — Top = editable prompt (prefilled with the default), Bottom =
  editable output (the draft). No Center split: the originals are on the right
  pane as the highlighted selection while drafting.
- **Compression inspector** — the left-pane view of a *committed* compression
  node: a **3-split** — Top = prompt, Center = the folded children/originals,
  Bottom = summary. The Center reappears (vs the editor) because after commit the
  originals are folded away on the right pane, so the left pane is their home.
- **Compression modes** — *default* (draft with the default prompt), *ad-hoc*
  (edit the prompt, then draft), *manual* (type the summary, never draft). All
  three are actions within the one compression editor.
- **Deep-dive (`gd` / `Ctrl+o`)** — "go to definition" for a compression node:
  full-view replacement of the right pane with the folded children, tracked by a
  breadcrumb stack; `Ctrl+o` returns up one level. Read-only inspection.
- **`:expand`** — return a compression's children to the model's context. Distinct
  from deep-dive/folding (which only *look*). In 3a it clears the children's
  `compressed_into` and orphans `K`; in 3b it appends an **expand event**.
- **Event node** — an off-line node (`prev_id = None`) that records a
  context-affecting *event* rather than conversation content, discovered by
  enumeration (never on the `prev_id` line). Two kinds: a **compression node**
  `K` (owns its folded range) and an **expand node** `E` (`meta.target = K.id`,
  deactivates `K` going forward). Both carry `created_seq`.
- **`created_seq`** — a monotonic, immutable, never-reassigned creation order on
  every node (3b). The basis for per-turn reconstruction. Distinct from rowid,
  which the full-replace save reassigns.
- **Per-turn reconstruction** — recomputing the context a past turn `T` saw:
  walk `T`'s ancestors for the raw sequence, then apply every compression `K`
  with `created_seq(K) < created_seq(T)` not deactivated (by an `E`) before `T`.
  On-demand and read-only — it powers the diff view, never generation.
- **Context-drift diff view** — a full-screen, navigable, block-alignment diff on
  an AI turn: *context-at-generation* (left) vs *now* (right). All differences are
  structural (a verbatim run ⟷ a summary `K`); source-file drift is a separate
  concern (staleness `~`, S5), not this view.
