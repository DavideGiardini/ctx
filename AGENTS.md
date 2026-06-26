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
- `conversation.py` — `ConversationCore`: owns conversation state (nodes, model,
  id/title) plus the command + streaming lifecycle. Takes a `Provider`, a
  `StoragePort`, and a `Workspace` by injection (ADR 0001).
- `provider.py` — `Provider` protocol (`stream()`, `check_connectivity()`) with
  adapters `LiteLLMProvider` (real) and `TestProvider` (canned, no network) (ADR 0002).
- `storage.py` — `StoragePort` protocol + `ConversationRepository(db_path)`
  encapsulating all SQLite (WAL) schema/serialization (ADR 0003).
- `context.py` — pure `build_context(nodes, load_file)` → litellm message list;
  expands `context` nodes via the injected loader, no I/O of its own (ADR 0004).
- `workspace.py` — `Workspace(root_path)`: `.ctx/` discovery, `ensure()`,
  `list_files()`, `read_file()`; the sole `Path.cwd()` lives at its call site (ADR 0005).
- `config.py` — `~/.config/ctx/config.json` merged over defaults (`model` — the
  user-overridable default LLM model, read once by `ConversationCore` at
  construction; `colors`; `ui.truncation_lines` — per-role node line caps; `"auto"`
  disables). `log.py` — file logging to `~/.local/state/ctx/ctx.log`.

**ui/** — dual-pane "conversation IDE" shell (Product Concept §7): docked
`AppHeader` (top) / `AppFooter` (bottom), a permanent `Horizontal#body` split with
a left `DetailInspector` and a right `#conversation` pane (the `MessageList` +
`InputBar` live inside it).
- `app.py` — `ChatApp`: Textual app and composition root. Constructs the core's
  dependencies; owns widgets, focus, Insert/Edit mode-switching (`_set_mode`),
  keybindings, selection→inspector wiring, and the `@work` streaming worker (which
  feeds both the truncated right-pane node and, when locked, the full left-pane
  stream). `describe_state()` exposes observable state for snapshots.
- `widgets/` — `MessageList`/`MessageWidget` (truncated nodes via per-role
  `max-height`, right-docked weight slot, conversation-pass margins),
  `DetailInspector` (reactive `show(NodeView)`; standard Markdown view vs. 3-split
  Prompt/Content/Output context view, empty splits hidden), `AppHeader` (title /
  logo / context-% gauge — gauge is a placeholder pending token counting),
  `AppFooter` (mode-driven keybinding hints + model), `InputBar` (command
  suggest/cycle), `IncludeScreen` (file-picker modal), `HistoryScreen`
  (conversation picker). CSS split across `app.css` and `widgets/*.css` plus
  widget `DEFAULT_CSS`.

**models/** — `nodes.py`: the `Node` dataclass (one chat turn or context reference),
plus factory classmethods (`Node.user`/`.assistant`/`.system`/`.context`) that are the
single source of truth for each kind's `role`/`node_type`/`content`/`meta`/
`conversation_id` combination — call sites construct via these, not the bare dataclass
(ADR 0014 #1). Note `Node.system` carries no `conversation_id` by design, so storage
skips it (system breadcrumbs are session-local notices, not durable turns). The
`Node.goes_to_model()` predicate is the single definition of "which nodes reach the
LLM" (user/assistant turns or `node_type == "context"`); `build_context` routes its
inclusion decision through it rather than re-deriving role rules inline (ADR 0014 #1).

**tools/agent/** (top-level, OUTSIDE the `ctx` package — never ships, ADR 0012) —
headless QA tooling (see "Agent-driven testing"): `snapshot.py`, `harness.py`,
`mcp_server.py`. It may import *from* `ctx` (tooling → product); `ctx` must never
import *from* `tools`.

### Non-obvious behaviors
- `/include` stores a `Node(node_type="context")` with `meta["source_path"]`;
  `build_context` wraps file contents in `<context_import>` XML merged into the
  next user message at stream time.
- `ConversationRepository.save` replaces *all* nodes for a conversation id.
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
