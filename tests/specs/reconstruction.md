# Behavioral contract — `ctx.core.reconstruction`

Derived purely from the public interface + statement of intent. Each item is an
oracle: a checkable assertion about the returned id-sequence
(`[n.id for n in result]`) or boolean, never "whatever the code produces".

Domain recap used throughout:
- Ordinary turns chain by `prev_id`; walking `prev_id` from `T` back to the root
  gives `T`'s ancestor line. `L` = **strict** ancestors (root-first, `T` excluded).
- A compression `K` (`node_type="compression"`, `prev_id=None`,
  `meta={"range":[...], "prompt":...}`) folds the contiguous run of its `range`
  ids inside `L` into the single node `K`.
- An expand event `E` (`node_type="expand"`, `prev_id=None`,
  `meta={"target":<K.id>, "anchor":...}`) records that `K` was later un-folded.
- `created_seq` is the monotonic transaction-time axis; every fixture node sets it
  explicitly.

---

## `context_at_generation(all_nodes, node_id)` — the as-of view

**C1. Happy path: a turn generated AFTER a compression sees `K`.**
  Given:    line a,b,c; `K` over range [a,b,c] with `created_seq(K) < created_seq(T)`;
            turn `T` with `prev_id=c`; no expand events.
  Expect:   returns id-sequence `["K"]` — the contiguous run [a,b,c] is folded to `K`.
  Rationale:`K` existed when `T` ran, its range lies wholly on `T`'s line, and it was
            not expanded before `T` (as-of rule, all three conditions hold).

**C2. As-of exclusion: a `K` created AFTER `T` is not applied → verbatim.**
  Given:    line a,b,c; turn `T` (`prev_id=c`); `K` over [a,b,c] with
            `created_seq(K) > created_seq(T)`.
  Expect:   returns `["a","b","c"]` (verbatim ancestors, no fold).
  Rationale:`K` did not exist when `T` was generated; the as-of rule requires
            `created_seq(K) < created_seq(T)`.

**C3. As-of exclusion: `K` expanded BEFORE `T` is not applied → verbatim.**
  Given:    line a,b,c; `K` over [a,b,c] (`seq(K) < seq(T)`); expand `E` targeting `K`
            with `created_seq(E) < created_seq(T)`; turn `T` (`prev_id=c`).
  Expect:   returns `["a","b","c"]`.
  Rationale:`K` had already been un-folded at the time `T` ran (an `E` with
            `target==K.id` and `seq(E) < seq(T)` blocks the fold).

**C4. As-of inclusion: `K` expanded AFTER `T` is still applied → `["K"]`.**
  Given:    line a,b,c; `K` over [a,b,c] (`seq(K) < seq(T)`); turn `T` (`prev_id=c`);
            expand `E` targeting `K` with `created_seq(E) > created_seq(T)`.
  Expect:   returns `["K"]`.
  Rationale:the expand happened after `T` was generated, so at `T`'s transaction time
            `K` was still active.

**C5. Range not a subset of `L` (abandoned-tail) never applies → verbatim.**
  Given:    line a,b,c; turn `T` (`prev_id=c`); `K` with range [a,b,"x"] where `"x"`
            is not among `T`'s strict ancestors; `seq(K) < seq(T)`; no expand.
  Expect:   returns `["a","b","c"]`.
  Rationale:the fold is all-or-nothing on `T`'s line; a range that leaves the line
            (`range ⊄ ids(L)`) never applies.

**C6. `T` itself is excluded (strict ancestors only).**
  Given:    line a,b,T (`T.prev_id=b`); no events.
  Expect:   returns `["a","b"]`; the last element is `T`'s predecessor `b`, and `"T"`
            is not present.
  Rationale:"a turn's context is the material before it" — strict ancestors.

**C7. Maximal contiguous run: a middle sub-run folds in place, neighbours kept.**
  Given:    line a,b,c,d,e; turn `T` (`prev_id=e`); `K` over range [b,c,d]
            (`seq(K) < seq(T)`); no expand.
  Expect:   returns `["a","K","e"]`.
  Rationale:only the contiguous run [b,c,d] is replaced by `K` in place; `a` before
            and `e` after are preserved in order.

**C8. Two independent compressions each fold their own run, in order.**
  Given:    line a,b,c,d; turn `T` (`prev_id=d`); `K1` over [a,b], `K2` over [c,d]
            (both `seq < seq(T)`); no expand.
  Expect:   returns `["K1","K2"]`.
  Rationale:each applying compression replaces its own contiguous run; order is
            preserved root-first.

**C9. Unknown / root / off-line node id → `[]`.**
  Given:    (a) `node_id` not present in `all_nodes`; (b) a root turn with
            `prev_id=None`; (c) the id of a compression or expand node
            (`prev_id=None`).
  Expect:   each returns `[]`.
  Rationale:no strict ancestors exist for an unknown, root, or off-line node.

**C10. Era selection: expand → re-compress; each turn sees the `K` active at its seq.**
  Given:    line a,b,c; `K1` over [a,b,c] (seq k1); `T1` (seq>k1, `prev_id=c`);
            expand `E1` targeting `K1` (seq e1>seq(T1)); `T2` (seq>e1, `prev_id=c`);
            `K2` over [a,b,c] (seq k2>seq(T2)); `T3` (seq>k2, `prev_id=c`).
  Expect:   `context_at_generation(all,"T1") == ["K1"]`;
            `context_at_generation(all,"T2") == ["a","b","c"]`;
            `context_at_generation(all,"T3") == ["K2"]`.
  Rationale:as-of resolution binds each turn to the compression active at its own
            `created_seq`; T2 falls in the expanded gap; T3 sees the later K2.

**C11. Result is root-first.**
  Given:    line a,b,c,T with no events.
  Expect:   returns `["a","b","c"]` (root first, predecessor-of-T last).
  Rationale:the contract states the result is root-first.

---

## `now_prefix(all_nodes, node_id)` — the now view

**C12. Folds a `K` that exists now even if it was created after `T`.**
  Given:    line a,b,c; turn `T` (`prev_id=c`); `K` over [a,b,c] with
            `created_seq(K) > created_seq(T)`; no expand.
  Expect:   returns `["K"]`.
  Rationale:now-view ignores `created_seq` ordering; `K` exists today and its range
            ⊆ ancestors, so it folds.

**C13. Any expand targeting `K` (regardless of seq) restores `K` → verbatim.**
  Given:    line a,b,c; `K` over [a,b,c]; turn `T` (`prev_id=c`); expand `E` targeting
            `K` (seq irrelevant, e.g. `seq(E) > seq(T)`).
  Expect:   returns `["a","b","c"]`.
  Rationale:now-view: a `K` applies iff NO `E` targets it at all; an existing expand
            un-folds it today.

**C14. Range not a subset of `L` never applies → verbatim.**
  Given:    line a,b,c; turn `T` (`prev_id=c`); `K` with range [a,b,"x"], `"x"` off
            line; no expand.
  Expect:   returns `["a","b","c"]`.
  Rationale:same subset constraint as as-of; range must lie wholly on the line.

**C15. Unknown / root / off-line node id → `[]`.**
  Given:    (a) unknown id; (b) root turn `prev_id=None`; (c) a compression/expand id.
  Expect:   each returns `[]`.
  Rationale:no strict ancestors.

**C16. Now-view of an as-of era-selected turn folds the currently-live `K`.**
  Given:    the C10 graph (K1 expanded by E1, then K2 exists, no expand on K2).
  Expect:   `now_prefix(all,"T1") == ["K2"]` (today only K2 is live over [a,b,c],
            K1 is expanded).
  Rationale:the now-view reflects every event that exists today: K1 restored, K2 live.

---

## `has_drift(all_nodes, node_id)` — as-of vs now

**C17. Drift True: turn before a compression (verbatim vs folded).**
  Given:    C2/C12 graph — `K` created after `T`.
  Expect:   `has_drift(all,"T") is True`.
  Rationale:as-of `["a","b","c"]` differs from now `["K"]`.

**C18. No drift: turn after a compression, no expand.**
  Given:    C1 graph — `K` created before `T`, no expand.
  Expect:   `has_drift(all,"T") is False`.
  Rationale:as-of `["K"]` equals now `["K"]`.

**C19. Drift True (reverse direction): saw `K`, expanded after.**
  Given:    C4 graph — `K` folded at `T`, `E` after `T`.
  Expect:   `has_drift(all,"T") is True`.
  Rationale:as-of `["K"]` differs from now `["a","b","c"]` — opposite direction to C17.

**C20. No drift: conversation with no compression/expand events.**
  Given:    plain line a,b,c,T.
  Expect:   `has_drift(all,"T") is False`; both views equal `["a","b","c"]`.
  Rationale:with no events the two rules coincide.

**C21. Unknown / root node never drifts.**
  Given:    unknown id, and a root turn.
  Expect:   `has_drift` is `False` for both (both views are `[]`).
  Rationale:equal (empty) prefixes cannot differ.

---

## Ambiguities assumed past (flag for human)

1. **`now_prefix` era of C16.** The docstring says now-view folds any `K` with no
   targeting `E` and range ⊆ ancestors. If two live compressions had identical
   ranges the result would be ambiguous; C16 keeps exactly one live `K` (K1
   expanded, K2 not) so the expected `["K2"]` is unambiguous. Confirm this is the
   intended reading.
2. **`created_seq` strictness.** The as-of comparisons are read as strict `<`
   (`created_seq(K) < created_seq(T)`), matching the docstring. Ties
   (`seq(K)==seq(T)`) are not exercised because the domain states creation order is
   strictly monotonic (no ties can occur).
3. **Off-line `node_id` returns `[]`.** Assumed a compression/expand node has no
   `prev_id` chain, so passing its id yields `[]` (per "an off-line K/E node yields
   []").
