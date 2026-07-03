import asyncio
import contextlib
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Input, Static, TextArea
from textual.worker import Worker, WorkerState

from ctx.core import tokens
from ctx.core.config import get_config
from ctx.core.context import build_context
from ctx.core.conversation import DEFAULT_COMPRESSION_PROMPT, ConversationCore
from ctx.core.log import logger
from ctx.core.provider import LiteLLMProvider, Provider
from ctx.core.storage import ConversationRepository, StoragePort
from ctx.core.workspace import Workspace
from ctx.models.nodes import Node
from ctx.ui.widgets.app_footer import AppFooter
from ctx.ui.widgets.app_header import AppHeader
from ctx.ui.widgets.compression_editor import CompressionEditor
from ctx.ui.widgets.detail_inspector import DetailInspector, NodeView
from ctx.ui.widgets.history_screen import HistoryScreen
from ctx.ui.widgets.include_screen import IncludeScreen
from ctx.ui.widgets.input_bar import InputBar
from ctx.ui.widgets.message_list import MessageList, MessageWidget

# Config key per node role for truncation lookups ("user" maps to "human").
_TRUNCATION_KEY = {
    "user": "human",
    "assistant": "assistant",
    "context": "context",
    "system": "system",
}


class ChatApp(App):
    CSS_PATH = [
        "app.css",
        "widgets/message_list.css",
        "widgets/input_bar.css",
    ]

    BINDINGS = [
        Binding("ctrl+c", "cancel_stream", "Cancel", show=False),
        Binding("escape", "escape", "Toggle mode", show=False),
        Binding("i", "enter_insert", "Insert Mode", show=False),
        Binding("v", "anchor_range", "Select range", show=False),
        Binding("c", "compress", "Compress", show=False),
        Binding("up", "up", "Up", show=False),
        Binding("down", "down", "Down", show=False),
        Binding("enter", "detail_enter", "Select split", show=False),
        Binding("home", "jump_home", "Jump to top", show=False),
        Binding("1", "maximize_split('prompt')", "Prompt split", show=False),
        Binding("2", "maximize_split('content')", "Content split", show=False),
        Binding("3", "maximize_split('output')", "Output split", show=False),
        Binding("tab", "switch_focus", "Switch pane", show=False, priority=True),
    ]

    def __init__(
        self,
        *,
        provider: Provider | None = None,
        workspace: Workspace | None = None,
        storage: StoragePort | None = None,
    ) -> None:
        super().__init__()
        # Injectable seams: default to the real adapters so production
        # `ChatApp()` is unchanged, while tests/harness can pass a
        # TestProvider and a temp-dir Workspace.
        self._workspace = workspace or Workspace(Path.cwd())
        self._repo = storage or ConversationRepository(str(self._workspace.db_path))
        self.core = ConversationCore(
            self._repo, provider or LiteLLMProvider(), workspace=self._workspace
        )
        self._stream_worker: Worker | None = None
        self.mode = "insert"
        self._selected_node_id: str | None = None
        # Anchor of a vim-style range selection (Edit mode). ``None`` when no
        # range is active; while set, up/down extend the contiguous highlight
        # between it and the cursor (``_selected_node_id``). See ADR-0016 Q5.
        self._range_anchor_id: str | None = None
        # Node-set signature captured the last time a streamed turn produced a
        # fresh provider ``usage`` anchor. The header gauge is exact only while
        # the conversation still matches it; any later change makes it stale
        # (``~``). ``None`` until the first anchored turn.
        self._gauge_anchor: tuple | None = None
        logger.info("app initialized | default_model=%s", self.core.model)

    def compose(self) -> ComposeResult:
        yield AppHeader(id="app-header")
        with Horizontal(id="body"):
            yield DetailInspector(id="detail")
            yield CompressionEditor(id="compression-editor")
            with Vertical(id="conversation"):
                yield MessageList(id="messages")
                # Suggestions + input share one docked container so they stack
                # in normal flow (docking both directly would overlap them).
                with Container(id="input-area"):
                    yield Static("", id="command-suggestions")
                    yield InputBar()
        yield AppFooter()

    def on_mount(self) -> None:
        self.core.setup()
        self.query_one(InputBar).focus()
        self.query_one(AppHeader).set_title(self.core.conversation_title)
        footer = self.query_one(AppFooter)
        footer.set_mode("insert")
        footer.set_model(self.core.model)
        self._lock_inspector_to_last()

    # --- command suggestions overlay ------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input is not self.query_one(InputBar):
            return
        suggestions = self.query_one("#command-suggestions", Static)
        if not event.value.startswith("/"):
            suggestions.display = False
            return
        if " " in event.value:
            suggestions.display = False
            return
        suggestions.display = True
        input_bar = self.query_one(InputBar)
        for i, cmd in enumerate(InputBar.COMMANDS):
            if cmd.startswith(event.value):
                input_bar._selected_command = i
                break
        else:
            if event.value == "/":
                input_bar._selected_command = 0
        self._update_suggestions()

    def _update_suggestions(self) -> None:
        input_bar = self.query_one(InputBar)
        suggestions = self.query_one("#command-suggestions", Static)
        selected = input_bar._selected_command
        lines = ["Available commands:"]
        for i, cmd in enumerate(InputBar.COMMANDS):
            prefix = "▸" if i == selected else " "
            lines.append(f"{prefix} [bold]{cmd}[/bold]")
        suggestions.update("\n".join(lines))

    def on_input_bar_command_navigated(self, event: InputBar.CommandNavigated) -> None:
        self._update_suggestions()

    def on_input_bar_command_selected(self, event: InputBar.CommandSelected) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#command-suggestions", Static).display = False

    # --- modes ----------------------------------------------------------

    def action_escape(self) -> None:
        try:
            suggestions = self.query_one("#command-suggestions", Static)
            if suggestions.display:
                suggestions.display = False
                return
        except Exception:
            pass
        # The draft editor cancels for free: Esc closes it, restores the
        # inspector, and keeps the selection (Q4). No graph mutation.
        if self.query_one(CompressionEditor).is_open:
            self._close_compression_editor()
            return
        # Inside the detail pane, Esc backs out one level (Maximized→Browse→right pane)
        # before it falls through to the Insert/Edit toggle.
        if self.mode == "edit" and self._focus_in_detail():
            inspector = self.query_one(DetailInspector)
            if inspector.pane_mode != "none":
                if inspector.back() == "exit":
                    self.query_one(MessageList).focus()
                self._sync_footer()
                return
        # An active range selection swallows the first Esc (clear the anchor but
        # stay in Edit); a second Esc then toggles the mode as usual (Q5).
        if self.mode == "edit" and self._range_anchor_id is not None:
            self._clear_range()
            return
        self._set_mode("edit" if self.mode == "insert" else "insert")

    def action_enter_insert(self) -> None:
        # Vim-style: `i` returns to Insert mode from anywhere in Edit mode
        # (right pane or inside the detail pane). Switching to Insert re-locks
        # the inspector to the last node, resetting any detail sub-state.
        if self.mode == "edit":
            self._set_mode("insert")

    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        # Any mode switch leaves the detail pane's navigation sub-state behind.
        # (Reset explicitly: re-showing the same node would be a no-op and skip
        # the reactive watcher that normally resets it.)
        self.query_one(DetailInspector).exit_pane()
        self.query_one(AppFooter).set_mode(mode)
        if mode == "insert":
            self._clear_selection()
            self.query_one(InputBar).focus()
            self._lock_inspector_to_last()
            logger.info("entered insert mode")
        else:
            self.query_one(InputBar).blur()
            self.query_one(MessageList).focus()
            target = self.core.nodes[-1].id if self.core.nodes else None
            self._select_message(target)
            logger.info("entered edit mode")

    # --- selection + inspector ------------------------------------------

    def _node_view(self, node: Node) -> NodeView:
        return NodeView(
            node_id=node.id,
            role=node.role,
            node_type=node.node_type,
            content=node.content,
            prompt=node.meta.get("prompt", ""),
            output=node.meta.get("output", ""),
            source_path=node.meta.get("source_path"),
        )

    def _lock_inspector_to_last(self) -> None:
        inspector = self.query_one(DetailInspector)
        last = self.core.nodes[-1] if self.core.nodes else None
        inspector.show(self._node_view(last) if last else None)

    def _select_message(self, node_id: str | None) -> None:
        message_list = self.query_one(MessageList)
        if self._selected_node_id:
            try:
                prev = message_list.query_one(f"#msg-{self._selected_node_id}", MessageWidget)
                prev.set_selected(False)
            except Exception:
                pass
        self._selected_node_id = node_id
        if node_id is None:
            self.query_one(DetailInspector).show(None)
            return
        try:
            widget = message_list.query_one(f"#msg-{node_id}", MessageWidget)
            widget.set_selected(True)
            widget.scroll_visible()
        except Exception:
            pass
        node = self._get_selected_node()
        self.query_one(DetailInspector).show(self._node_view(node) if node else None)

    def _clear_selection(self) -> None:
        if self._selected_node_id:
            try:
                prev = self.query_one(MessageList).query_one(
                    f"#msg-{self._selected_node_id}", MessageWidget
                )
                prev.set_selected(False)
            except Exception:
                pass
        self._selected_node_id = None
        self._clear_range()

    def action_anchor_range(self) -> None:
        """`v` in Edit mode: anchor a range selection at the current node.

        A fresh press re-anchors at the cursor (range-of-one). Up/Down then
        extend the contiguous highlight between the anchor and the cursor.
        """
        if self.mode != "edit" or self._focus_in_detail():
            return
        if self._selected_node_id is None:
            return
        self._range_anchor_id = self._selected_node_id
        self._apply_range_selection()

    def _range_ids(self) -> list[str]:
        """The ids of the currently selected range, in view order (empty when
        no anchor is set or the anchor has left the view)."""
        if self._range_anchor_id is None:
            return []
        ids = [n.id for n in self.core.nodes]
        try:
            anchor = ids.index(self._range_anchor_id)
        except ValueError:
            return []
        cursor_id = self._selected_node_id or self._range_anchor_id
        cursor = ids.index(cursor_id) if cursor_id in ids else anchor
        lo, hi = sorted((anchor, cursor))
        return ids[lo : hi + 1]

    def _apply_range_selection(self) -> None:
        selected = set(self._range_ids())
        for widget in self.query_one(MessageList).query(MessageWidget):
            widget.set_range_selected(widget.node.id in selected)

    def _clear_range(self) -> None:
        if self._range_anchor_id is None:
            return
        self._range_anchor_id = None
        try:
            for widget in self.query_one(MessageList).query(MessageWidget):
                widget.set_range_selected(False)
        except Exception:
            pass

    # --- compression draft editor ---------------------------------------

    def _compression_range(self) -> list[str]:
        """Node ids the draft editor would compress: the active range, or a
        range-of-one on the selected node when no anchor is set (Q5). Empty when
        nothing is selected at all."""
        if self._range_anchor_id is not None:
            return self._range_ids()
        if self._selected_node_id is not None:
            return [self._selected_node_id]
        return []

    def action_compress(self) -> None:
        """`c` in Edit mode: open the draft editor on the active selection (Q4).

        No anchor → range-of-one on the selected node; no selection → no-op
        (the discoverable ``/compress`` command explains how to select)."""
        if self.mode != "edit" or self._focus_in_detail():
            return
        if not self._compression_range():
            return
        self._open_compression_editor()

    def _open_compression_editor(self) -> None:
        editor = self.query_one(CompressionEditor)
        self.query_one(DetailInspector).display = False
        editor.open(DEFAULT_COMPRESSION_PROMPT)
        editor.query_one("#compress-prompt", TextArea).focus()

    def _close_compression_editor(self) -> None:
        self.query_one(CompressionEditor).close()
        self.query_one(DetailInspector).display = True
        self.query_one(MessageList).focus()

    def _focus_in_detail(self) -> bool:
        return self._is_focused_in(self.query_one(DetailInspector))

    def action_up(self) -> None:
        if self.mode != "edit":
            return
        if self._focus_in_detail():
            inspector = self.query_one(DetailInspector)
            if inspector.pane_mode == "browse":
                inspector.highlight_prev()
            elif inspector.pane_mode == "maximized":
                inspector.scroll_lines(-1)
            return
        self._select_relative(-1)
        if self._range_anchor_id is not None:
            self._apply_range_selection()

    def action_down(self) -> None:
        if self.mode != "edit":
            return
        if self._focus_in_detail():
            inspector = self.query_one(DetailInspector)
            if inspector.pane_mode == "browse":
                inspector.highlight_next()
            elif inspector.pane_mode == "maximized":
                inspector.scroll_lines(1)
            return
        self._select_relative(1)
        if self._range_anchor_id is not None:
            self._apply_range_selection()

    def _select_relative(self, step: int) -> None:
        if not self.core.nodes:
            return
        default = len(self.core.nodes) if step < 0 else -1
        if self._selected_node_id is None:
            start = default
        else:
            start = next(
                (i for i, n in enumerate(self.core.nodes) if n.id == self._selected_node_id),
                default,
            )
        idx = (start + step) % len(self.core.nodes)
        self._select_message(self.core.nodes[idx].id)

    def action_detail_enter(self) -> None:
        if self.mode != "edit" or not self._focus_in_detail():
            return
        inspector = self.query_one(DetailInspector)
        if inspector.pane_mode == "browse":
            inspector.maximize()
            self._sync_footer()

    def action_jump_home(self) -> None:
        if not self.core.nodes:
            return
        if self.mode != "edit":
            self._set_mode("edit")
        self._select_message(self.core.nodes[0].id)

    def action_maximize_split(self, which: str) -> None:
        if self.mode != "edit":
            return
        node = self._get_selected_node()
        if not node or node.node_type != "context":
            return
        if self.query_one(DetailInspector).maximize_named(which):
            self._sync_footer()

    def action_switch_focus(self) -> None:
        if self.mode != "edit":
            return
        inspector = self.query_one(DetailInspector)
        message_list = self.query_one(MessageList)
        if self._focus_in_detail():
            inspector.exit_pane()
            message_list.focus()
        else:
            mode = inspector.enter_pane()
            if mode == "browse":
                inspector.focus()
            # "maximized" already focused the split; "none" → stay on messages
        self._sync_footer()

    def _sync_footer(self) -> None:
        self.query_one(AppFooter).set_detail(self.query_one(DetailInspector).pane_mode)

    def _get_selected_node(self) -> Node | None:
        if self._selected_node_id is None:
            return None
        for node in self.core.nodes:
            if node.id == self._selected_node_id:
                return node
        return None

    def _is_focused_in(self, widget) -> bool:
        focused = self.focused
        if focused is None:
            return False
        if focused == widget:
            return True
        return focused in widget.walk_children()

    def _focus_target(self) -> str | None:
        """Report which pane currently holds focus, semantically."""
        if self.focused is None:
            return None
        if self._is_focused_in(self.query_one(InputBar)):
            return "input"
        if self._is_focused_in(self.query_one(DetailInspector)):
            return "detail"
        if self._is_focused_in(self.query_one(MessageList)):
            return "messages"
        return "other"

    # --- token weights --------------------------------------------------

    def _node_weights(self) -> list[int | None]:
        """Per-node weight percentages parallel to ``self.core.nodes``.

        The single computation both ``describe_state`` and ``_refresh_token_ui``
        read, so the snapshot and the rendered ``--%`` slots cannot drift. Basis
        comes from config; the window denominator (only used by ``"window"``
        basis) from the active model, ``None`` when unknown.
        """
        return tokens.weight_pct(
            self.core.nodes,
            self.core.model,
            self.core.read_file,
            get_config()["ui"]["weight_basis"],
            tokens.model_window(self.core.model),
        )

    def _node_signature(self) -> tuple:
        """A cheap fingerprint of the current node set's content.

        Pairs each node's stable id with its content length, so the tuple
        differs whenever a node is added, removed, reordered, or grows (a
        streamed reply). The gauge compares it against ``_gauge_anchor`` to tell
        a provider-exact figure from a now-stale one.
        """
        return tuple((n.id, len(n.content)) for n in self.core.nodes)

    def _gauge_state(self) -> tuple[int | None, bool]:
        """Header gauge ``(pct, approximate)`` for the current context.

        ``pct`` is used ÷ model window (``None`` → ``--%`` when the window is
        unknown), with the local estimate scaled by any provider calibration.
        ``approximate`` is ``True`` when there is no calibration yet *or* the
        node set has drifted from the last anchored turn — either way the
        absolute figure is only an estimate and the UI marks it ``~``.
        """
        messages = build_context(self.core.nodes, self.core.read_file)
        local_total = tokens.count_messages(messages, self.core.model)
        pct, approximate = tokens.gauge(
            local_total,
            tokens.model_window(self.core.model),
            self.core.calibration,
        )
        stale = self._node_signature() != self._gauge_anchor
        return pct, approximate or stale

    def _refresh_token_ui(self) -> None:
        """Refresh both token-budget surfaces after a node-list/content change.

        Called after any change to the node list or to node content (a new turn,
        a finished stream, ``/include``, ``/resume``, ``/new``): pushes each
        node's per-node weight ``--%`` onto its message widget and the
        used-÷-window gauge (with its ``~`` marker) onto the header."""
        message_list = self.query_one(MessageList)
        for node, pct in zip(self.core.nodes, self._node_weights(), strict=True):
            try:
                widget = message_list.query_one(f"#msg-{node.id}", MessageWidget)
            except Exception:
                continue
            widget.set_weight_pct(pct)
        gauge_pct, approximate = self._gauge_state()
        self.query_one(AppHeader).set_context_pct(gauge_pct, approximate)

    # --- state snapshot -------------------------------------------------

    def describe_state(self) -> dict:
        """Return a structured snapshot of the app's observable state.

        Raw data only (full node content, no truncation) — token-budget
        formatting lives in ``tools/agent/snapshot.py``. Useful for the agent
        MCP layer and for debugging/logging this otherwise-opaque TUI.

        Nodes are reported by stable *index* + role (the random ``Node.id``
        uuids are an implementation detail agents should not depend on).
        """
        nodes = self.core.nodes
        truncation = get_config()["ui"]["truncation_lines"]
        weights = self._node_weights()
        gauge_pct, gauge_approximate = self._gauge_state()
        selected_index: int | None = None
        selected_role: str | None = None
        node_states: list[dict] = []
        for i, node in enumerate(nodes):
            is_selected = node.id == self._selected_node_id
            if is_selected:
                selected_index = i
                selected_role = node.role
            entry: dict = {
                "index": i,
                "role": node.role,
                "node_type": node.node_type,
                "content": node.content,
                "selected": is_selected,
                "weight_pct": weights[i],
                "truncated": self._is_truncated(node, truncation),
            }
            source_path = node.meta.get("source_path")
            if source_path:
                entry["source_path"] = source_path
            node_states.append(entry)

        streaming = (
            self._stream_worker is not None
            and self._stream_worker.state == WorkerState.RUNNING
        )

        input_bar = self.query_one(InputBar)
        suggestions = self.query_one("#command-suggestions", Static)
        command_menu: dict | None = None
        if suggestions.display:
            command_menu = {
                "visible": True,
                "selected": InputBar.COMMANDS[input_bar._selected_command],
                "items": list(InputBar.COMMANDS),
                "count": len(InputBar.COMMANDS),
                # True when the menu's region is covered by the input bar — a
                # rendering regression that is invisible to widget content but
                # hides menu items from the user (see the docked-overlap bug).
                "occluded": self._regions_overlap(suggestions, input_bar),
            }

        inspector = self.query_one(DetailInspector)
        detail_view = inspector.view_kind
        detail_node_index: int | None = None
        detail_node_role: str | None = None
        if inspector.node_state is not None:
            detail_id = inspector.node_state.node_id
            detail_node_index = next(
                (i for i, n in enumerate(nodes) if n.id == detail_id), None
            )
            detail_node_role = inspector.node_state.role

        return {
            "mode": self.mode,
            "model": self.core.model,
            "title": self.core.conversation_title,
            "streaming": streaming,
            "focus": self._focus_target(),
            "selected_index": selected_index,
            "selected_role": selected_role,
            "range_selection": self._range_ids(),
            "compression_editor": self._compression_editor_state(),
            "layout": {"header": True, "footer": True, "panes": ["detail", "conversation"]},
            "footer": self.query_one(AppFooter).current_hint(),
            "detail": {
                "node_index": detail_node_index,
                "node_role": detail_node_role,
                "view": detail_view,
                "splits_visible": inspector.splits_visible() if detail_view == "context" else [],
                "pane_mode": inspector.pane_mode,
                "highlighted_split": inspector.highlighted_split(),
                "maximized_split": inspector.maximized_split(),
                "locked": self.mode == "insert",
            },
            "context_gauge": {"pct": gauge_pct, "approximate": gauge_approximate},
            "truncation": truncation,
            "input": input_bar.value,
            "command_menu": command_menu,
            "colors": get_config()["colors"],
            "nodes": node_states,
        }

    def _compression_editor_state(self) -> dict:
        """Snapshot of the draft editor for ``describe_state`` (the Pilot floor):
        whether it is open plus its current prompt/output text."""
        editor = self.query_one(CompressionEditor)
        return {"open": editor.is_open, "prompt": editor.prompt, "output": editor.output}

    @staticmethod
    def _regions_overlap(a, b) -> bool:
        """Whether two widgets' laid-out regions intersect on screen. Used to
        detect rendering overlaps that widget content/state cannot reveal."""
        try:
            ra, rb = a.region, b.region
        except Exception:
            return False
        if not ra.area or not rb.area:
            return False
        return not (
            ra.right <= rb.x
            or rb.right <= ra.x
            or ra.bottom <= rb.y
            or rb.bottom <= ra.y
        )

    @staticmethod
    def _is_truncated(node: Node, truncation: dict) -> bool:
        limit = truncation.get(_TRUNCATION_KEY.get(node.role, "system"))
        if limit == "auto" or not isinstance(limit, int):
            return False
        return node.content.count("\n") + 1 > limit

    # --- input + commands -----------------------------------------------

    async def on_input_bar_submitted(self, event: InputBar.Submitted) -> None:
        text = event.text.strip()
        logger.info("on_input_bar_submitted | text=%r | len=%d", text, len(text))
        with contextlib.suppress(Exception):
            self.query_one("#command-suggestions", Static).display = False
        if not text:
            return

        logger.info("input submitted | text=%r", text)

        if text.startswith("/model"):
            logger.info("matched /model")
            await self._handle_model_command(text)
            return

        if text == "/new":
            logger.info("matched /new")
            await self._handle_new_command()
            return

        if text == "/resume":
            logger.info("matched /resume")
            self._handle_resume_command()
            return

        if text == "/include":
            logger.info("matched /include")
            self._handle_include_command()
            return

        if text == "/compress":
            logger.info("matched /compress")
            await self._handle_compress_command()
            return

        logger.info("no command matched, sending to model")

        user_node, assistant_node = self.core.submit(text)
        message_list = self.query_one(MessageList)
        await message_list.add_node(user_node)
        await message_list.add_node(assistant_node)
        self.query_one(AppHeader).set_title(self.core.conversation_title)
        self._refresh_token_ui()
        if self.mode == "insert":
            self._lock_inspector_to_last()
        self._stream_worker = self._stream_response(assistant_node)

    def _update_model_label(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one(AppFooter).set_model(self.core.model)

    async def _handle_model_command(self, text: str) -> None:
        parts = text.split(maxsplit=1)
        if len(parts) == 1:
            logger.info("model queried | current=%s", self.core.model)
            node = self.core.add_system_message(f"Current model: {self.core.model}")
        else:
            new_model = parts[1]
            node = self.core.set_model(new_model)
            self._update_model_label()
            logger.info("model switched | new_model=%s", new_model)
            self._check_connectivity(new_model)
        await self.query_one(MessageList).add_node(node)
        if self.mode == "insert":
            self._lock_inspector_to_last()

    @work(name="check_connectivity")
    async def _check_connectivity(self, model: str) -> None:
        node = await self.core.check_connectivity(model)
        await self.query_one(MessageList).add_node(node)
        if self.mode == "insert":
            self._lock_inspector_to_last()

    async def _handle_new_command(self) -> None:
        old_id = self.core.conversation_id
        node = self.core.new_conversation()
        logger.info("new conversation | old_id=%s", old_id)
        self._clear_selection()
        message_list = self.query_one(MessageList)
        for child in list(message_list.children):
            await child.remove()
        await message_list.add_node(node)
        self.query_one(AppHeader).set_title(self.core.conversation_title)
        self._update_model_label()
        self._refresh_token_ui()
        if self.mode == "insert":
            self._lock_inspector_to_last()

    @work(name="handle_resume")
    async def _handle_resume_command(self) -> None:
        conversations = self._repo.list()
        if not conversations:
            node = self.core.add_system_message("No past conversations found.")
            await self.query_one(MessageList).add_node(node)
            if self.mode == "insert":
                self._lock_inspector_to_last()
            return
        result = await self.push_screen_wait(HistoryScreen(self._repo))
        if result is None:
            return
        nodes = self.core.resume_conversation(result)
        self._clear_selection()
        message_list = self.query_one(MessageList)
        for child in list(message_list.children):
            await child.remove()
        for node in nodes:
            await message_list.add_node(node)
        self.query_one(AppHeader).set_title(self.core.conversation_title)
        self._update_model_label()
        self._refresh_token_ui()
        if self.mode == "insert":
            self._lock_inspector_to_last()
        logger.info("loaded conversation | id=%s | nodes=%d", result, len(nodes))

    @work(name="handle_include")
    async def _handle_include_command(self) -> None:
        files = self._workspace.list_files()
        if not files:
            node = self.core.add_system_message("No files in .ctx/context/ to include.")
            await self.query_one(MessageList).add_node(node)
            if self.mode == "insert":
                self._lock_inspector_to_last()
            return
        result = await self.push_screen_wait(IncludeScreen(self._workspace))
        if not result:
            return
        nodes = self.core.include_files(result)
        message_list = self.query_one(MessageList)
        for node in nodes:
            await message_list.add_node(node)
            logger.info("context included | path=%s", node.meta.get("source_path", ""))
        self._refresh_token_ui()
        if self.mode == "insert":
            self._lock_inspector_to_last()

    async def _handle_compress_command(self) -> None:
        if not self._compression_range():
            node = self.core.add_system_message("Select a range first: v in Edit mode")
            await self.query_one(MessageList).add_node(node)
            self._refresh_token_ui()
            if self.mode == "insert":
                self._lock_inspector_to_last()
            return
        self._open_compression_editor()

    # --- streaming ------------------------------------------------------

    @work(name="stream_response")
    async def _stream_response(self, assistant_node: Node) -> None:
        message_list = self.query_one(MessageList)
        inspector = self.query_one(DetailInspector)
        usage_gen_before = self.core.usage_generation
        try:
            async for _token in self.core.stream(assistant_node):
                message_list.update_content(assistant_node.id, assistant_node.content)
                self._stream_to_inspector(inspector, assistant_node)
            logger.info("response finalized | length=%d", len(assistant_node.content))
            if self.core.usage_generation != usage_gen_before:
                # This turn produced a fresh provider anchor: the gauge is now
                # exact for the current node set. Remember it so a later change
                # (a /include before the next turn) re-marks the gauge stale.
                self._gauge_anchor = self._node_signature()
        except asyncio.CancelledError:
            assistant_node.meta["interrupted"] = True
            message_list.update_content(assistant_node.id, assistant_node.content or "▌")
            raise
        except Exception as exc:
            assistant_node.meta["error"] = str(exc)
            message_list.update_content(assistant_node.id, f"**Error:** {exc}")
            logger.error("stream error | error=%s", exc)

    def _stream_to_inspector(self, inspector: DetailInspector, node: Node) -> None:
        """Render the live stream into the left pane only when it is locked to
        this streaming node (so navigating away in Edit mode is not hijacked)."""
        state = inspector.node_state
        if state is not None and state.node_id == node.id:
            inspector.append_stream(node.content)

    def action_cancel_stream(self) -> None:
        if self._stream_worker and self._stream_worker.state == WorkerState.RUNNING:
            self._stream_worker.cancel()
        else:
            self.exit()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.name == "stream_response" and event.state in (
            WorkerState.SUCCESS,
            WorkerState.CANCELLED,
            WorkerState.ERROR,
        ):
            self._stream_worker = None
            # The assistant node now carries its full text — its weight (and the
            # context-basis share of every other node) only just became real.
            self._refresh_token_ui()
