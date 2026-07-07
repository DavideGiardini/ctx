# AGENTS.md

## Environment
- Python >=3.11, managed with `uv` (`uv.lock` committed).
- Build backend: `hatchling`.
- Quality tooling: `ruff` + `mypy` + `pytest` (scaffolded) and GitHub Actions CI — see "Quality checks".

## Dependencies
- Install: `uv sync`
- Entry point declared in `pyproject.toml`: `ctx = "ctx.main:run"`
- Runtime deps: `textual`, `litellm`

## Run the app
- `uv run ctx` (or `uv run python -m ctx.main`)
- Requires a `.env` with `OPENROUTER_API_KEY` (or other litellm-supported API key env var). The app itself does not load `.env`; litellm reads the env directly.

## Workspace
- Each working directory gets a local `.ctx/` folder created at runtime.
- `.ctx/conversations.db` — SQLite (WAL mode) for chat history.
- `.ctx/context/` — drop text files here; use the `/include` command in-app to inject them into the conversation as `<context_import>` XML.
- Both are gitignored by default.

## App behavior
- Switch models at runtime with `/model <model>`.
- Commands: `/new`, `/resume`, `/include`, `/model`.
- Logs written to `~/.local/state/ctx/ctx.log`.
- User config (colors) lives in `~/.config/ctx/config.json`.

## Architecture
Layered: `core/` is framework-free domain logic (zero `textual` imports), `ui/` is
a thin Textual adapter over it, `models/` holds shared types. `ctx/main.py` is a
tiny entry point. The headless QA tooling lives in the top-level `tools/agent/`
package — deliberately **outside** the shippable `ctx` package so it can never
reach end users (ADR 0012). See `docs/decisions/` for *why* it's shaped this way.

**core/** (no `textual` imports)
- `conversation.py` — `ConversationCore`: owns conversation state (an append-only
  node graph, model, id/title) plus the command + streaming lifecycle. State is a
  `_graph: dict[str, Node]` of *all* nodes (active line + abandoned tails + future
  compression children) keyed by id, plus an `_active_leaf_id` tip; `current_view()`
  walks `prev_id` from the tip to project the linear list, and the read-only `nodes`
  property returns that projection so the UI/token-accounting see today's shape
  unchanged (ADR 0016). Commands append via `_append_to_line` (never by mutating
  `nodes`); `persist()` saves the *full* graph (`_all_nodes()`) + tip so a rewind's
  tail survives (append-only). `rewind(target_id)` moves the tip back to a node on
  the active line (non-destructive; core-only proof op). The compression lifecycle
  (ADR-0016, S3) is core-only too: `current_view()` folds each maximal run of an
  applying `K`'s children into that `K` by **event enumeration** (`_active_folds`
  — a `K` applies iff no `E` targets it and `K.meta["range"]` ⊆ the line; child
  `compressed_into` pointers are never read at runtime, A#3 §3, task 15);
  `commit_compression(start, end, summary, prompt)`
  builds `K` (validated by `_validate_compress_range` — no streaming, contiguous view
  slice, flat; the 3a tip guard was deleted in task 22 so a middle range folds too,
  the reconstruction path carrying the honesty the guard provided, Q5) and sets the
  children's `compressed_into`;
  `expand_compression(k_id)` is its non-destructive inverse — appends an off-line
  `Node.expand` event `E`, clears the folded children's pointers, and keeps `K` as an
  orphan (never row-deleted). `draft_compression(start, end, prompt=None)` is the
  AI-assisted counterpart to the pure `commit_compression`: same `_validate_compress_range`,
  then it renders *only the range* via `build_context` (so each node contributes its
  model-facing form, Q10c), appends one final user message carrying the instruction
  (`prompt` or the `DEFAULT_COMPRESSION_PROMPT` constant, ADR-0016 A#1), and streams the
  draft with a **no-op `on_usage`** so the gauge is never anchored (Q10b) — it mutates no
  state and commits nothing (Q3). `folded_children(k_id)` returns a K's folded originals
  ordered by `K.meta["range"]` (`[]` for an unknown/non-compression id) — the children are
  off-view, so this is how the UI reaches them for the committed-K inspector (Q8). The
  read-only `streaming` flag (set in `submit()` when the turn's `created_seq` is
  stamped, cleared in `stream()`'s `finally`; reset on `new`/`resume`) gates all
  three compression ops across the whole in-flight window, closing the
  submit→first-tick gap (H2, ADR-0016 A#3 §2, task 28). Takes a `Provider`, a
  `StoragePort`, and a `Workspace` by injection (ADR 0001). Exposes a `read_file`
  property — the very loader it hands `build_context` — so the UI's token
  accounting renders nodes exactly as the model sees them without reaching past
  the core into the workspace. The read-only `all_nodes()` accessor (over
  `_all_nodes()`) hands the UI the whole graph the `reconstruction` oracles need
  (drift/diff resolve as-of and now-view folds over every node, not the active
  line `nodes` projects). `stream` also anchors the header gauge: it measures
  the local token sum of the context it sends (`tokens.count_messages`) and hands
  the provider an `on_usage` callback; a reported `Usage` that passes a sanity check
  (`prompt_tokens > 0`, positive local sum, within `CALIBRATION_TOLERANCE`× of it)
  sets the read-only `last_usage`/`calibration` (= `prompt_tokens / local_sum`)
  accessors and bumps a monotonic `usage_generation` counter, otherwise all three
  are left unchanged so a trusted anchor survives a bogus or usage-less turn. The
  UI samples `usage_generation` before/after a turn to detect a fresh anchor without
  depending on the provider minting a new `Usage` object each turn (ADR 0015 #2).
- `provider.py` — `Provider` protocol (`stream()`, `check_connectivity()`) with
  adapters `LiteLLMProvider` (real) and `TestProvider` (canned, no network) (ADR 0002).
  `LiteLLMProvider.stream` passes a finite `STREAM_TIMEOUT` to the backend and maps
  any backend failure (request-time or mid-stream) to the domain error `ProviderError`
  so litellm types never leak through the seam; `CancelledError`/`GeneratorExit`
  (BaseException) pass through unwrapped (ADR 0011 #1). `stream` also takes an optional
  out-of-band `on_usage: Callable[[Usage], None]`: when the provider reports exact token
  counts it fires `on_usage` exactly once with a `Usage(prompt_tokens, completion_tokens,
  total_tokens)`, keeping the stream plain `str` (ADR 0015). `LiteLLMProvider` requests
  `stream_options={"include_usage": True}` and guards the chunk loop so the final
  empty-`choices` usage chunk can't `IndexError`; `TestProvider(tokens, usage=None)` fires
  the canned `usage` after its tokens (default `None` keeps the `test_provider` fixture green).
- `storage.py` — `StoragePort` protocol + `ConversationRepository(db_path)`
  encapsulating all SQLite (WAL) schema/serialization (ADR 0003). Persists the
  append-only graph (ADR 0016): `nodes.prev_id`/`nodes.compressed_into` edge columns
  + `conversations.active_leaf_id` + `nodes.created_seq` (the A#2 creation-order oracle);
  `save(..., active_leaf_id=)` writes the full node set (incl. each `created_seq`) and
  the tip; `get_active_leaf(cid)` reads it back (symmetric with `get_model`).
  `_migrate` chains pre-graph flat DBs into the degenerate single-path case by rowid,
  once, when the `active_leaf_id` column is first added; a separate once-only
  `_backfill_created_seq` (gated on the `created_seq` column being absent) assigns
  per-conversation 1-based `created_seq`s in rowid order.
- `context.py` — pure `build_context(nodes, load_file)` → litellm message list;
  expands `context` nodes via the injected loader, no I/O of its own (ADR 0004).
  Renders a `compression` node as a user-role `<conversation_summary>` wrapper (no
  preamble, ADR-0016 H6/Q2) that coalesces with adjacent user content like an import;
  a dropped node (system) is a coalescing boundary (user runs on either side don't merge).
- `reconstruction.py` — pure, read-only per-turn context reconstruction over a flat
  node list, **never on the live pipeline** (ADR-0016 A#2/A#3): `context_at_generation`
  (what turn `T` saw, as-of `created_seq(K) < created_seq(T)`) / `now_prefix` (the same
  ancestor prefix folded under today's events) / `has_drift` (their id-sequences differ);
  all resolve by **event enumeration** over `K`/`E` nodes, never child pointers.
  `hash_context` is the canonical `build_context`-message digest stamped on each turn's
  `meta["ctx_hash"]` at generation (the A#3 §4 tripwire). `diff_regions` block-aligns
  `context_at_generation` vs `now_prefix` **by node id** (`difflib`) into contiguous
  `DiffRegion`s (`changed` flag; H6 structural diff, never content); `reconstruction_warning`
  recomputes the hash and returns `True` on a missing/mismatched `ctx_hash` (feeds the
  diff view's honesty banner). Imports only `Node` + the sibling `build_context` (task 20).
- `tokens.py` — pure, stateless token accounting for the context-budget UI (no
  Protocol seam — single impl). `count_messages` (the sole home of litellm's
  `token_counter`/tiktoken fallback), `per_node_tokens` (per-node local estimate,
  each node rendered in isolation via `build_context` so a context node counts its
  resolved file body; `0` when not `goes_to_model()`), `weight_pct` (per-node
  `"context"`/`"window"`-basis %, a *local provider-agnostic ratio* — no calibration
  arg; `0`-token nodes → `None`), `gauge(local_total, max_input_tokens, calibration)`
  → `(pct, approximate)` (absolute used÷window, scaled by an optional provider
  calibration; `approximate=True` whenever `calibration is None`; pct unclamped),
  `model_window` (wraps `get_model_info`, unknown model → `None`, never raises).
- `workspace.py` — `Workspace(root_path)`: `.ctx/` discovery, `ensure()`,
  `list_files()`, `read_file()`; the sole `Path.cwd()` lives at its call site (ADR 0005).
  `list_files` classifies a file as text by a **bounded ~8 KB sniff** (`SNIFF_BYTES`):
  no NUL byte + UTF-8-decodable prefix (incremental decode, so a multi-byte char split
  at the boundary isn't a false negative) — no extension allowlist, so `Dockerfile`/`LICENSE`
  pass. It also applies `read_file`'s containment guard (`resolve()` + `is_relative_to`),
  so a symlink escaping the sandbox is never listed and the picker can't surface a file
  the reader would reject (ADR 0008 #1/#2).
- `config.py` — `~/.config/ctx/config.json` merged over defaults (`model` — the
  user-overridable default LLM model, read once by `ConversationCore` at
  construction; `colors`; `ui.truncation_lines` — per-role node line caps; `"auto"`
  disables; `ui.weight_basis`; `ui.show_context_drift` — bool, default `True`,
  non-bool coerced back to the default; `compression.default_prompt` — the
  preserve-info fallback, the single source of the `DEFAULT_COMPRESSION_PROMPT`
  constant re-exported by `conversation.py`, the editor's Top prefill reads the
  user-overridable value, ADR-0016 A#1). `log.py` — file logging to
  `~/.local/state/ctx/ctx.log`.

**ui/** — dual-pane "conversation IDE" shell (Product Concept §7): docked
`AppHeader` (top) / `AppFooter` (bottom), a permanent `Horizontal#body` split with
a left `DetailInspector` and a right `#conversation` pane (the `MessageList` +
`InputBar` live inside it).
- `app.py` — `ChatApp`: Textual app and composition root. Constructs the core's
  dependencies; owns widgets, focus, Insert/Edit mode-switching (`_set_mode`),
  keybindings, selection→inspector wiring, and the `@work` streaming worker (which
  feeds both the truncated right-pane node and, when locked, the full left-pane
  stream). `describe_state()` exposes observable state for snapshots (incl.
  `last_hint`, the most-recent transient hint). Transient UI hints (refusals,
  "nothing to include") route through `_hint` → `self.notify()` — a toast, never
  a graph node, so they don't accumulate across `/new`/`/resume` (task 42); only
  *durable* breadcrumbs (`/model` changes, connectivity notices) stay persistent
  `core.add_system_message` nodes (ADR 0006 #6). Per-node
  weight %s come from `tokens.weight_pct` (basis from `ui.weight_basis`, window
  from `tokens.model_window`) via `_node_weights()`, which both `describe_state`
  and `_refresh_token_ui` read. The header gauge comes from `_gauge_state()`
  (`tokens.gauge` of the full context's `count_messages`, window from
  `tokens.model_window`, calibration from `core.calibration`); it is `approximate`
  (`~`) when there is no calibration yet *or* the node set drifted from
  `_gauge_anchor` — the signature (`_node_signature`) captured at stream-complete
  whenever a turn bumped `core.usage_generation` (i.e. adopted fresh `usage`). `describe_state()` emits both per-node
  `weight_pct` and a `context_gauge` `{pct, approximate}`. `_refresh_token_ui`
  pushes the per-node %s onto the mounted `MessageWidget`s and the gauge onto the
  `AppHeader` after every node-list/content change (submit, stream-complete,
  `/include`, `/resume`, `/new`). The single drift predicate is `_turn_has_drift(node, all_nodes)`: `False`
  for non-assistant roles and for *every* node when `ui.show_context_drift` is
  off (the flag gates *all* drift UI, task 24). `_node_drift()` (parallel to
  `core.nodes`, read
  by both `describe_state` and `_refresh_token_ui`) flags each **assistant** turn
  whose generation context has drifted from the now-view — `reconstruction.has_drift`
  over `core.all_nodes()`, gated by `ui.show_context_drift`; other roles/off = `False`.
  `describe_state()` emits it as each node's `"drift"`, and `MessageWidget.set_drift`
  renders a subtle `Δ` marker (task 19). The `g d` chord (`on_key` → `_drill_selected`)
  drills into the selected node: a `compression` K deep-dives (task 12), a **drifted
  assistant** turn opens the full-pane context diff (`_enter_diff`, task 20) — one
  navigation family (Q12); the diff branch shares `_turn_has_drift`, so with drift
  display off `g d` is a no-op on a drifted turn while a K still deep-dives (task 24). Diff state lives in `_diff_view` (mutually exclusive with
  the deep-dive stack): `_enter_diff` block-aligns `reconstruction.diff_regions`
  (`context_at_generation` left ⟷ `now_prefix` right) and runs the H4 tripwire
  (`reconstruction.reconstruction_warning`) to toggle the "reconstruction may be
  inexact" banner; `up`/`down` move a region cursor. `Enter` (`action_detail_enter`,
  routed through `_drill_diff_region`) drills into the cursored changed region —
  `_diff_view["drill"]` holds that `DiffRegion` and `DiffView.show_drill` renders its
  left/right block sequences in full (H6 many-to-many, task 21). `Esc`/`Ctrl+o` pop
  one level (drill → overview → live via `_close_drill`/`_close_diff`), `i` exits
  fully. `describe_state()` gains `"diff_view"`
  `{open, regions: [{left, right}] (changed only), warning, drill: {left, right} | None}`
  and the unified breadcrumb appends "Diff …" then "Region" while drilled (task 20/21).
- `widgets/` — `MessageRow` (`message_row.py`, task 36) is the single shared
  compact-row renderer: takes a `Node`, draws the role-colored left bar
  (palette), truncation, the right-docked drift `Δ` + weight meta slot, and the
  content (Markdown for turns, Static for system/context); sets no id unless the
  caller supplies one, so the same node can appear in more than one pane. The
  colored bar lives on an inner `.row-body` wrapper (around the meta slot +
  content), not the outer row — so a range selection's grey bridge padding (on
  the outer row) has no bar bleeding through the gap (task 49); `_row_body()`
  is the seam both `on_mount` and `MessageWidget._refresh_border` set the bar on. The
  conversation `MessageList`/`MessageWidget` (`MessageWidget` subclasses
  `MessageRow`, adding the list's cursor/range selection, pass margins, and
  `msg-<id>` id; shared CSS targets the `MessageRow` type selector so it cascades
  to the subclass) renders through it — the shared surface the diff view and
  inspector splits adopt in tasks 37/38,
  `DetailInspector` (reactive `show(NodeView)`; standard Markdown view vs. 3-split
  context view, empty splits hidden — a `context` node labels the splits
  Prompt/Content/Output, a `compression` K reuses the same split machinery
  (browse/maximize/`1`/`2`/`3`) labelled Prompt/Originals/Summary, the app mapping
  K→NodeView via `core.folded_children`, task 10),
  `CompressionEditor` (left-pane 2-split draft editor — editable prompt + summary
  `TextArea`s, no Center; shown in place of the inspector while drafting a
  compression, cancels for free on Esc, ADR-0016 Q4; opened by `c` in Edit mode
  on an active selection — `x` expands the selected K, both Edit-mode keys, never
  slash commands, ADR-0016 A#5, task 13b),
  `DiffView` (full right-pane replacement rendering a turn's context-drift block
  diff — left/right block columns aligned by node id, a changed-region cursor
  (`move_cursor`), a reconstruction-inexact warning banner, and a `#diff-drill`
  overlay (`show_drill`/`close_drill`) that isolates one region's full block
  sequences; shown in place of the `MessageList` while `_diff_view` is open,
  task 20/21. Its four panes are `_SyncedScroll`s, scroll-locked per pair
  (overview left⟷right, drill left⟷right): a scroll of one mirrors onto its
  `partner` (re-entrancy-guarded) and `set_cursor` scrolls **both** panes to the
  cursored region — kept aligned by the task-50 equal-height rows, task 51),
  `AppHeader` (title /
  logo / context-window gauge — `set_context_pct(pct, approximate)` renders a
  filled bar and a leading `~` when the figure is only an estimate; `--%` when
  the window is unknown),
  `AppFooter` (mode-driven keybinding hints + model; the Edit-mode hint is
  contextual — `set_selection(node_type, drifted)` surfaces `x Expand` only on a
  K and `g d Drift` only on a drifted turn, fed by `_sync_footer`, task 43c),
  `InputBar` (command
  suggest/cycle), `IncludeScreen` (file-picker modal), `HistoryScreen`
  (conversation picker). CSS split across `app.css` and `widgets/*.css` plus
  widget `DEFAULT_CSS`.

**models/** — `nodes.py`: the `Node` dataclass (one chat turn or context reference),
carrying append-only graph edges `prev_id` (predecessor on the line; `None` = root;
shared `prev_id` = branch siblings) and `compressed_into` (the compression node that
folds it; `None` until S3) — both default `None`, so the factories are unchanged
(ADR 0016). It also carries `created_seq: int = 0`, the monotonic creation order the
core stamps at graph-insertion time (`_next_seq` = max over the whole graph + 1, never
reassigned; the 3b event-enumeration oracle, ADR-0016 A#2/H6). Factory classmethods (`Node.user`/`.assistant`/`.system`/`.context`/`.compression`/`.expand`)
are the single source of truth for each kind's `role`/`node_type`/`content`/`meta`/
`conversation_id` combination — call sites construct via these, not the bare dataclass
(ADR 0014 #1). `Node.compression(summary, conversation_id, range_ids, prompt="")` builds
an off-line K node (`role`/`node_type` both `"compression"`, `content=summary`,
`meta={"prompt", "range": [child ids]}` — canonical H1 keys, ADR-0016 A#2).
`Node.expand(target_id, anchor_id, conversation_id)` builds the off-line E *event* node
that undoes a compression (`role`/`node_type` both `"expand"`, empty content, never
reaches the model, `meta={"target": K.id, "anchor": <leaf at expand time>}` — H5). `Node.system(content, conversation_id="")` takes an optional
`conversation_id`: a breadcrumb raised inside an active conversation carries it and so
persists (model-change/connectivity notices reappear on resume — uniform-persistence
policy, ADR 0006 #6); one raised with no active conversation defaults to `""` and stays
session-local, because storage skips id-less nodes. The
`Node.goes_to_model()` predicate is the single definition of "which nodes reach the
LLM" (user/assistant turns or `node_type` in `{"context", "compression"}`);
`build_context` routes its
inclusion decision through it rather than re-deriving role rules inline (ADR 0014 #1).

**tools/agent/** (top-level, OUTSIDE the `ctx` package — never ships, ADR 0012) —
headless QA tooling (see "Agent-driven testing"): `snapshot.py`, `harness.py`,
`mcp_server.py`. It may import *from* `ctx` (tooling → product); `ctx` must never
import *from* `tools`.

### Non-obvious behaviors
- `/include` stores a `Node(node_type="context")` with `meta["source_path"]`;
  `build_context` wraps file contents in `<context_import>` XML merged into the
  next user message at stream time.
- `ConversationRepository.save` replaces *all* nodes for a conversation id (with the
  full graph — every line + folded child — not just the active view).
- `check_connectivity` fires a single-token probe to confirm a model is reachable.

## Designing new modules
This codebase is built on a deep-module philosophy (see `docs/decisions/` for the
ADRs that established it). Hold new code to the same bar:

- **Prefer deep modules** — a simple interface hiding substantial implementation.
  If a module's interface is about as complex as its implementation, it is
  shallow; fold it into its caller or deepen it.
- **The interface is the test surface.** Design the public interface so behavior
  can be exercised through it. Don't extract a pure function *only* to test it
  while the real bug lives in how it's called — keep logic where it has locality.
- **Keep core logic framework-free.** `ctx/core/*` has zero `textual` imports;
  the UI (`ctx/ui/*`) is a thin adapter over it. New domain logic goes in `core`.
- **Inject a Protocol seam only when a second real implementation exists.** One
  adapter is a hypothetical seam; two is a real one. Examples that earned their
  seam: `Provider`/`TestProvider` (`ctx/core/provider.py`), `StoragePort` +
  `ConversationRepository` (`ctx/core/storage.py`), injected `Workspace`.
- **Apply the deletion test before adding an abstraction.** Would deleting it
  concentrate complexity (good — it's pulling its weight) or just scatter it
  (don't add it)?

### Comments: sparse anchors, not narration
Comments rot, and a repo full of long comments trains the next agent to write
more of them. Keep them sparse and short; let the code, types, and docstrings
carry the obvious, and let ADRs carry the *why*.

- **Don't restate the code, type, or docstring.** If a reader learns nothing the
  signature/body already shows, delete the comment.
- **Don't re-argue a settled decision inline.** The rationale lives in an ADR
  (`docs/decisions/`) or in this file — reference it (`(ADR 0016)`) instead of
  duplicating the argument, which just creates a second copy to keep in sync.
- **Comment only the genuinely tricky or bug-prone.** The spots that are
  confusing, subtly ordered, or easy to break "wrong" earn a line — e.g. *persist
  the full graph, not the view, else rewind turns destructive*; *gate the backfill
  on the column, not a per-conversation NULL leaf*.
- **Anchor those with `AIDEV-NOTE:` / `AIDEV-TODO:` / `AIDEV-QUESTION:`** (≤120
  chars). They're greppable, and the prefix signals to future agents: this note
  guards something subtle — don't delete it without cause.
- **Durable rationale goes in ADRs / this file, not inlined.** Code points *to*
  the reasoning; it doesn't re-type it.

**Keep this file current.** Whenever you change the architecture — add/remove/rename
a module, move a responsibility across the core/ui seam, change a module's
interface, or introduce a new seam — update the `## Architecture` map (and its
`### Non-obvious behaviors`) in the same change so it never goes stale. For a
decision worth not re-litigating, add an ADR in `docs/decisions/`. A diff that
reshapes the architecture without touching this file is incomplete.

For deeper refactors, run the `/improve-codebase-architecture` skill.

## What `ctx` is

A terminal chat application that streams LLM responses via `litellm`. It supports model switching, context file inclusion, conversation persistence, and a two-mode UI (insert vs. edit). Built on `textual`.

## Quality checks
The gate (run before every commit; CI and the Ralph loop call it too):
- `bash scripts/check.sh` — ruff + mypy + pytest in one shot.
Individually: `uv run ruff check .` (add `--fix` to auto-fix), `uv run mypy .`,
`uv run pytest`. A deterministic Pilot-driven test layer is the required next
step — see `tests/README.md`. Install the local hook with `uv run pre-commit install`.

## Agent-driven testing (headless)
The real app can be driven and observed without a terminal or screenshots, via the
`ctx-agent` MCP server (`tools/agent/mcp_server.py`, auto-discovered from `.mcp.json`).
It drives a deterministic `HarnessApp` (`tools/agent/harness.py` — `TestProvider` +
temp workspace) and exposes `ctx_snapshot`, a ~100-token semantic state read,
alongside `textual-mcp-server`'s keyboard/observation tools.

**Default to delegating behavioral QA to the `qa-tester` subagent** (modes:
stress-test / verify-fix / verify-feature). It owns the launch flow, the
snapshot→act→snapshot→check-errors loop, and the key bindings, and keeps that
token-heavy traffic out of your context. Drive the MCP tools yourself only for a
quick one-off check.

**Two harness limits to design around:**
- *It runs the app in-process.* The MCP server imports `ctx.*` once and caches it in
  `sys.modules`; relaunching the app (`textual_stop` + `textual_launch`) does **not**
  reload edited code. Source you change in a session is invisible to the harness until
  the **server process** restarts. So never edit code and UI-verify it in the same
  session — verify in a later Ralph iteration (a fresh `claude -p` gets a fresh server)
  or, interactively, after a `/mcp` reconnect of `ctx-agent`.
- *It can't see layout.* `textual_snapshot`/`textual_query` carry no computed margins
  and `textual_screenshot` is an unreliable character grid, so the harness cannot judge
  vertical spacing, margins, or pixel-level layout. Assert on queryable state (CSS
  classes, content, `ctx_snapshot` fields); put layout/spacing invariants in unit
  tests, not in `qa-tester`.

> Dependency note: `textual-mcp-server` 1.0.0 pins `textual<8` conservatively;
> `[tool.uv] override-dependencies` keeps the app on textual 8 while reusing the
> library. Run the server manually with `uv run python -m tools.agent.mcp_server`
> if needed (it is intentionally not a console script — see ADR 0012).

## What to avoid
- Do not weaken the gate to make it pass; fix what `scripts/check.sh` reports.
- Do not commit `.ctx/` or `.env`; they are gitignored.
- Do not modify `uv.lock` by hand; use `uv sync` / `uv add` / `uv remove`.

## Interaction modes
- **Default — autonomous engineer**: implement complete logical changes, run
  `scripts/check.sh`, and self-verify behavior via the `qa-tester` subagent before
  reporting; read `docs/decisions/` before reopening settled design.
- **`/professor`** — opt-in slow, teaching, one-unit-per-turn pairing style.
