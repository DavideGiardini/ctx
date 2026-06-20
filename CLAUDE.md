# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- Run the app: `uv run ctx` (or `uv run python -m ctx.main`)
- Install/sync deps: `uv sync` — never edit `uv.lock` by hand; use `uv add` / `uv remove`
- Lint: `uv run ruff check .` (auto-fix: `uv run ruff check --fix .`)
- Type check: `uv run mypy .`
- There is **no test suite, formatter, or CI**. Do not run `pytest`. Ad-hoc scratch scripts (`test_fake_context.py`, `debug_bindings3.py`) exist at the repo root but are not a real suite.

Running the app requires a `.env` with `OPENROUTER_API_KEY` (or another litellm-supported key). The app does **not** load `.env` itself — litellm reads the environment directly, so the key must already be exported (or sourced) in the shell.

## Architecture

`ctx` is a terminal LLM chat client built on **Textual**, streaming responses via **litellm**. The design is ports-and-adapters around a single deep core module.

**`ConversationCore` (`ctx/core/conversation.py`) is the heart of the app.** It owns all conversation state (the `nodes` list, conversation id/title, active model) and every command's logic (`submit`, `stream`, `new_conversation`, `resume_conversation`, `include_files`, `set_model`, `check_connectivity`). It depends only on three Protocol "seams", so it has no direct knowledge of litellm, SQLite, or the filesystem:

- `Provider` (`ctx/core/provider.py`) — LLM streaming seam. `LiteLLMProvider` is the real adapter; `TestProvider` yields canned tokens. `stream()` yields `StreamChunk(token, usage)`; the final chunk carries `usage` (completion-token count).
- `StoragePort` (`ctx/core/storage.py`) — persistence seam. `ConversationRepository` is the SQLite adapter (WAL mode, FKs on). `save()` replaces *all* nodes for a conversation id in one transaction. Node `meta` is stored as a JSON column, so new fields need no schema migration.
- `Workspace` (`ctx/core/workspace.py`) — per-directory `.ctx/` discovery and file reading. Each working directory gets its own `.ctx/conversations.db` and `.ctx/context/`.

**The UI layer (`ctx/ui/app.py`, `ChatApp`) is a thin Textual shell over `ConversationCore`.** It wires the seams together, runs `stream()` inside a Textual `Worker` (so the UI stays responsive), and translates between UI events and core method calls. Keep business logic in the core, not in widgets.

**The `Node` model (`ctx/models/nodes.py`) is the universal unit.** Every chat turn, system prompt, context import, and app message is a `Node`. Two orthogonal fields matter:
- `role` — `user` / `assistant` / `system` / `context` / `application`. Crucial distinction: `role="system"` is reserved for the *single root LLM system prompt* ("Big S"); `role="application"` is for UI-only status messages (model switches, connectivity, "new conversation") and is **never sent to the LLM**.
- `node_type` — `"chat"` vs `"context"`, controlling how `build_context` expands the node.
- Context nodes store their data in `meta` (`source_path`, `prompt`, `raw_content`, `output`), surfaced via `@property` accessors on `Node`. `token_count` is also stored in `meta`.

**`build_context` (`ctx/core/context.py`) is the pure node→LLM-messages translator.** It is intentionally side-effect-free: the file-reading callable is *injected* so it stays testable. It expands `context` nodes by wrapping referenced file content in `<context_import source="...">` XML and merging it into the adjacent user message, emits `system`/`user`/`assistant` roles, and **drops `application` nodes entirely**.

### UI structure (mid-refactor)

The interface is being rebuilt into a **dual-pane** layout (see `CHANGELOG.md` and `CTX UI Implementation Specification.md`): a `MessageList` of truncated nodes on one side and a `DetailInspector` rendering the full selected node on the other (with a 3-split prompt/content/output view for context nodes), plus a global header (context-window % bar) and mode-aware footer. The app has two modes: **Insert** (input focused) and **Edit** (vim-style `j`/`k`/↑/↓ navigation over nodes, `1`/`2`/`3` to focus inspector splits, `g` to jump to root system node). `Esc` toggles modes. Note `ctx/ui/widgets/file_viewer.py` is legacy being removed in favor of `DetailInspector` — prefer the inspector.

### Other conventions

- In-app commands: `/new`, `/resume`, `/include`, `/model <name>`. Default model is set by `DEFAULT_MODEL` in `conversation.py`.
- CSS is split per-widget: `ctx/ui/app.css` plus `ctx/ui/widgets/*.css`.
- Logs: `~/.local/state/ctx/ctx.log` (`ctx/core/log.py`). User config (colors, `ui.truncation_lines`): `~/.config/ctx/config.json`, deep-merged over defaults (`ctx/core/config.py`).
- `.ctx/` and `.env` are gitignored — never commit them.

## Working style

`AGENTS.md` defines an explicit teaching-oriented working style for this repo (the author is building it as a learning exercise): **one logical unit per response, explain before writing, pause for go-ahead, never scaffold future steps.** Honor that unless the user says otherwise.
