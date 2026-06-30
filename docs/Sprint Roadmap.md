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

**The architectural linchpin:** compression, branching, history/reversibility, and
import snapshots *all* require the same persistence change — today's flat node list
with **full-replace `save()`** (`ctx/core/storage.py:75`, DELETE-all-then-INSERT) and a
`nodes` table with no edges or soft-delete (`ctx/core/storage.py:30`) must become a
**node graph with soft-delete + an append-only operation log**. ADR-0006 #2 already
names this horizon. That redesign is the foundation everything else stacks on.

**Direction set for this roadmap:** Foundation → Compression first; RAG deferred
entirely; multi-project + first-run wizard last.

---

## Ordering rationale

1. **Token accounting** is independent of the graph, high-visibility, and *motivates*
   compression (you compress to cut token weight — you must see weight first). Cheap
   warm-up.
2. **Node-graph foundation** unblocks compression, branching, history, and snapshots —
   build it before any of them so nothing gets retrofitted.
3. **Compression + spatial nav** is the differentiator; it lands as early as the
   foundation allows.
4. **History/reversibility** is a thin layer over the op-log from S2 and the ops from S3.
5. **Branching/sub-chats** also rides the S2 graph; sub-chats specifically need
   compression (S3), so it follows.
6. **Import snapshots** need a place to store frozen content (S2 graph), then layer
   staleness/`gd`/`gD` on the existing context-node UI.
7. **KB expansion + access modes** generalize the knowledge base and gate it — a
   prerequisite shape for any future retrieval.
8. **Assistants** bundle prompt+model+tools and finally send a system prompt to the LLM.
9. **Tools/MCP** are large and benefit from the assistant invocation model (S8).
10. **Multi-project + wizard** restructure the on-disk layout; deferred so features are
    built once against single-project, then generalized.

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
**Goal:** Replace flat-list + full-replace persistence with a node graph that can
represent edges, soft-delete, and an operation log — without changing any current
user-visible behavior.
**Approach (DB redesign):**
- `nodes` table gains `parent_id` (edge), `deleted` flag (nothing is ever truly
  removed), and an explicit `position`/ordering column (stop relying on `rowid`).
- New `operations` table: append-only log (op type, target node ids, timestamp,
  payload) — the substrate for `:history` and reversal.
- Replace full-replace `save()` (`storage.py:75-121`) with incremental, edge-aware
  upserts; `load()` reconstructs the graph and the linear "current view."
- A `PRAGMA table_info` migration like the existing `_migrate` (`storage.py:66`) for
  pre-existing DBs.
- **Must update `SaveCountingStorage`** test double (`tests/test_conversation.py`) in
  the same sprint — it's the second `StoragePort` impl.
**Depends on:** S1 (none hard). **Size:** L. **Done:** all existing tests + qa-tester
flows pass unchanged; graph fields exist and round-trip; op-log records writes.
**Note:** ships no new feature by itself — it's deliberately behavior-preserving.

### Sprint 3 — Compression & spatial navigation *(the differentiator, §4)*
**Goal:** Select a message range → AI-drafts a compression node (editable before
commit) → the model sees only the compressed node; navigate compression depth.
**Approach:**
- Core: a "compress range" op that creates a compressed `Node` whose children are the
  origin nodes (soft-deleted from the linear view, preserved via edges from S2).
  `build_context` (`ctx/core/context.py`) already routes inclusion through
  `goes_to_model()` — extend so a compressed node reaches the model and its hidden
  children do not.
- Generation always AI-drafted (default project prompt / ad-hoc / manual) but
  user-editable before commit (§4.1).
- UI (Textual): range selection in Edit mode; **deep-dive** `gd`/`Ctrl+o` (full-view
  replacement + breadcrumb, §4.2); **inline folding** `zo`/`zc`/`zR`/`zM`; `:expand`
  (uncompress & destroy) and `:remove`.
**Depends on:** S2. **Size:** XL — **may split** into 3a (compression core + commit +
`build_context`) and 3b (deep-dive + folding UI). **Done:** compress a range, edit the
draft, confirm the model only sees the node (qa-tester via context inspection);
`gd`/`zo`/`zM` behave per §4.2; `check.sh` green.

### Sprint 4 — History log & reversibility (§4.3)
**Goal:** `:history` shows the full operation log; selective reversal of any op;
nothing truly deleted.
**Approach:** Read/replay the `operations` table from S2; a history modal screen
(pattern: `history_screen.py`); reversal applies the inverse op against the graph.
**Depends on:** S2 (op-log), S3 (gives meaningful ops to reverse). **Size:** M.
**Done:** ops appear in `:history`; reverting a compression restores the range;
qa-tester confirms; `check.sh` green.

### Sprint 5 — Branching & sub-chats (§5)
**Goal:** Branch from any node (inline tabs at the fork); a sub-chat = a branch later
re-imported & compressed back into the parent. Indexed/not-indexed as an orthogonal
archive flag.
**Approach:** Branches are sibling edges off a fork node in the S2 graph; `load()`
resolves the active branch path. UI renders inline `Branch1/Branch2` tabs at the fork.
Sub-chat re-import reuses the S3 compression path. Add an `indexed` flag on the
conversation row.
**Depends on:** S2 (edges), S3 (sub-chat compression). **Size:** L. **Done:** branch,
switch tabs, re-import a branch as a compressed node; archive via un-index; qa-tester +
`check.sh` green.

### Sprint 6 — Import snapshots & staleness (§3.3)
**Goal:** File imports become **static snapshots** at import time (today they re-read
live every stream — `context.py` calls `load_file` per build, ADR-0009). Drift gets a
`~` marker; `gd` shows the snapshot, `gD` the live file; manual re-import to refresh.
**Approach:** Store snapshot content + a source hash on the context node (room added in
S2). `build_context` reads the snapshot, not the live file. A staleness check compares
current file hash to the stored one and sets the `~` marker. Wire `gd`/`gD` in the
detail inspector / message widget.
**Depends on:** S2 (storage for snapshots). **Size:** M. **Done:** edit a source file
post-import → `~` appears, model still sees the snapshot, `gD` shows live, re-import
updates; qa-tester + `check.sh` green.

### Sprint 7 — KB expansion + access & permission modes (§3, §3.1)
**Goal:** The **launch directory's files are the KB** (not just `.ctx/context/`), with
`.ignore` exclusions; plus Access modes (Isolated / Restricted / Open) and Permission
modes (Automatic / Accept).
**Approach:** Extend `Workspace.list_files`/`read_file` (`ctx/core/workspace.py`) to
walk the launch dir honoring `.ignore` (keep the existing path-traversal sandbox). Add
an access/permission policy object consulted before any search/import; Accept mode
prompts the user. Manual import always allowed regardless of mode.
**Depends on:** S6 (import-node maturity helps). **Size:** M. **Done:** KB lists repo
files minus `.ignore`; switching to Isolated blocks auto-import; Accept prompts before
import; qa-tester + `check.sh` green.

### Sprint 8 — Assistants + system prompt (§6.1)
**Goal:** An Assistant config bundles system prompt + default model/provider + default
auto-tools + default compression prompts; switching mid-conversation changes behavior,
never prior content. Closes the current gap that **no system prompt reaches the LLM**.
**Approach:** Assistant config objects (project-level on disk); the "Big S" system-
prompt node (§7.3.1) actually included by `build_context`; an assistant selector.
Reuses the compression-prompt hooks from S3.
**Depends on:** S3 (compression prompts), pairs with S9 (tools). **Size:** M. **Done:**
define an assistant, switch it, confirm system prompt reaches the model and switching
doesn't mutate prior nodes; qa-tester + `check.sh` green.

### Sprint 9 — Tools / MCP (§6.2)
**Goal:** Two-tier tool system: global registry (`~/.config/ctx/`) → project activation
→ assistant auto-invocation → manual `/` invocation. Function calling in the provider.
**Approach:** Tool registry in config; extend `Provider` (`ctx/core/provider.py`) for
tool/function-calling round-trips and render tool calls as explicit nodes; `/tool`
style manual invocation. Largest external-surface sprint.
**Depends on:** S8 (assistant invocation model). **Size:** L. **Done:** activate a
tool, assistant auto-invokes it, manual invoke works, tool nodes appear; qa-tester +
`check.sh` green.

### Sprint 10 — Multi-project + first-run wizard (§2, §2.2)
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
- **S2 visibility:** Sprint 2 ships no user-visible feature (pure groundwork, de-risks
  S3–S6). Alternative: merge S2 + S3a so the foundation lands *with* the first
  compression slice. _(To decide during S2 refinement.)_
- _(Add per-sprint refinement notes below as we go through each one.)_
