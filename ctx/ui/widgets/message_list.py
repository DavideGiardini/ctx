from textual.color import Color
from textual.containers import VerticalScroll, Vertical
from textual.widgets import Markdown, Static

from ctx.core.config import get_config
from ctx.models.nodes import Node


class MessageWidget(Vertical):
    DEFAULT_CSS = """
    MessageWidget {
        height: auto;
        padding: 0 1 0 2;
        margin: 0 0 1 0;
    }
    MessageWidget.system {
        text-style: italic;
    }
    MessageWidget Markdown {
        padding: 1 2 1 2;
    }
    MessageWidget Markdown > MarkdownParagraph {
        margin: 0;
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

    def on_mount(self) -> None:
        colors = get_config()["colors"]
        color_str = colors.get(self._role, colors["system"])
        color = Color.parse(color_str)
        style = "tall" if self._role in ("user", "assistant") else "solid"
        self.styles.border_left = (style, color)

    def compose(self):
        if self._role == "system":
            yield Static(self._content or "", classes="content")
        else:
            yield Markdown(self._content or "▌", classes="content")

    def update_content(self, content: str) -> None:
        self._content = content
        placeholder = "" if self._role == "system" else "▌"
        self.query_one(".content").update(content or placeholder)


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