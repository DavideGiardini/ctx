# ctx0 — Roadmap

> Living planning doc for **ctx0** (`docs/ctx0_Product_Concept.md`), the product
> being built. Created at the 2026-07-11 re-scope (ADR-0017). The full-ctx
> Sprint Roadmap is parked in `docs/north-star/` — consult it during planning
> for settled design (S3/S4/S5 grills); do not schedule its sprints.

## Where ctx0 starts from

Sprint 3 (compression, all 51 PRD tasks) is merged. The shell, the dual-pane
view, streaming, persistence on the append-only graph (ADR-0016), token
accounting, and range compaction with the draft editor and 3-split inspector
all exist. What remains between here and a shippable ctx0 is: stabilization of
the streaming turn lifecycle, a subtraction pass, the rendering redesign, and
two genuinely new capabilities — `import(file, prompt)` and built-in web
search — plus a system prompt and shipping polish.

Each phase below: decide Ralph loop vs in-conversation per change (project
CLAUDE.md); gate with `scripts/check.sh`; behavioral verification via the
`qa-tester` subagent.

## Phase 1 — Stabilize the streaming turn lifecycle

From `docs/Code Quality Review 2026-07.md` (§Turn lifecycle, §Aborted-turn
policy) — bug pressure now, independent of the re-scope. The review's shape is
adopted: **core owns the fact, UI owns the mechanism.**

- **Critical:** refuse a second submit mid-stream. `submit()` raises while
  `_streaming` (the backstop); the UI reads `core.streaming`, hints, and keeps
  the typed text (InputBar stops clearing before acceptance).
- **`end_turn(node, outcome)`** — the single door every ending passes through:
  lower the flag, stamp the durable ending mark (`interrupted`/`error` move
  into the core; persist *after* the mark), persist. Renderer displays aborted
  turns from the persisted mark, not one-shot widget text.
- Convergence in `on_worker_state_changed` (fires on all terminal transitions,
  incl. cancel-before-first-tick — pin that assumption with a test). `/new` and
  `/resume` cancel a live stream worker; Ctrl+C cancels a live draft instead of
  exiting; `@work` exceptions can't crash the app.
- Register the `interrupted`/`error` meta keys (the 20% of typed-meta worth doing).
- Rides along (safe for an unsupervised Ralph iteration): extract the ~400
  lines of duplicated Pilot test scaffolding into conftest.

## Phase 2 — Subtraction pass, then the rendering redesign

Subtract **first** so the redesign never has to carry the deleted surface.

- **Delete deep-dive** (`g d` on a K, `Ctrl+o`, breadcrumb stack) — the 3-split
  Center already shows a K's folded originals (ADR-0017 #3).
- **Delete the transparency surface, keep the data** (ADR-0017 #2): drift `Δ`
  marker + `ui.show_context_drift`, drift cache, `DiffView`, the as-of oracles
  in `reconstruction.py`. Keep stamping `created_seq` + `ctx_hash`
  (`hash_context` stays). Middle compaction stays live. Removing
  `reconstruction._fold` leaves `current_view` as the single fold
  implementation — the review's fold-unification item closes by deletion.
- **Rendering redesign** (review §Message-rendering, accepted): geometry
  computed once from the nodes, state only recolors; separator widget at turn
  boundaries; retire the four spacing mechanisms; fix the diverged truncation
  map; spacing invariants become deterministic DOM assertions.

## Phase 3 — `import(file, prompt)`

The second front door of the one condense engine (ctx0 §3–4.2): point at a
file, give an instruction, AI-drafts an extract, user edits, commit creates a
context node whose output is all the model sees. Supersedes today's live
`/include` reads (ADR-0009) with content-on-the-node snapshots.

- Reuses the compression draft engine (draft → edit → commit) and the 3-split
  inspector (prompt / source / output).
- Design inputs: north-star S5 grill (B4 verbatim/summarize modes,
  content-on-node, B6) and the "import-with-prompt" future-sprint note.
- Preamble refactor (review §Model-facing-form): extract the single "what does
  this node look like to the model" rule before adding the node type.
- Needs a `plan-feature` session first (open: is a promptless/verbatim import
  in ctx0? what does `/include` become?).

## Phase 4 — Built-in web search

The biggest genuinely new build (ctx0 §4.4, §7): the model can call
`search(query)`; results come back as nodes in the high-ground view.

- Provider seam grows function calling (first real change to `Provider.stream`'s
  shape since ADR-0015 — design carefully, it's the deepest seam).
- One internal search abstraction, 2–3 concrete backends (Brave/Tavily/…),
  selected by config + API key. A provider interface, **not** a plugin system.
- Needs a `plan-feature` session first (tool-call rendering as nodes, retry
  policy, how search results weigh in token accounting).

## Phase 5 — System prompt + shipping polish

- One system prompt actually reaching the LLM (today none does), from config.
- Packaging/first-run: install story, README for a stranger, API key via env
  var or flat config — ctx0 is a product someone chooses on day one.

## Dropped at the re-scope (ADR-0017 #4)

ViewStack, typed meta accessors beyond `interrupted`/`error`, StoragePort read
collapse, fold unification as a refactor (closed by deletion in Phase 2). The
full deferred-capability list lives in ctx0 concept §8 and
`docs/north-star/Sprint Roadmap.md` §Future Sprints.
