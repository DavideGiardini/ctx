# 0017 — Re-scope to ctx0: ship a smaller, complete product

## Status

Accepted (2026-07-11)

## Context

The full ctx Product Concept had grown beyond what a personal project can carry:
the Sprint Roadmap ran to ten sprints (branching, imports, KB access modes,
assistants, MCP tools, multi-project), and the Sprint-3 compression work — though
feature-complete per its PRD — surfaced a class of UI locality bugs (see
`docs/Code Quality Review 2026-07.md`) that made the maintenance cost of the
growing surface tangible.

The response is **ctx0** (`docs/ctx0_Product_Concept.md`): not a demo of ctx but
a smaller *and complete* product — a modal terminal chat client whose soul is the
high-ground dual-pane view plus one condense engine (import a file / compact a
range into an editable node that is the only thing the model sees), with built-in
web search. The full concept and roadmap are parked, unedited, in
`docs/north-star/` — they remain the long-term vision and hold settled design
(the S3/S4/S5 grills) that ctx0 work reuses. The working plan is
`docs/ctx0 Roadmap.md`.

Re-scoping forced four decisions about work that already exists on
`feat/compression`.

## Decision

1. **`feat/compression` merges to develop as-is; fixes land on develop.**
   Compaction is ctx0's soul, so everything worth keeping on the branch is
   wanted. The known critical bug (mid-stream double submit) and the
   streaming-lifecycle cluster from the July review are fixed on develop as the
   first ctx0 work, not on a longer-lived feature branch.

2. **Context transparency: keep writing the data, delete the reading surface.**
   Every turn keeps stamping `created_seq` and `meta["ctx_hash"]` (cheap,
   invisible, and only the real generation moment can produce them — history
   stays honest). The *surface* built on them is deleted in the subtraction
   pass: the drift `Δ` marker, the drift cache, the full-screen `DiffView`, and
   the as-of reconstruction oracles (`context_at_generation`, `now_prefix`,
   `has_drift`, `diff_regions`, `reconstruction_warning`). `hash_context` stays
   (the stamping path uses it).

   **This consciously reverses the Sprint-3 invariant** "middle compression must
   never be live before the diff view exists." ctx0 keeps middle compaction —
   compacting *old* turns is the primary real-world use — without the
   inspection surface. Nothing lies: past turns simply aren't inspectable for
   what they saw. Because the data keeps accruing, the surface can return later
   with retroactively honest history and no migration seam.

3. **Deep-dive is deleted; the 3-split inspector is kept.** This corrects the
   ctx0 concept's original cut list, which dropped the 3-split on the wrong
   premise ("no prompt/output triads") — ctx0's condensed nodes carry exactly a
   prompt/source/output triad, and the 3-split's Center split showing the folded
   originals is precisely what makes deep-dive (`g d` on a K, `Ctrl+o`, the
   breadcrumb stack) a redundant second mechanism. With both deep-dive and the
   diff view gone, the `g d` binding and the full-screen-inspection view stack
   go entirely.

4. **The July review's build/defer list is re-triaged**, because its forcing
   event — Sprint-4 branching — no longer exists. Survives: the turn-lifecycle
   `end_turn` owner + aborted-turn policy (bug pressure now), the
   message-rendering redesign (bug pressure now; smaller once `DiffView` is
   gone), the test-choreography conftest extraction, the truncation-map fix.
   Dropped: ViewStack (its new view states were S4's; ctx0 shrinks the cluster
   instead), typed meta accessors beyond registering `interrupted`/`error`
   (which fold into `end_turn`), the StoragePort read collapse, and fold
   unification as a refactor — deleting the as-of oracles removes
   `reconstruction._fold`, so the live `current_view` copy becomes the single
   implementation and the duplication is resolved by deletion.

## Consequences

- `docs/north-star/**` is permission-gated (`.claude/settings.json`) so
  implementation sessions never read the vision docs by accident; planning
  sessions approve the prompt deliberately (see the `plan-feature` skill).
- ADR-0009 (imports are live, not snapshots) will be superseded when ctx0's
  `import(file, prompt)` lands: imports become instructed condenses stored
  content-on-node, per north-star S5/B4 design.
- The append-only graph (ADR-0016) is untouched: `prev_id` siblings, `rewind`,
  and `E.meta.anchor` stay in the schema/core even though branching UI is not a
  ctx0 feature — the data model already supports the future without carrying UI
  surface.
- Node kinds, `Node.goes_to_model()`, and the compression event model (K/E,
  event enumeration) are unchanged; ctx0 subtracts *views*, not the graph.
