# ctx — Sprint Roadmap to the Product Concept

> Living planning doc. We refine it sprint by sprint. Sprints are one level above
> Ralph tasks: each is a coherent slice of capability, not a single-session task.
> See `docs/Product Concept.md` for the target vision.

## Context

`ctx` is a context-aware conversation IDE (Python/Textual). The **shell is done and
production-grade**: dual-pane TUI (conversation graph + detail inspector), Insert/Edit
modes, vim-style navigation, the 3-split context view, live streaming, SQLite
persistence with model round-trip, `/model /new /resume /include`, sandboxed file
includes, and a clean `core/` (framework-free) ↔ `ui/` (Textual) split with stable
seams (`StoragePort`, `Provider`, injected `load_file`, `Workspace`).

**What's missing is almost everything that makes ctx *special*** per
`docs/Product Concept.md`: compression & spatial navigation (the stated *primary
differentiator*, §4), branching/sub-chats (§5), import snapshots & staleness (§3.3),
granular KB access control (§3.1), assistants (§6.1), tools/MCP (§6.2), and
multi-project structure (§2).

**The architectural linchpin:** compression, branching, reversibility, and import
snapshots *all* require the same persistence change — today's flat node list with
**full-replace `save()`** (`ctx/core/storage.py:75`, DELETE-all-then-INSERT) and a
`nodes` table with no edges (`ctx/core/storage.py:30`) must become an **append-only,
non-destructive node graph** (git-like: the past is immutable; the conversation only
changes going forward; divergence forks a branch). This **supersedes ADR-0006 #2's**
assumption of a soft-delete + operation-log design — the append-only graph *is* the
history, so there is no undo subsystem and no op log (see S2). That redesign is the
foundation everything else stacks on.

**Direction set for this roadmap:** Foundation → Compression first; RAG deferred
entirely; multi-project + first-run wizard last.

---

## Ordering rationale

1. **Token accounting** *(shipped)* — independent of the graph, high-visibility, and
   *motivates* compression (you compress to cut token weight — you must see weight first).
2. **Node-graph foundation** unblocks compression, branching, and snapshots — build it
   before any of them so nothing gets retrofitted. (History/reversibility needs *no* sprint
   of its own: the append-only graph *is* the history — see the note under S3/S4.)
3. **Compression + spatial nav** is the differentiator; it lands as early as the
   foundation allows.
4. **Branching/sub-chats** also rides the S2 graph; sub-chats specifically need
   compression (S3), so it follows. Reversibility (rewind/fork) lives here.
5. **Import snapshots** are immutable content stored on the graph (S2); re-import forks a
   branch (S4), then staleness/`gd`/`gD` layer on the existing context-node UI.
6. **KB expansion + access modes** generalize the knowledge base and gate it — a
   prerequisite shape for any future retrieval.
7. **Assistants** bundle prompt+model+tools and finally send a system prompt to the LLM.
8. **Tools/MCP** are large and benefit from the assistant invocation model (S7).
9. **Multi-project + wizard** restructure the on-disk layout; deferred so features are
   built once against single-project, then generalized.
10. **Conversation graph map** *(nice-to-have)* — a bird's-eye DAG visualization, beyond
    the concept's spec; lowest priority, last. Everything above make-or-breaks the app;
    this is orientation polish and could stay unbuilt.

---

## Sprints

### Sprint 1 — Token accounting & context budget
**Goal:** Real numbers in the two UI slots that already exist but are hardcoded to
`None`: the header context-window gauge (`app_header.py:set_context_pct`) and per-node
weight `--%` (`message_list.py`, `MessageWidget.set_weight_pct`). No DB change; `core/`
stays framework-free (a new small `core/tokens.py` deep module; `describe_state()` at
`app.py:386` feeds the widgets).
**Depends on:** nothing. **Size:** S. **Done:** gauge + per-node % reflect real usage;
`check.sh` green; qa-tester confirms numbers move as nodes are added/removed.

#### The reliability problem (why this needs a design, not just a library call)
Local token counting is **exact only for OpenAI** (`tiktoken`). Anthropic ships **no
local tokenizer since Claude 3** (only a networked, rate-limited `count_tokens` API; its
Opus 4.7+ tokenizer is ~30% denser than older ones). Gemini is the same (networked
API, no local tokenizer). Gemma/Qwen/Deepseek have accurate local tokenizers only via
heavy HuggingFace deps. `litellm.token_counter` falls back to `tiktoken` for anything it
doesn't bundle — and ctx's **default model is `openrouter/google/gemma-…`**, i.e. the
common case is the *approximate* path. A live gauge that updates per-keystroke/per-node
must be **fast, offline, synchronous** — which rules out the accurate-but-networked APIs
and the heavy local tokenizers.

#### Design decision: two denominators, relative-local + absolute-from-provider
The two things a user wants map to two mechanisms with two denominators:
- **Per-node weight (distribution — "which parts cost most"):** a *relative* quantity =
  `local_estimate(node) / Σ local_estimate(all nodes)`. Computed locally, no provider
  call. **Robust even for non-OpenAI models**, because the per-model error lives in the
  tokenizer's *scale factor*, and the scale factor **cancels in a ratio** (a block with
  2× the prose is ~2× the tokens under any BPE/SentencePiece tokenizer). So the
  distribution view is accurate for free, regardless of model.
- **Header total (absolute — "how full is my budget"):** the **exact** number from the
  provider's `usage.prompt_tokens`, against `litellm.get_model_info(model).max_input_tokens`.

#### Making the parts sum to exactly 100%
ctx's "full control" philosophy means **every context contributor is a node** —
including the system prompt and tool definitions (editable system/tool nodes, landing in
S8/S9), not hidden framing. So per-node weights should sum to 100%. To make that literal:
1. **Count each node *with its message framing included*** (role/delimiter tokens), not
   bare content — `litellm.token_counter` already counts messages as rendered, so each
   node's estimate carries its own structural share; only a tiny conversation-level
   constant is left over.
2. **Global-ratio true-up (calibration):** store one float `r = exact_total / local_sum`
   from the last turn's real `usage`; per-node *absolute* tokens = `local_estimate × r`,
   which then **sum exactly to the provider's total**. This is principled (we have a real
   per-node basis and only correct *scale*; we are **not** fabricating attribution from a
   single aggregate — the provider cannot and does not attribute its total per-message).
   The ratio cancels in the percentage, so per-node **%** stays purely local/robust;
   calibration only sharpens the **absolute** numbers.

#### Design constraints / notes
- **Count generically over all context-contributing node types** — drive off
  `Node.goes_to_model()`, don't special-case user/assistant/context. When S8/S9 add the
  system-prompt and tool nodes, they're counted automatically with no rework. (In S1 only
  user/assistant/context exist to count, but the model is built total.)
- **Configurable denominator** (note for config): `ui.weight_basis: "context" | "window"`
  — (a) `context` = % of *current* context used (sums to 100%), vs (b) `window` = % of
  the model's *full* context window (shows headroom). Applies to the per-node weight and
  the gauge basis.
- **Honesty marker:** `~` rides only on *absolute* numbers when they're an estimate (no
  provider anchor yet, or stale between turns after nodes were added); per-node **%**
  never needs it.
- **Requires a small provider seam change (flagged, not designed this session):**
  `Provider.stream` yields `str` today; the exact `usage` must be surfaced off the stream
  (litellm exposes it on the final chunk via `stream_options={"include_usage": True}`).
- **Explicitly rejected:** networked `count_tokens` calls (too slow/rate-limited, breaks
  offline) and HuggingFace/SentencePiece tokenizers (too heavy for a TUI). Both are
  possible later as an opt-in "accurate mode."

### Sprint 2 — Node-graph persistence foundation *(linchpin)*
**Goal:** Replace flat-list + full-replace persistence with an **append-only,
non-destructive node graph** — without changing any current user-visible behavior.
Today's linear conversation is just the degenerate single-path case of this graph.

#### The mental model (settled — this shapes S3/S5 too)
The conversation is **git-like**: an append-only DAG where the past is immutable and the
conversation only ever changes *going forward*. This single structure *is* the history —
there is **no separate undo system, no operation log, and no event-sourcing.**
- **The line is time; compression is depth** (§4) — two orthogonal relationships.
- **The key invariant we get for free:** the ancestor path of any node is a faithful,
  permanent record of exactly what that node saw when it was generated. No extra
  bookkeeping — the structure *is* the record. (This is *why* we rejected a mutable
  per-node "mute/in_context" flag: it would break this invariant and drag per-turn
  temporal versioning back in. See parking lot.)
- **Reversibility = navigate or fork**, not undo:
  - *Edit a past message* or *refresh an import to new content* → **fork a branch** (the
    old line is preserved; turns after it depended on the old text, so a new line is the
    only coherent outcome).
  - *Delete a middle message* → **the same as rewind**: fork from the node before it
    (there is no "excise a node but keep its dependent tail" — that's incoherent).
  - *Delete the last n messages* → **rewind** the active tip.
  - *Compress a contiguous range* (any position, incl. middle) / *expand it back* →
    **non-destructive**; children are preserved under the compression node and `expand` is
    a pure toggle. Compression is an **immutable, creation-ordered event**: a turn's
    context applies only compressions created before it (see ADR-0016 Amendment #1 + S3).
  - *Delete a whole branch / conversation* → the **only** true row-deletion; permanent,
    no trash for now (trash is a clean future add).

#### Schema (locked — three fields, nothing more)
- `nodes.prev_id TEXT NULL` — predecessor on the line; NULL = root. **Siblings (same
  `prev_id`) are branches.** Rewind moves the active tip; diverging from it creates a
  sibling.
- `nodes.compressed_into TEXT NULL` — if set, this node is a child folded into that
  compression node: preserved, reachable via deep-dive/`expand`. The compression node
  itself sits **off** the `prev_id` line (so it never reads as a branch sibling) and
  carries the range it folds. Per-turn folding is by **creation order** (rowid today; a
  possible explicit `created_seq`/timestamp) — see ADR-0016 Amendment #1.
- `conversations.active_leaf_id TEXT NULL` — the current tip; walking `prev_id` from it to
  root yields the active line. (Degenerate/today's case: it's the last node.)
- **Explicitly NOT added:** `deleted_at`/soft-delete (per-message "delete" is
  rewind/branch, not removal; whole-branch delete is a hard `DELETE`), an `operations`
  table, and any `in_context`/mute flag. All three were considered and rejected above.

#### Approach
- Introduce a **`current_view() -> list[Node]`** projection (walk the active line,
  resolving compression) so the UI and `build_context` consume exactly today's shape;
  the graph lives behind that one method (blast radius on the UI ≈ zero).
- `ConversationCore`'s in-memory state grows from `list[Node]` to the graph; it must hold
  *all* nodes (every line + compression children), not just the active view.
- Replace full-replace `save()` (`storage.py:75-121`) so it persists the **full node
  set**; `load()` reconstructs the graph. **`StoragePort.save` changes → the
  `SaveCountingStorage` double (`tests/test_conversation.py`) MUST move in lockstep.**
- A `PRAGMA table_info` migration like the existing `_migrate` (`storage.py:66`):
  existing flat DBs get `prev_id` chained by `rowid`, `active_leaf_id` = last node,
  `compressed_into` NULL.

**Scope (settled):** rails **+ one proof op — `rewind`** (move `active_leaf_id` back a
node). It's the smallest real graph mutation and exercises the whole new pipeline
end-to-end: mutate the tip → recompute `current_view()` → persist → reload → confirm.
**Depends on:** none hard. **Size:** L (smaller than first drafted — no op-log, no
soft-delete). **Done:** all existing tests + qa-tester flows pass unchanged; the graph
fields round-trip; `current_view()` on a migrated linear DB equals today's node list; a
`rewind` moves the tip, the view updates, and it survives a save/reload round-trip.

### Sprint 3 — Compression & spatial navigation *(the differentiator, §4)*
The compression model is fully specified in **ADR-0016 Amendment #1**. Compression is an
**immutable, creation-ordered event** that folds a contiguous range; a turn's context =
its ancestors with only the compressions **created before it** applied. Split into two:

#### Sprint 3a — Safe (tip/suffix) compression + spatial nav
**Goal:** Select a contiguous range **at the tip** (no live assistant response after it) →
AI-drafts a compression node (editable before commit, §4.1) → the model sees the node, not
its children; navigate compression depth. This is the fast, fully-safe slice: nothing was
generated atop the fold, so no reconstruction is needed and concerns (a)/(b) can't arise.
**Approach:** a "compress range" op creating a compression node + `compressed_into` on the
origins (preserved, non-destructive). Extend `build_context` (`ctx/core/context.py`,
already routing through `goes_to_model()`) so a compression node reaches the model and its
children don't. `expand` is a pure non-destructive toggle. UI: range selection in Edit
mode; **deep-dive** `gd`/`Ctrl+o` (full-view replacement + breadcrumb, §4.2); **inline
folding** `zo`/`zc`/`zR`/`zM`; `:expand`. (`:remove` of an import stays rewind/branch, not
a special op.)
**Depends on:** S2. **Size:** L. **Done:** compress a tip range, edit the draft, confirm
the model sees only the node (qa-tester via context inspection); `gd`/`zo`/`zM` behave per
§4.2; `check.sh` green.

#### Sprint 3b — Middle compression + context transparency
**Goal:** Allow compressing **any contiguous range** (incl. the middle, with live turns
after it), made honest by a per-turn context diff. Middle compression and the diff view
ship **together** — the diff is what makes middle compression trustworthy.
**Approach:**
- **Preserve-info default prompt** (§6.1) injected on the default path — *"preserve facts,
  decisions, entities, and open threads needed to continue coherently"* — with a **config
  opt-out** for full prompt control (then info loss is the user's call: power over
  protection). Tip compression needs no such instruction.
- **Per-turn reconstruction:** context of turn T = its ancestors applying only
  compressions created before T (creation order via rowid / an explicit `created_seq`).
  Generation always uses the current (all-compressions) view.
- **Git-diff context view:** for an AI node whose generation context differs from now
  (a later compression folds something in its ancestry), add an openable split to its left
  detail pane showing *context-at-generation* (left) vs *that same prefix now* (right).
  Keep the indicator subtle + config-toggleable (many turns can legitimately show it).
- Coherence is **mitigated, not guaranteed** (concern (a)); reversibility (`expand`,
  rewind/branch) is the safety net.
**Depends on:** S3a. **Size:** L. **Done:** compress a middle range on a continued
conversation; later turns still read coherently; the affected earlier response shows the
diff of what it saw then vs now; expand restores full context going forward; `check.sh`
green.

> **Sprint 4 (History log & reversibility) has been removed.** §4.3 reversibility is fully
> served by the append-only graph itself: "nothing is truly deleted" is the graph being
> non-destructive (compression preserves children; abandoned lines persist as branches),
> and "reversal" is navigate/rewind/fork — not an undo subsystem. A chronological text
> `:history` readout was considered and **dropped** (marginal once reversal is direct
> action, not undo). The spatial *graph-map* idea is spun out to its own late nice-to-have
> sprint (S10). This **revises ADR-0006 #2**, which had anticipated an op log.

### Sprint 4 — Branching & sub-chats (§5)  *(was S5)*
**Goal:** Branch from any node (inline tabs at the fork); a sub-chat = a branch later
re-imported & compressed back into the parent. Indexed/not-indexed as an orthogonal
archive flag.
**Approach:** Branches are the sibling `prev_id` edges already in the S2 graph;
`current_view()` follows `active_leaf_id`. UI renders inline `Branch1/Branch2` tabs at the
fork and lets the user switch the active line. Rewind/edit/expand all surface here as the
operations that create or move between branches. Sub-chat re-import reuses the S3
compression path. Add an `indexed` flag on the conversation row for archive/hide.
**Depends on:** S2 (edges), S3 (sub-chat compression). **Size:** L. **Done:** branch,
switch tabs, rewind-edit forks a branch, re-import a branch as a compressed node; archive
via un-index; qa-tester + `check.sh` green.

### Sprint 5 — Import snapshots & staleness (§3.3)  *(was S6)*
**Goal:** File imports become **static snapshots** at import time (today they re-read
live every stream — `context.py` calls `load_file` per build, ADR-0009). Drift gets a
`~` marker; `gd` shows the snapshot, `gD` the live file; **re-import forks a branch**
(the new content is genuinely different, so the conversation should diverge).
**Approach:** Store snapshot content + a source hash on the context node (the snapshot is
immutable, consistent with the append-only model — `meta` for the hash; a dedicated
column/table for the content, decided here). `build_context` reads the snapshot, not the
live file. A staleness check compares current file hash to the stored one and sets the
`~` marker. Wire `gd`/`gD` in the detail inspector / message widget.
**Depends on:** S2 (graph), S4 (re-import forks a branch). **Size:** M. **Done:** edit a
source file post-import → `~` appears, model still sees the snapshot, `gD` shows live,
re-import forks a branch with the new content; qa-tester + `check.sh` green.

### Sprint 6 — KB expansion + access & permission modes (§3, §3.1)  *(was S7)*
**Goal:** The **launch directory's files are the KB** (not just `.ctx/context/`), with
`.ignore` exclusions; plus Access modes (Isolated / Restricted / Open) and Permission
modes (Automatic / Accept).
**Approach:** Extend `Workspace.list_files`/`read_file` (`ctx/core/workspace.py`) to
walk the launch dir honoring `.ignore` (keep the existing path-traversal sandbox). Add
an access/permission policy object consulted before any search/import; Accept mode
prompts the user. Manual import always allowed regardless of mode.
**Depends on:** S5 (import-node maturity helps). **Size:** M. **Done:** KB lists repo
files minus `.ignore`; switching to Isolated blocks auto-import; Accept prompts before
import; qa-tester + `check.sh` green.

### Sprint 7 — Assistants + system prompt (§6.1)  *(was S8)*
**Goal:** An Assistant config bundles system prompt + default model/provider + default
auto-tools + default compression prompts; switching mid-conversation changes behavior,
never prior content. Closes the current gap that **no system prompt reaches the LLM**.
**Approach:** Assistant config objects (project-level on disk); the "Big S" system-
prompt node (§7.3.1) actually included by `build_context`; an assistant selector.
Reuses the compression-prompt hooks from S3.
**Depends on:** S3 (compression prompts), pairs with S8 (tools). **Size:** M. **Done:**
define an assistant, switch it, confirm system prompt reaches the model and switching
doesn't mutate prior nodes; qa-tester + `check.sh` green.

### Sprint 8 — Tools / MCP (§6.2)  *(was S9)*
**Goal:** Two-tier tool system: global registry (`~/.config/ctx/`) → project activation
→ assistant auto-invocation → manual `/` invocation. Function calling in the provider.
**Approach:** Tool registry in config; extend `Provider` (`ctx/core/provider.py`) for
tool/function-calling round-trips and render tool calls as explicit nodes; `/tool`
style manual invocation. Largest external-surface sprint.
**Depends on:** S7 (assistant invocation model). **Size:** L. **Done:** activate a
tool, assistant auto-invokes it, manual invoke works, tool nodes appear; qa-tester +
`check.sh` green.

### Sprint 9 — Multi-project + first-run wizard (§2, §2.2)  *(was S10)*
**Goal:** Restructure single flat `.ctx/` into `.ctx/<project>/` (own config,
conversations, `.ignore`); `:project init`; project chooser when several share a
directory. First-run wizard for global config + API keys at `~/.config/ctx/`.
**Approach:** Generalize `Workspace` (`ctx/core/workspace.py`) to a selected project
root under `.ctx/<name>/`; migration that moves the existing flat layout into a default
project; a launch-time chooser; a terminal setup wizard (Claude-Code-style).
**Depends on:** everything (restructures layout last, so nothing is retrofitted).
**Size:** L. **Done:** init two projects in one dir, switch between them, wizard
configures keys on a clean machine; migration preserves existing data; qa-tester +
`check.sh` green.

### Sprint 10 — Conversation graph map  *(nice-to-have, last)*
**Goal:** A bird's-eye visualization of the conversation DAG — a window/overlay showing
where the line forks (branches), where compression nodes sit (depth), and where the
active line runs — for orientation once a conversation gets deep. **Beyond the Product
Concept's spec:** the concept navigates branches via inline `Branch1/Branch2` tabs (§5)
and compression via `gd`/folding (§4.2); this map is pure convenience on top.
**Approach:** Read-only spatial render of the graph (`prev_id` forks + `compressed_into`
depth from S2); a modal/overlay you can move around in, with jump-to-node. No new data —
it's a view over the existing graph.
**Depends on:** S3 (compression) + S4 (branching) — nothing to map before they exist.
**Priority:** **lowest** — explicitly a nice-to-have. The other sprints make or break the
app; this is orientation polish. Could stay unbuilt without hurting the product.
**Size:** M–L (DAG layout in a TUI is the real cost). **Done:** open the map on a
branched, compressed conversation; forks/compression/active line are legible; jumping to
a node selects it in the main view.

---

## Out of scope (this roadmap)
- **RAG / semantic search** (embeddings, chunking, vector store, query-as-RAG, push) —
  **deferred entirely** per direction; revisit in a future planning round once S6/S7
  KB infrastructure exists.
- `<context_import>` escaping for untrusted sources (0007 #3) — fold into S7 if cheap.
- The current Ralph PRD's remaining hardening tasks (`scripts/ralph/PRD.md`) continue
  independently; this roadmap starts from a green tree.

## Verification (every sprint)
- **Unit/contract:** `scripts/check.sh` (ruff + mypy + pytest) green; new core modules
  get code-blind contract tests via the `/write-tests` pipeline. Any `StoragePort`
  change updates the `SaveCountingStorage` double in `tests/test_conversation.py`.
- **Behavioral:** the `qa-tester` subagent drives the real TUI headlessly
  (`ctx-agent` MCP) to confirm each feature end-to-end.
- **Decompose to Ralph:** turn each approved sprint into a `scripts/ralph/PRD.md` of
  small ordered tasks via the `/ralph-tasks` skill before the loop runs it.

---

## Open questions / parking lot
- **S1 — settled:** two-denominator model (local-relative per-node %, exact provider
  total), framed-per-node counting, global-ratio calibration to sum to 100%, count
  generically over `goes_to_model()` node types, `ui.weight_basis` config flag.
- **S1 — shipped (2026-06-30):** all of the above plus the `usage`-off-the-stream
  provider seam (`on_usage` callback, ADR-0015), in-conversation calibration, the header
  gauge, and the `~` estimate marker. `ui.weight_basis` defaults to `"context"`.
- **S1 — known gap (deferred, revisit as a fast-follow):** the header gauge renders
  `--%` for any model litellm has **no window metadata** for — including the default
  `openrouter/google/gemma-…` (`get_model_info` → "model isn't mapped yet", so
  `tokens.model_window` returns `None`). Per-node **%** is unaffected (pure local ratio,
  no window needed); only the absolute gauge needs the denominator. We *do* have the
  exact used-token numerator from `usage`. Candidate fixes when we pick it up: (a) a
  config-settable `model_windows` map / fallback consulted by `model_window()` — offline,
  provider-agnostic, fits the "full control" ethos; (b) render absolute used-tokens
  (e.g. `1.2k ~`) instead of `--%` when the window is unknown. _Decided to defer
  2026-06-30._
- **S2 — settled (data model):** append-only, non-destructive node graph as the single
  source of truth. Schema = `prev_id` + `compressed_into` + `active_leaf_id`, nothing
  more. **No** op-log/event-sourcing, **no** `deleted_at`/soft-delete, **no**
  `in_context`/mute flag. Reversibility = rewind/fork; per-message "delete" = rewind or
  branch; only whole-branch/conversation delete removes rows (permanent, no trash for now).
  Key invariant preserved: a node's ancestor path faithfully records what it saw.
- **S2 — rejected & why (so we don't re-litigate):**
  - *Event-sourcing / inverse-undo op-log* — the graph already *is* the history; a log
    re-stores what the structure holds.
  - *Mutable per-node `in_context`/mute toggle* — would break the ancestor-path invariant
    and require per-turn temporal versioning (re-introducing the mutable model we removed),
    for a use case already covered by rewind/branch/compression and with real
    model-confusion risk. If per-node exclusion is ever truly needed, the only
    append-only-safe form is a forward-only exclusion *marker* on the line, never a flag.
- **S2 — settled (scope):** rails + `rewind` proof op.
- **S2 — refinement notes (implementation, 2026-07-01):**
  - `ConversationCore.nodes` became a read-only `@property` returning `current_view()`
    (walk `prev_id` from `_active_leaf_id`, reversed); commands append via a private
    `_append_to_line`. UI blast radius was zero as predicted.
  - `save()` gained an `active_leaf_id` kwarg and persists the *full* graph
    (`_all_nodes()`); a sibling `get_active_leaf(cid)` reads the tip on resume
    (symmetric with `get_model`; `load()` unchanged). `persist()` passing the *view*
    instead of the full graph was the #1 correctness trap — it would delete rewound
    tails.
  - `prev_id`/`compressed_into` live as nullable `Node` dataclass fields + nodes columns.
  - `rewind(target_id)` is **core-only, pytest-verified** (no command/keybinding, no
    user-visible surface) and **rewinds to a chosen message** (target becomes the tip,
    inclusive); the abandoned tail stays in the graph/DB. No `created_seq` this sprint
    (rowid is creation order; defer to S3).
  - Migration backfill runs **once**, gated on the `active_leaf_id` column being newly
    added (not on a per-conversation NULL leaf) — else a conversation legitimately saved
    with `active_leaf_id=None` gets its `prev_id` chain rewritten on every `init()`.
  - Behavioral QA (qa-tester regression) + the code-blind `/write-tests` contract
    build-out (migration fixture, rewind, append-only-preserved, edge-field round-trip)
    are **still pending** as separate passes.
- **S3 — settled (compression model, ADR-0016 Amendment #1):** any contiguous range is
  compressible (incl. middle); compression is an immutable creation-ordered event; a
  turn's context applies only compressions created before it. Split into **3a** (safe
  tip/suffix compression + deep-dive/folding, no reconstruction needed) and **3b** (middle
  compression + preserve-info default prompt with config opt-out + per-turn reconstruction
  + the git-diff AI-node context view; middle compression and the diff ship together).
  Coherence is mitigated (default prompt) + reversible (expand/rewind), not guaranteed.
- **S4 — open:** whether an abandoned tail after a rewind is a **visible branch** or
  **discarded** (S4 behavior, does not affect the S2 schema).
- _(Add per-sprint refinement notes below as we go through each one.)_
