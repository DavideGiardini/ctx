# ctx0 — Roadmap

## 1. Charter

The countdown to shipping **ctx0** (spec: `docs/ctx0_Product_Concept.md`;
re-scope decision: ADR-0017). This roadmap ends: when every box in §2 is
checked, the doc is archived and the next version gets its own. It records
*that* something was decided in one line with a pointer — grills and designs
live in ADRs and plan docs, never here. The long-term vision is parked in
`docs/north-star/` (permission-gated; consult during planning only).

## 2. Definition of shipped

A stranger installs ctx0 and, on day one, prefers it to a web chat app:

- [x] **chats** — streaming turns that cannot be broken by a second submit,
      a cancel, a provider error, or `/new`/`/resume` mid-stream *(Phase 1 —
      done 2026-07-21, `end_turn` single-owner lifecycle)*
- [ ] **sees the whole conversation** — the dual-pane high-ground view renders
      predictably, with one owner for geometry *(Phase 2)*
- [ ] **compacts** — condense any span of turns into an editable node that is
      all the model sees, reversibly *(shipped; surface finalized in Phase 2)*
- [ ] **imports** — point at a file with an instruction; only the editable
      extract enters the context *(Phase 3)*
- [ ] **searches the web** — the model calls built-in search; results are
      nodes in the same view *(Phase 4)*
- [ ] **is a product** — system prompt, install story, README, config
      *(Phase 5)*

## 3. Where we start

Sprint 3 is merged (2026-07-11): the dual-pane shell, streaming, the
append-only graph (ADR-0016), token accounting, and range compaction with the
draft editor and 3-split inspector all exist, with 705 green tests. Known debt
is catalogued in `docs/Code Quality Review 2026-07.md`: one critical
turn-lifecycle bug, a streaming-lifecycle cluster, and the accepted
message-rendering redesign. The ctx0 cuts (ADR-0017) are decided but not yet
applied to the code.

## 4. Ordering rationale

1. **Stabilize before adding** — the critical/major lifecycle bugs are in the
   floor everything else stands on.
2. **Subtract before redesigning** — delete the cut surfaces first so the
   rendering redesign never has to carry them.
3. **Import before search** — import reuses the existing compression draft
   engine; search needs new provider-seam work.
4. **Ship last** — polish and package what is finished.

## 5. Phases

### Phase 1 — Stabilize the streaming turn lifecycle
- **Goal:** one turn in flight, with one owner for how it starts and ends;
  a second submit is refused; every ending (finish / cancel / error) leaves a
  durable, rendered mark.
- **Approach:** review §"Turn lifecycle" + §"Aborted-turn policy" (the spec:
  core `end_turn`, UI convergence in `on_worker_state_changed`, refuse-don't-
  queue). Ride-alongs: register `interrupted`/`error` meta keys (§"Typed meta
  accessors"), extract shared Pilot scaffolding into conftest (§"Test
  choreography helpers").
- **Depends on:** nothing. **Size:** M.
- **Design status:** settled (the review is the spec).
- **Execution mode:** to decide at phase start.
- **Done:** double-submit refused with typed text preserved; cancel before
  first tick can't stick the flag; error/interrupt marks survive resume;
  `/new`/`/resume` cancel a live worker; Ctrl+C cancels a draft, not the app;
  qa-tester verify-fix pass + `check.sh` green.

### Phase 2 — Subtraction pass, then the rendering redesign
- **Goal:** the codebase is ctx0-shaped (cut surfaces deleted) and the message
  list has one geometry owner.
- **Approach:** deletions per ADR-0017 §2–3 — deep-dive, drift `Δ` +
  `ui.show_context_drift`, drift cache, `DiffView`, the as-of reconstruction
  oracles (keep `created_seq`/`ctx_hash` stamping and `hash_context`; fold
  duplication closes by deletion). Then the redesign per review
  §"Message-rendering redesign": geometry computed once, state only recolors,
  separator widget, truncation-map fix.
- **Depends on:** Phase 1 (don't redesign rendering atop unstable streaming).
  **Size:** M–L.
- **Design status:** settled (ADR-0017 + the review's accepted design).
- **Execution mode:** to decide at phase start (deletions are strong Ralph
  candidates; the redesign needs a decomposition pass first).
- **Done:** cut features gone from UI, bindings, footer hints, and
  `describe_state()`; stamping still on; spacing invariants hold as
  deterministic DOM assertions; qa-tester regression + `check.sh` green.

### Phase 3 — `import(file, prompt)`
- **Goal:** the second front door of the condense engine (spec §3–4.2): point
  at a file, give an instruction, edit the AI-drafted extract, commit a
  context node; the raw file never reaches the model.
- **Approach:** reuse the compression draft engine and 3-split inspector;
  content-on-node snapshots supersede live `/include` reads (supersedes
  ADR-0009). Design inputs: north-star S5 grill (B4, B6) + the
  "import-with-prompt" future-sprint note. Preamble refactor: extract the
  model-facing-form rule (review §"Model-facing-form extraction") before
  adding the node type.
- **Depends on:** Phase 2 (stable rendering for the new node flow).
  **Size:** L.
- **Design status:** **needs a `plan-feature` session** (open: verbatim mode
  in ctx0? what does `/include` become? snapshot staleness out of scope?).
- **Execution mode:** to decide after the design session.
- **Done:** import a file with a prompt, edit, commit; model receives only the
  extract (context-inspection proof); node inspects as prompt/source/output;
  qa-tester verify-feature + `check.sh` green.

### Phase 4 — Built-in web search
- **Goal:** the model can call `search(query)`; results come back as nodes in
  the high-ground view (spec §4.4, §7).
- **Approach:** provider seam grows function calling (first shape change since
  ADR-0015 — design carefully); one internal search abstraction with 2–3
  swappable backends behind a config line + API key; a provider interface,
  not a plugin system.
- **Depends on:** Phase 1 (turn lifecycle must absorb tool-call round-trips);
  independent of Phase 3. **Size:** L.
- **Design status:** **needs a `plan-feature` session** (open: tool-call
  rendering as nodes, retry policy, search-result weight in token accounting).
- **Execution mode:** to decide after the design session.
- **Done:** a question that needs the web gets a searched, cited answer;
  results visible as nodes with weights; backend swappable by config;
  qa-tester verify-feature + `check.sh` green.

### Phase 5 — System prompt + shipping polish
- **Goal:** ctx0 is a product someone installs on day one.
- **Approach:** one system prompt actually reaching the LLM (today none does),
  from config; install story + README for a stranger; API key via env var or
  flat config (spec §8 — no wizard).
- **Depends on:** Phases 1–4. **Size:** M.
- **Design status:** settled enough; confirm details at phase start.
- **Execution mode:** to decide at phase start.
- **Done:** clean-machine install → configured key → first useful conversation
  exercising all four verbs, following only the README.

## 6. Out of scope

By reference, to avoid dual-truth lists: ctx0 concept **§8** (everything
deliberately cut) and **ADR-0017 §4** (refactors dropped at re-scope). If it
isn't in §2 above, it isn't ctx0.

## 7. Verification (every phase)

`bash scripts/check.sh` green before every commit; new core behavior gets
code-blind contract tests via `/write-tests`; behavioral acceptance via the
`qa-tester` subagent; Ralph loops get a fresh PRD via `/ralph-tasks` per run
(the Sprint 3 PRD is archived, not edited).

## 8. Deferred, with revival triggers

Not scheduled anywhere — each revives only if its trigger event happens:

- **ViewStack** — trigger: a feature adds new full-screen/modal view states.
- **Fold policy/mechanism split** — trigger: the diff view (or any second
  fold consumer) returns.
- **Typed meta accessors (full) / StoragePort read collapse** — trigger: the
  meta vocabulary multiplies or storage changes are forced by a feature.
- **Nested compression** — trigger: compressing-a-compression proves needed in
  real use (north-star roadmap §Future Sprints).
- **Transparency surface (drift Δ, diff view)** — trigger: a post-ctx0 version
  re-adopts it; data has kept accruing (ADR-0017 §2), so history stays honest.
- **Branching, assistants, tools/MCP, KB modes, multi-project, RAG** — the
  north-star ladder; revisit only in a post-ctx0 planning round.
