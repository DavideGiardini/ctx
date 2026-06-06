import asyncio

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.worker import Worker, WorkerState
from textual import work

from ctx.core.context import build_context
from ctx.core.log import logger
from ctx.core.provider import stream_response
from ctx.models.nodes import Node
from ctx.ui.widgets.input_bar import InputBar
from ctx.ui.widgets.message_list import MessageList

DEFAULT_MODEL = "openrouter/google/gemma-4-26b-a4b-it"


class ChatApp(App):
    CSS = """
    Screen {
        layout: vertical;
    }
    MessageList {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "cancel_stream", "Cancel", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.nodes: list[Node] = []
        self.model = DEFAULT_MODEL
        self._stream_worker: Worker | None = None
        logger.info("app initialized | default_model=%s", DEFAULT_MODEL)

    def compose(self) -> ComposeResult:
        yield MessageList()
        yield InputBar()

    def on_mount(self) -> None:
        self.query_one(InputBar).focus()

    async def on_input_bar_submitted(self, event: InputBar.Submitted) -> None:
        text = event.text.strip()
        if not text:
            return

        logger.info("input submitted | text=%r", text)

        if text.startswith("/model"):
            await self._handle_model_command(text)
            return

        user_node = Node(role="user", content=text)
        self.nodes.append(user_node)
        message_list = self.query_one(MessageList)
        await message_list.add_node(user_node)

        assistant_node = Node(role="assistant", content="")
        self.nodes.append(assistant_node)
        await message_list.add_node(assistant_node)

        self._stream_worker = self._stream_response(assistant_node)

    async def _handle_model_command(self, text: str) -> None:
        parts = text.split(maxsplit=1)
        if len(parts) == 1:
            logger.info("model queried | current=%s", self.model)
            await self._add_system_message(f"Current model: {self.model}")
        else:
            self.model = parts[1]
            logger.info("model switched | new_model=%s", self.model)
            await self._add_system_message(f"Model set to: {self.model}")

    async def _add_system_message(self, content: str) -> None:
        node = Node(role="assistant", content=content)
        self.nodes.append(node)
        await self.query_one(MessageList).add_node(node)

    @work(name="stream_response")
    async def _stream_response(self, node: Node) -> None:
        context_nodes = self.nodes[:-1]
        messages = build_context(context_nodes)
        message_list = self.query_one(MessageList)

        try:
            await stream_response(
                messages=messages,
                model=self.model,
                on_token=lambda token: self._on_token(node, token, message_list),
                on_done=lambda text: self._on_done(node, text),
                on_error=lambda exc: self._on_error(node, exc, message_list),
            )
        except asyncio.CancelledError:
            node.meta["interrupted"] = True
            logger.info("stream cancelled | partial_length=%d", len(node.content))
            message_list.update_content(node.id, node.content or "▌")
            raise

    def _on_token(self, node: Node, token: str, message_list: MessageList) -> None:
        node.content += token
        message_list.update_content(node.id, node.content)

    def _on_done(self, node: Node, text: str) -> None:
        node.content = text
        logger.info("response finalized | length=%d", len(text))

    def _on_error(self, node: Node, exc: Exception, message_list: MessageList) -> None:
        node.meta["error"] = str(exc)
        message_list.update_content(node.id, f"**Error:** {exc}")
        logger.error("stream error displayed | error=%s", exc)

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