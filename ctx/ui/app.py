import asyncio
import contextlib

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.widgets import Input, Static
from textual.worker import Worker, WorkerState

from ctx.core.conversation import DEFAULT_MODEL, ConversationCore
from ctx.core.log import logger
from ctx.core.provider import LiteLLMProvider
from ctx.core.storage import ConversationRepository
from ctx.core.workspace import get_db_path, list_context_files
from ctx.models.nodes import Node
from ctx.ui.widgets.file_viewer import FileViewer, FileViewerScreen
from ctx.ui.widgets.history_screen import HistoryScreen
from ctx.ui.widgets.include_screen import IncludeScreen
from ctx.ui.widgets.input_bar import InputBar
from ctx.ui.widgets.message_list import MessageList, MessageWidget


class ChatApp(App):
    CSS_PATH = [
        "app.css",
        "widgets/message_list.css",
        "widgets/input_bar.css",
    ]

    BINDINGS = [
        Binding("ctrl+c", "cancel_stream", "Cancel", show=False),
        Binding("escape", "dismiss_commands", "Dismiss", show=False),
        Binding("up", "select_prev", "Previous Message", show=False),
        Binding("down", "select_next", "Next Message", show=False),
        Binding("i", "enter_insert", "Insert Mode", show=False),
        Binding("o", "open_fullscreen", "Open file", show=False),
        Binding("v", "toggle_split", "Toggle split", show=False),
        Binding("ctrl+v", "close_split", "Close split", show=False),
        Binding("tab", "switch_focus", "Switch focus", show=False, priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._repo = ConversationRepository(str(get_db_path()))
        self.core = ConversationCore(self._repo, LiteLLMProvider())
        self._stream_worker: Worker | None = None
        self.mode = "insert"
        self._selected_node_id: str | None = None
        self._split_active: bool = False
        self._split_file_path: str | None = None
        logger.info("app initialized | default_model=%s", DEFAULT_MODEL)

    def compose(self) -> ComposeResult:
        with Horizontal(id="main-area"):
            yield MessageList()
            yield FileViewer(id="split-viewer")
        with Container(id="input-area"):
            yield Static("", id="command-suggestions")
            yield InputBar()
            yield Static("", id="model-label")

    def on_mount(self) -> None:
        self.core.setup()
        self.query_one(InputBar).focus()
        self._update_model_label()

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
        for node in reversed(self.core.nodes):
            if node.role != "system":
                self._select_message(node.id)
                break
        logger.info("entered edit mode")

    def _enter_insert_mode(self) -> None:
        if self.mode == "insert":
            return
        self.mode = "insert"
        self._clear_selection()
        self.query_one(InputBar).focus()
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
            return
        try:
            widget = message_list.query_one(f"#msg-{node_id}", MessageWidget)
            widget.set_selected(True)
            widget.scroll_visible()
        except Exception:
            pass

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
        for offset in range(1, len(self.core.nodes) + 1):
            idx = (start - offset) % len(self.core.nodes)
            if self.core.nodes[idx].role != "system":
                self._select_message(self.core.nodes[idx].id)
                return

    def action_select_next(self) -> None:
        if self.mode != "edit" or not self.core.nodes:
            return
        if self._selected_node_id is None:
            start = -1
        else:
            start = next(
                (i for i, n in enumerate(self.core.nodes) if n.id == self._selected_node_id), -1
            )
        for offset in range(1, len(self.core.nodes) + 1):
            idx = (start + offset) % len(self.core.nodes)
            if self.core.nodes[idx].role != "system":
                self._select_message(self.core.nodes[idx].id)
                return

    def action_enter_insert(self) -> None:
        if self.mode == "edit":
            self._enter_insert_mode()

    def _get_selected_node(self) -> Node | None:
        if self._selected_node_id is None:
            return None
        for node in self.core.nodes:
            if node.id == self._selected_node_id:
                return node
        return None

    def action_open_fullscreen(self) -> None:
        if self.mode != "edit":
            return
        node = self._get_selected_node()
        if not node or node.node_type != "context":
            return
        source_path = node.meta.get("source_path")
        if not source_path:
            return
        self.push_screen(FileViewerScreen(file_path=source_path))

    def action_toggle_split(self) -> None:
        if self.mode != "edit":
            return
        node = self._get_selected_node()
        if not node or node.node_type != "context":
            return
        source_path = node.meta.get("source_path")
        if not source_path:
            return
        split_viewer = self.query_one("#split-viewer", FileViewer)
        split_viewer.display = True
        split_viewer.load_file(source_path)
        self._split_active = True
        self._split_file_path = source_path
        split_viewer.focus()

    def _close_split(self) -> None:
        split_viewer = self.query_one("#split-viewer", FileViewer)
        split_viewer.display = False
        split_viewer.clear()
        self._split_active = False
        self._split_file_path = None
        if self.mode == "edit":
            with contextlib.suppress(Exception):
                self.query_one(MessageList).focus()

    def action_close_split(self) -> None:
        if self._split_active:
            self._close_split()

    def _is_focused_in(self, widget) -> bool:
        focused = self.focused
        if focused is None:
            return False
        if focused == widget:
            return True
        return focused in widget.walk_children()

    def action_switch_focus(self) -> None:
        if self.mode != "edit":
            return
        message_list = self.query_one(MessageList)
        if not self._split_active:
            message_list.focus()
            return
        split_viewer = self.query_one("#split-viewer", FileViewer)
        if self._is_focused_in(split_viewer):
            message_list.focus()
        else:
            split_viewer.focus()

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

    def _update_model_label(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#model-label", Static).update(self.core.model)

    async def _handle_model_command(self, text: str) -> None:
        parts = text.split(maxsplit=1)
        if len(parts) == 1:
            logger.info("model queried | current=%s", self.core.model)
            node = self.core.query_model()
        else:
            new_model = parts[1]
            node = self.core.set_model(new_model)
            self._update_model_label()
            logger.info("model switched | new_model=%s", new_model)
            self._check_connectivity(new_model)
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
        logger.info("loaded conversation | id=%s | nodes=%d", result, len(nodes))

    @work(name="handle_include")
    async def _handle_include_command(self) -> None:
        files = list_context_files()
        if not files:
            node = self.core.add_system_message("No files in .ctx/context/ to include.")
            await self.query_one(MessageList).add_node(node)
            return
        result = await self.push_screen_wait(IncludeScreen())
        if not result:
            return
        nodes = self.core.include_files(result)
        message_list = self.query_one(MessageList)
        for node in nodes:
            await message_list.add_node(node)
            logger.info("context included | path=%s", node.meta.get("source_path", ""))

    @work(name="stream_response")
    async def _stream_response(self, assistant_node: Node) -> None:
        message_list = self.query_one(MessageList)
        try:
            async for _token in self.core.stream(assistant_node):
                message_list.update_content(assistant_node.id, assistant_node.content)
            logger.info("response finalized | length=%d", len(assistant_node.content))
        except asyncio.CancelledError:
            assistant_node.meta["interrupted"] = True
            message_list.update_content(assistant_node.id, assistant_node.content or "▌")
            self.core.persist()
            raise
        except Exception as exc:
            assistant_node.meta["error"] = str(exc)
            message_list.update_content(assistant_node.id, f"**Error:** {exc}")
            logger.error("stream error | error=%s", exc)

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
