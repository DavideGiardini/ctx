import asyncio
import contextlib
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Static
from textual.worker import Worker, WorkerState

from ctx.core.conversation import DEFAULT_MODEL, ConversationCore
from ctx.core.log import logger
from ctx.core.provider import LiteLLMProvider, Provider
from ctx.core.storage import ConversationRepository
from ctx.core.workspace import Workspace
from ctx.models.nodes import Node
from ctx.ui.widgets.detail_inspector import DetailInspector
from ctx.ui.widgets.history_screen import HistoryScreen
from ctx.ui.widgets.include_screen import IncludeScreen
from ctx.ui.widgets.input_bar import InputBar
from ctx.ui.widgets.message_list import MessageList, MessageWidget


class ChatApp(App):
    CSS_PATH = [
        "app.css",
        "widgets/message_list.css",
        "widgets/input_bar.css",
        "widgets/detail_inspector.css",
    ]

    BINDINGS = [
        Binding("ctrl+c", "cancel_stream", "Cancel", show=False, priority=True),
        Binding("escape", "dismiss_commands", "Dismiss", show=False),
        Binding("up", "select_prev", "Previous Message", show=False),
        Binding("down", "select_next", "Next Message", show=False),
        Binding("k", "select_prev", "Previous Message", show=False),
        Binding("j", "select_next", "Next Message", show=False),
        Binding("i", "enter_insert", "Insert Mode", show=False),
        Binding("g", "jump_to_root", "Jump to Root", show=False),
        Binding("1", "focus_split(1)", "Focus Prompt", show=False),
        Binding("2", "focus_split(2)", "Focus Content", show=False),
        Binding("3", "focus_split(3)", "Focus Output", show=False),
    ]

    def __init__(
        self,
        *,
        provider: Provider | None = None,
        workspace: Workspace | None = None,
    ) -> None:
        super().__init__()
        self._workspace = workspace if workspace is not None else Workspace(Path.cwd())
        self._repo = ConversationRepository(str(self._workspace.db_path))
        self.core = ConversationCore(
            self._repo,
            provider if provider is not None else LiteLLMProvider(),
            workspace=self._workspace,
        )
        self._stream_worker: Worker | None = None
        self.mode = "insert"
        self._selected_node_id: str | None = None
        logger.info("app initialized | default_model=%s", DEFAULT_MODEL)

    @property
    def selected_node_id(self) -> str | None:
        """Id of the node currently selected in edit mode, or ``None``."""
        return self._selected_node_id

    @property
    def is_streaming(self) -> bool:
        """``True`` while an assistant response is actively streaming."""
        return (
            self._stream_worker is not None
            and self._stream_worker.state == WorkerState.RUNNING
        )

    def compose(self) -> ComposeResult:
        with Horizontal(id="header"):
            yield Static("", id="header-title")
            yield Static("CTX", id="header-logo")
            yield Static("0% [          ]", id="header-context")
        with Horizontal(id="main-area"):
            yield DetailInspector(id="detail-inspector")
            with Vertical(id="right-pane"):
                yield MessageList()
                with Container(id="input-area"):
                    yield Static("", id="command-suggestions")
                    yield InputBar()
        yield Static("^X Cancel | Esc Toggle Mode | ↑/↓ Navigate", id="footer")

    def on_mount(self) -> None:
        self.core.setup()
        self.query_one(InputBar).focus()
        self._update_footer()
        self._update_header()

    def on_key(self, event) -> None:
        """Intercept Tab when the Detail Inspector is in full-view mode.

        Textual's default Screen handler cycles focus on Tab. We need to
        suppress that so Tab returns to the 3-split view without jumping
        to the input bar.
        """
        if event.key == "tab":
            inspector = self.query_one("#detail-inspector", DetailInspector)
            if inspector.is_full_view():
                event.stop()
                event.prevent_default()
                self.action_return_to_split()
                return

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

    def action_dismiss_commands(self) -> None:
        try:
            suggestions = self.query_one("#command-suggestions", Static)
            if suggestions.display:
                suggestions.display = False
                return
        except Exception:
            pass

        if self.mode == "insert":
            self._enter_edit_mode()
        else:
            self._enter_insert_mode()

    def _enter_edit_mode(self) -> None:
        if self.mode == "edit":
            return
        self.mode = "edit"
        self.query_one(InputBar).blur()
        self.query_one(MessageList).focus()
        if self.core.nodes:
            self._select_message(self.core.nodes[-1].id)
        self._update_footer()
        logger.info("entered edit mode")

    def _enter_insert_mode(self) -> None:
        if self.mode == "insert":
            return
        self.mode = "insert"
        self._clear_selection()
        self.query_one(InputBar).focus()
        # Lock detail inspector to the last node
        if self.core.nodes:
            self.query_one("#detail-inspector", DetailInspector).show_node(
                self.core.nodes[-1]
            )
        self._update_footer()
        logger.info("entered insert mode")

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
            self.query_one("#detail-inspector", DetailInspector).show_node(None)
            return
        try:
            widget = message_list.query_one(f"#msg-{node_id}", MessageWidget)
            widget.set_selected(True)
            widget.scroll_visible()
        except Exception:
            pass
        # Update detail inspector to show the selected node
        node = self._get_selected_node()
        self.query_one("#detail-inspector", DetailInspector).show_node(node)

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
        self.query_one("#detail-inspector", DetailInspector).show_node(None)

    def action_select_prev(self) -> None:
        if self.mode != "edit" or not self.core.nodes:
            return
        if self._selected_node_id is None:
            start = len(self.core.nodes)
        else:
            start = next(
                (i for i, n in enumerate(self.core.nodes) if n.id == self._selected_node_id), -1
            )
            if start == -1:
                start = len(self.core.nodes)
        idx = (start - 1) % len(self.core.nodes)
        self._select_message(self.core.nodes[idx].id)

    def action_select_next(self) -> None:
        if self.mode != "edit" or not self.core.nodes:
            return
        if self._selected_node_id is None:
            start = -1
        else:
            start = next(
                (i for i, n in enumerate(self.core.nodes) if n.id == self._selected_node_id), -1
            )
        idx = (start + 1) % len(self.core.nodes)
        self._select_message(self.core.nodes[idx].id)

    def action_enter_insert(self) -> None:
        if self.mode == "edit":
            self._enter_insert_mode()

    def action_jump_to_root(self) -> None:
        """Jump to the first role='system' node (the 'Big S' root prompt)."""
        if not self.core.nodes:
            return
        for node in self.core.nodes:
            if node.role == "system":
                self._select_message(node.id)
                return

    def action_focus_split(self, index: int) -> None:
        """Maximize the Nth split in the Detail Inspector (1=prompt, 2=content, 3=output)."""
        if self.mode != "edit":
            return
        inspector = self.query_one("#detail-inspector", DetailInspector)
        inspector.enter_full_view(index)
        if inspector.is_full_view():
            with contextlib.suppress(Exception):
                inspector.query_one(".full-view-scroll", VerticalScroll).focus()

    def action_return_to_split(self) -> None:
        """Return from full-view to 3-split and move focus back to the conversation."""
        inspector = self.query_one("#detail-inspector", DetailInspector)
        if not inspector.is_full_view():
            return
        inspector.return_to_split_view()
        self.query_one(MessageList).focus()

    def _get_selected_node(self) -> Node | None:
        if self._selected_node_id is None:
            return None
        for node in self.core.nodes:
            if node.id == self._selected_node_id:
                return node
        return None

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

        logger.info("no command matched, sending to model")

        user_node, assistant_node = self.core.submit(text)
        message_list = self.query_one(MessageList)
        await message_list.add_node(user_node)
        await message_list.add_node(assistant_node)
        self._stream_worker = self._stream_response(assistant_node)

    def _update_footer(self) -> None:
        if self.mode == "insert":
            text = "^X Cancel | Esc Edit Mode | / Commands"
        else:
            text = "^X Cancel | Esc Insert Mode | ↑/↓ Navigate | 1/2/3 Focus Split"
        with contextlib.suppress(Exception):
            self.query_one("#footer", Static).update(text)

    def _update_header(self) -> None:
        """Refresh the header with title, logo, and context-window progress."""
        title = self.core.conversation_title or "New Conversation"

        usage = self.core.token_usage()
        percent = min(100, round(usage.fraction * 100))
        filled = int(percent / 10)
        bar = "=" * filled + " " * (10 - filled)

        with contextlib.suppress(Exception):
            self.query_one("#header-title", Static).update(title[:30])
            self.query_one("#header-context", Static).update(f"{percent}% [{bar}]")

    async def _handle_model_command(self, text: str) -> None:
        parts = text.split(maxsplit=1)
        if len(parts) == 1:
            logger.info("model queried | current=%s", self.core.model)
            node = self.core.add_system_message(f"Current model: {self.core.model}")
        else:
            new_model = parts[1]
            node = self.core.set_model(new_model)
            self._update_header()
            logger.info("model switched | new_model=%s", new_model)
            await self.query_one(MessageList).add_node(node)
            self._check_connectivity(new_model)
            return
        await self.query_one(MessageList).add_node(node)

    @work(name="check_connectivity")
    async def _check_connectivity(self, model: str) -> None:
        node = await self.core.check_connectivity(model)
        await self.query_one(MessageList).add_node(node)

    async def _handle_new_command(self) -> None:
        old_id = self.core.conversation_id
        node = self.core.new_conversation()
        logger.info("new conversation | old_id=%s", old_id)
        self._clear_selection()
        message_list = self.query_one(MessageList)
        for child in list(message_list.children):
            await child.remove()
        await message_list.add_node(node)
        self._update_header()

    @work(name="handle_resume")
    async def _handle_resume_command(self) -> None:
        conversations = self._repo.list()
        if not conversations:
            node = self.core.add_system_message("No past conversations found.")
            await self.query_one(MessageList).add_node(node)
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
        self._update_header()
        logger.info("loaded conversation | id=%s | nodes=%d", result, len(nodes))

    @work(name="handle_include")
    async def _handle_include_command(self) -> None:
        files = self._workspace.list_files()
        if not files:
            node = self.core.add_system_message("No files in .ctx/context/ to include.")
            await self.query_one(MessageList).add_node(node)
            return
        result = await self.push_screen_wait(IncludeScreen(self._workspace))
        if not result:
            return
        nodes = self.core.include_files(result)
        message_list = self.query_one(MessageList)
        for node in nodes:
            await message_list.add_node(node)
            logger.info("context included | path=%s", node.meta.get("source_path", ""))
        self._update_header()

    @work(name="stream_response")
    async def _stream_response(self, assistant_node: Node) -> None:
        message_list = self.query_one(MessageList)
        inspector = self.query_one("#detail-inspector", DetailInspector)
        try:
            async for _token in self.core.stream(assistant_node):
                message_list.update_content(assistant_node.id, assistant_node.content)
                # Update detail inspector in real-time when locked to the last node
                if self.mode == "insert":
                    inspector.show_node(assistant_node)
            logger.info("response finalized | length=%d", len(assistant_node.content))
            message_list.update_weights(self.core.token_usage())
            self._update_header()
        except asyncio.CancelledError:
            assistant_node.meta["interrupted"] = True
            message_list.update_content(assistant_node.id, assistant_node.content or "▌")
            message_list.update_weights(self.core.token_usage())
            self._update_header()
            raise
        except Exception as exc:
            assistant_node.meta["error"] = str(exc)
            message_list.update_content(assistant_node.id, f"**Error:** {exc}")
            message_list.update_weights(self.core.token_usage())
            self._update_header()
            logger.error("stream error | error=%s", exc)

    def action_cancel_stream(self) -> None:
        if self.is_streaming and self._stream_worker is not None:
            self._stream_worker.cancel()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.name == "stream_response" and event.state in (
            WorkerState.SUCCESS,
            WorkerState.CANCELLED,
            WorkerState.ERROR,
        ):
            self._stream_worker = None
