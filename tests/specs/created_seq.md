# Behavioral contract — `created_seq` monotonic creation-order stamp

Source of intent: PRD task 14 + ADR-0016 amendments A#2 / A#3 / H6.

`created_seq: int` is a monotonically increasing integer stamped on each `Node`
recording the order it was created within a conversation. It is assigned at creation,
never reassigned, and is the durable oracle for "which events had happened as-of a turn."

Notation: "the graph" = the full append-only conversation graph (active line + abandoned
tails from rewinds + off-line compression `K` and expand `E` event nodes), NOT merely the
folded/visible view.

---

C1. Legacy DB migrates to sequential seqs in rowid order (per conversation)
  Given:    A raw pre-`created_seq` DB whose `nodes` table LACKS the `created_seq`
            column, with a single conversation whose node rows were inserted (rowid
            order) in creation order n1 -> n2 -> n3.
  Expect:   After `ConversationRepository(path).init()`, `load(conv)` returns the nodes
            in rowid order with `created_seq` == [1, 2, 3] — 1-based, strictly increasing
            by rowid.
  Rationale:Migration must backfill a column that never existed; rowid order == creation
            order (guaranteed by full-replace save), and a migrated conversation must
            match a fresh conversation's 1-based counter.

C2. New node after rewind gets max+1 counting the abandoned tail
  Given:    A conversation with line nodes u1,a1,u2,a2,u3,a3 (increasing seqs), then a
            `rewind` to a1 (nodes u2,a2,u3,a3 become an abandoned tail that stays in the
            graph), then a new `submit` producing u4,a4.
  Expect:   `u4.created_seq` is strictly greater than every abandoned-tail seq
            (max(u2,a2,u3,a3)) — the counter never reuses numbers freed by a rewind.
  Rationale:Monotonic per graph (H6): abandoned tails are counted; the new seq is one
            past the highest seq ANYWHERE in the graph.

C3. Compression K and expand E each consume a fresh seq
  Given:    A clean two-turn line (u1,a1,u2,a2 with increasing seqs); then
            `commit_compression` folds [u1..a2] into K; then `expand_compression(K.id)`
            appends event node E; then a new `submit` produces u3,a3.
  Expect:   `K.created_seq > a2.created_seq` and `K.created_seq > 0`; and after the
            expand, `u3.created_seq > K.created_seq + 1` (i.e. u3 skipped at least the
            seq consumed by E, proving E was itself stamped and counted).
  Rationale:K and E are graph nodes; each entering the graph gets max+1 exactly like a
            line node, so subsequent nodes advance past them.

C4. Save -> load round-trip preserves every node's created_seq exactly
  Given:    Nodes carrying non-contiguous, non-default seqs (e.g. 3, 7, 11) saved via
            `save()` then reloaded via `load()`.
  Expect:   Each node's `created_seq` after `load()` equals the value it was saved with
            (3, 7, 11), matched by node id — NOT re-derived from rowid.
  Rationale:created_seq is durable and assigned-once; unlike rowid it must survive the
            full-replace save/load without being re-sequenced.

C5. Migration is gated / runs exactly once
  Given:    A legacy DB migrated by a first `init()`, whose seqs are then externally
            perturbed to sentinel values; then `init()` is called a second and third time.
  Expect:   The perturbed seq values are unchanged after the repeated `init()` calls —
            the backfill does not re-run once the column exists.
  Rationale:Backfill is gated on the column being absent; re-running it would clobber
            durable, already-assigned seqs.

C6. Fresh conversation's first node gets seq 1
  Given:    A freshly set-up core (empty graph) and a first `submit`.
  Expect:   The first created node's `created_seq` == 1.
  Rationale:Empty graph => max default 0 => first node gets 1.
  (AMBIGUITY: assumes `setup()` does not itself stamp a node — see notes.)

C7. Two nodes from one submit get distinct, adjacent, increasing seqs
  Given:    A single `submit` returning (user_node, assistant_node).
  Expect:   `assistant_node.created_seq == user_node.created_seq + 1` and both > 0.
  Rationale:Both nodes enter the graph; each gets its own max+1 in creation order,
            user before assistant.

C8. Seqs strictly increase across successive submits
  Given:    Three successive drained submits producing u1,a1,u2,a2,u3,a3.
  Expect:   u1<a1<u2<a2<u3<a3 (strictly increasing in creation order).
  Rationale:Monotonicity of the per-graph counter.

C9. After resume, next node continues from loaded max + 1
  Given:    A conversation with max line seq = a2.created_seq, persisted (via
            new_conversation), then reloaded with `resume_conversation`; then a new submit.
  Expect:   The newly submitted user node's `created_seq == a2.created_seq + 1`.
  Rationale:Graph is rebuilt from persisted seqs; the counter continues monotonically
            across the persistence boundary from the loaded maximum.

C10. new_conversation resets to a fresh 1-based counter
  Given:    A populated conversation, then `new_conversation()`, then a first `submit`.
  Expect:   The first created node of the new conversation has `created_seq` == 1.
  Rationale:Reset returns to the empty-graph fresh state (max 0 -> first node 1).
  (AMBIGUITY: same setup/system-node assumption as C6.)

C11. Migration backfill numbers each conversation independently
  Given:    A legacy DB with conversation A (3 nodes) and conversation B (2 nodes),
            each inserted in creation order.
  Expect:   After migration, A's seqs == [1,2,3] and B's seqs == [1,2] — numbering is
            per-conversation, not global.
  Rationale:Per-conversation numbering; each conversation's counter is independent and
            1-based.

---

## Intent ambiguities flagged for a human

- C6 / C10 assume `ConversationCore.setup()` (and the `new_conversation()` reset) do NOT
  themselves stamp a node into the graph before the first user submit. If setup injects,
  e.g., a system node, the first *user* node would be seq 2, not 1. The tests assert the
  first *submitted user node* == 1; if setup pre-stamps a node this must be relaxed to
  "the first node in the graph == 1" (which is not directly observable through the given
  interface). Resolve by confirming whether setup/reset pre-create a node.
- The exact absolute seq of K and E is not observable (E's node object is not returned),
  so C3 asserts relative orderings only, per guidance.
- Whether `include_files` context nodes also receive seqs is implied by "every Node" but
  not independently exercised here (no floor requirement, low mutation risk beyond C7/C8).
