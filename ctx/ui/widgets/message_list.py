from textual.color import Color
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Markdown, Static

from ctx.core.config import get_config
from ctx.core.conversation import TokenUsage
from ctx.models.nodes import Node


class MessageWidget(Horizontal):
    DEFAULT_CSS = ""

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
        self._border_color = Color.parse(color_str)
        style = "heavy" if self._role in ("user", "assistant", "context") else "solid"
        self.styles.border_left = (style, self._border_color)  # type: ignore[assignment]

        # Truncation: clamp the *content* widget to the configured max-height
        config = get_config()
        lines = config.get("ui", {}).get("truncation_lines", {}).get(self._role, "auto")
        if lines != "auto":
            content = self.query_one(".content")
            content.styles.max_height = lines
            content.styles.overflow = ("hidden", "hidden")  # type: ignore[attr-defined]

    def set_selected(self, selected: bool) -> None:
        self.set_class(selected, "selected")
        if self._role in ("user", "assistant", "context"):
            style = "thick" if selected else "heavy"
            self.styles.border_left = (style, self._border_color)  # type: ignore[assignment]

    def compose(self):
        # Content first (left), weight second (right) for Horizontal layout
        if self._role in ("system", "application", "context"):
            yield Static(self._content or "", classes="content")
        else:
            yield Markdown(self._content or "▌", classes="content")
        # Weight indicator (right-aligned) — not shown for system/application
        if self._role not in ("system", "application"):
            yield Static("0%", classes="weight")

    def update_content(self, content: str) -> None:
        self._content = content
        placeholder = "" if self._role in ("system", "application") else "▌"
        self.query_one(".content").update(content or placeholder)  # type: ignore[attr-defined]

    def update_weight(self, percent: int) -> None:
        """Refresh the right-aligned context-weight indicator."""
        try:
            weight = self.query_one(".weight", Static)
            weight.update(f"{percent}%")
        except Exception:
            pass  # no weight indicator for system/application


class MessageList(VerticalScroll):
    DEFAULT_CSS = ""

    async def add_node(self, node: Node) -> None:
        widget = MessageWidget(node)

        # ── Spacing: every message after the first gets a top margin,
        #     UNLESS the immediately preceding message is a context/system/application node ──
        prev_widgets = [w for w in self.children if isinstance(w, MessageWidget)]
        if prev_widgets:
            last_widget = prev_widgets[-1]
            if last_widget.node.role not in ("context", "system", "application"):
                widget.add_class("new-pass")

        await self.mount(widget)
        self.call_after_refresh(self.scroll_end)

    def update_content(self, node_id: str, content: str) -> None:
        try:
            widget = self.query_one(f"#msg-{node_id}", MessageWidget)
        except Exception:
            return
        widget.update_content(content)
        self.call_after_refresh(self.scroll_end)

    def update_weights(self, usage: TokenUsage) -> None:
        """Refresh each message's context-weight indicator from a token-usage snapshot."""
        if usage.total <= 0:
            return
        for widget in self.query(MessageWidget):
            count = usage.per_node.get(widget.node.id, 0)
            widget.update_weight(round((count / usage.total) * 100))
