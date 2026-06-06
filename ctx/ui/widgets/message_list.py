from textual.containers import VerticalScroll, Vertical
from textual.widgets import Markdown, Static

from ctx.models.nodes import Node

ROLE_LABELS = {
    "user": "You",
    "assistant": "Assistant",
}


class MessageWidget(Vertical):
    DEFAULT_CSS = """
    MessageWidget {
        height: auto;
        border: round $primary;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    MessageWidget.user {
        border: round $success;
    }
    MessageWidget.assistant {
        border: round $accent;
    }
    MessageWidget > .role-label {
        text-style: bold;
        margin-bottom: 0;
    }
    """

    def __init__(self, node: Node, **kwargs) -> None:
        self.node = node
        self._role = node.role
        self._content = node.content
        super().__init__(
            id=f"msg-{node.id}",
            classes=node.role,
            **kwargs,
        )

    def compose(self):
        yield Static(ROLE_LABELS.get(self._role, self._role), classes="role-label")
        yield Markdown(self._content or "▌", classes="content")

    def update_content(self, content: str) -> None:
        self._content = content
        self.query_one(Markdown).update(content or "▌")


class MessageList(VerticalScroll):
    DEFAULT_CSS = """
    MessageList {
        scrollbar-size: 1 1;
    }
    """

    async def add_node(self, node: Node) -> None:
        widget = MessageWidget(node)
        await self.mount(widget)
        self.call_after_refresh(self.scroll_end)

    def update_content(self, node_id: str, content: str) -> None:
        try:
            widget = self.query_one(f"#msg-{node_id}", MessageWidget)
        except Exception:
            return
        widget.update_content(content)
        self.call_after_refresh(self.scroll_end)