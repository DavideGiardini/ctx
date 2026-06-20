# Changelog

All notable changes to the `ctx` UI refactor project.

## [Unreleased] — Dual-Pane Conversation UI

### Overview

Complete architectural and visual refactor of the terminal UI. The interface transitions from a standard scrolling chat to a dual-pane **Conversation Graph** (Right) and **Detail Inspector** (Left), with a global header/footer, truncated message nodes, real-time streaming to both panes, and context-window tracking.

---

### Added

#### Core Data Model

- **`Node` dataclass extensions** (`ctx/models/nodes.py`)
  - Added `@property` accessors for context 3-split data:
    - `prompt` — import/compression prompt (Top split)
    - `raw_content` — raw imported document text (Center split)
    - `output` — extracted/summarized text passed to LLM (Bottom split)
    - `token_count` — provider-reported completion token count, with getter/setter
  - All values stored in `meta` dict for transparent JSON serialization in SQLite.

- **`StreamChunk` dataclass** (`ctx/core/provider.py`)
  - New dataclass carrying `token: str` and optional `usage: dict | None`.
  - Captures completion-token metadata from the final LLM chunk.

- **Token counting & estimation** (`ctx/core/conversation.py`)
  - `ConversationCore.stream()` extracts `completion_tokens` from `StreamChunk.usage` and stores it on the assistant node.
  - `ConversationCore.estimate_tokens(text)` — lightweight `len(text) // 4` heuristic for non-assistant nodes.

#### Configuration

- **`ui.truncation_lines` config section** (`ctx/core/config.py`)
  - Per-role line limits: `user` (2), `assistant` (2), `context` (2), `system` (1), `application` (1).
  - Setting any value to `"auto"` disables truncation for that role.
  - Deep-merge support so users can override individual roles without dropping defaults.

#### Widgets

- **`DetailInspector` widget** (`ctx/ui/widgets/detail_inspector.py`, `.css`)
  - Left Pane widget that dynamically renders the full content of the active/selected node.
  - **Standard view**: single scrollable `Markdown` widget for `user`, `assistant`, `system`, `application` nodes.
  - **3-split view** for `context` nodes:
    - Top (`1fr`) — Prompt
    - Center (`3fr`) — Full Content
    - Bottom (`1fr`) — Output
    - Empty splits are completely hidden (`display: none`).
  - Caches node ID to avoid remounting during streaming; only updates text content.
  - `focus_split(index)` helper for keyboard navigation (1/2/3 keybindings).

- **Context weight indicators** (`ctx/ui/widgets/message_list.py`)
  - Each `MessageWidget` (except `system`/`application`) shows a right-aligned percentage label.
  - `MessageList.update_weights()` recomputes per-node share of total estimated tokens.

#### Layout & Chrome

- **Global Header bar** (`ctx/ui/app.css`, `app.py`)
  - Three-column horizontal layout:
    - Left: active conversation title
    - Center: "CTX" logo
    - Right: context-window percentage + ASCII progress bar (e.g., `45% [====      ]`)
  - Updates after every stream, `/new`, `/resume`, `/include`, and model switch.
  - Context limit resolved via `litellm.get_model_info()` with 128k fallback for unmapped models.

- **Global Footer bar** (`ctx/ui/app.css`, `app.py`)
  - Dynamically switches text based on mode:
    - Insert: `^C Cancel | Esc Edit Mode | / Commands`
    - Edit: `^C Cancel | Esc Insert Mode | ↑/↓ Navigate | 1/2/3 Focus Split`

- **Dual-pane main layout** (`ctx/ui/app.py`, `app.css`)
  - Left Pane (`1fr`): `DetailInspector`
  - Right Pane (`1fr`): `MessageList` + `InputBar` + command suggestions overlay
  - Removed the old split-viewer `FileViewer` and all its keybindings.

#### Keybindings

- **`j` / `k`** — vim-style aliases for Up/Down navigation in Edit Mode.
- **`g`** — Jump to the root `role="system"` node (the "Big S" LLM system prompt).
- **`1` / `2` / `3`** — Focus the Top / Center / Bottom split in the Detail Inspector when a context node is selected (Edit Mode only).
- Removed obsolete bindings: `o`, `v`, `ctrl+v`, `tab` (old FileViewer controls).

---

### Changed

#### Role taxonomy

- **App-generated messages now use `role="application"`** instead of `role="system"`.
  - `role="system"` is reserved exclusively for the LLM System Prompt.
  - Updated in: `ConversationCore.set_model()`, `check_connectivity()`, `new_conversation()`, `add_system_message()`.
  - UI widgets (`MessageWidget`, CSS) updated to treat `application` identically to the old `system` styling.

#### Conversation lifecycle

- **`new_conversation()`** now prepends a root LLM System Prompt node (`role="system"`, content: "You are a helpful assistant.") before the app confirmation message.
- **`build_context()`** emits `{"role": "system"}` for LLM system nodes and skips `role="application"` entirely (UI-only messages).

#### Message rendering

- **Truncation** (`ctx/ui/widgets/message_list.py`)
  - `MessageWidget.on_mount()` reads `ui.truncation_lines` from config and applies `max_height` + `overflow: hidden`.
  - Messages are now compressed scanning nodes by default (2 lines for user/assistant/context, 1 line for system/application).

- **Pass spacing** (`ctx/ui/widgets/message_list.py`)
  - `MessageList.add_node()` dynamically adds the `new-pass` CSS class (margin-top: 1) when transitioning from `assistant` → `user`.
  - Nodes within the same turn have zero vertical margin.

#### Navigation

- **Edit Mode navigation no longer skips any nodes**.
  - Previously `system` nodes were skipped during Up/Down traversal.
  - Now all nodes — including the root system prompt and application messages — are fully selectable.
- **`_enter_edit_mode()`** now selects the **last node** instead of the last non-system node.

#### Streaming behavior

- **Two-pane real-time streaming** (`ctx/ui/app.py`)
  - Right Pane: truncated preview updates on each token (overflow hidden by CSS).
  - Left Pane: `DetailInspector.show_node(assistant_node)` renders the full, unbound stream text when locked to the last node in Insert Mode.

#### Context file inclusion

- **`include_files()`** now reads the raw file content at inclusion time and stores it in `meta`:
  - `raw_content` — the full file text
  - `output` — same as raw for direct imports (future compression/summarization can override)
  - `prompt` — empty string for direct imports

---

### Removed

- **`FileViewer` widget** (`ctx/ui/widgets/file_viewer.py`) and `FileViewerScreen` — replaced entirely by the Detail Inspector.
- **Old split-viewer keybindings**: `o` (fullscreen), `v` (toggle split), `ctrl+v` (close split), `tab` (switch focus).
- **`#model-label` widget** — replaced by the three-section header bar.
- **`#split-viewer` CSS rules** — no longer in the widget tree.

---

### Technical Notes

- **Provider Protocol Breaking Change**: `Provider.stream()` now yields `AsyncIterator[StreamChunk]` instead of `AsyncIterator[str]`. The `ConversationCore` adapts this internally so the UI layer is unaffected.
- **SQLite Schema**: No schema migration required — new fields are stored in the existing `meta` JSON column.
- **Config Compatibility**: Existing `~/.config/ctx/config.json` files continue to work; the new `ui` section is optional and defaults are applied automatically.
