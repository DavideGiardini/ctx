from textual.actions import SkipAction
from textual.binding import Binding
from textual.containers import VerticalScroll

from ctx.models.nodes import Node
from ctx.ui.widgets.message_row import _TALL_ROLES, MessageRow

# Which "conversation pass" a role belongs to. context imports are always
# human-invoked (/include), so they take the human side; only system nodes
# inherit the previous node's side, resolved positionally (see _pass_starts).
_SIDE = {
    "user": "human",
    "assistant": "assistant",
    "context": "human",
    # A K node folds a range that stood in the assistant's context; treat it as
    # the assistant side for conversation-pass margins.
    "compression": "assistant",
}


def _pass_starts(roles: list[str]) -> list[bool]:
    """For an ordered list of node roles, return whether each node begins a new
    conversation pass (gets a top margin). A pass is a human turn (query + its
    context imports) or an assistant turn (response + its imports); context nodes
    take the human side (they come from /include) and system nodes inherit the
    side of the preceding node. The first node is never a pass start.

    A compression node ``K`` *always* starts a new pass (unless it is the very
    first node): a summary of a folded run is its own block and must detach from
    the preceding turn, even when that turn is on the same (assistant) side it
    inherits — otherwise a K mounted right after an assistant reply hugs it with
    no blank margin and the two read as produced together (task 40).
    """
    starts: list[bool] = []
    prev_side: str | None = None
    for role in roles:
        side = _SIDE.get(role, prev_side)
        if role == "compression":
            starts.append(prev_side is not None)
        else:
            starts.append(prev_side is not None and side != prev_side)
        if side is not None:
            prev_side = side
    return starts


class MessageWidget(MessageRow):
    """A conversation-list row: the shared :class:`MessageRow` plus the list's
    interaction state (cursor/range selection, pass margins) and a stable
    ``msg-<node id>`` id the list queries by."""

    def __init__(self, node: Node, **kwargs) -> None:
        super().__init__(node, id=f"msg-{node.id}", **kwargs)

    def set_selected(self, selected: bool) -> None:
        self.set_class(selected, "selected")
        if self._role in _TALL_ROLES:
            style = "thick" if selected else "tall"
            self.styles.border_left = (style, self._border_color)  # type: ignore[assignment]

    def set_range_selected(self, selected: bool) -> None:
        """Toggle membership in a vim-style range selection (Q5). Distinct from
        ``set_selected`` (the single cursor): a range can span many widgets."""
        self.set_class(selected, "range-selected")

    def set_new_pass(self, is_new_pass: bool) -> None:
        self.set_class(is_new_pass, "pass-start")


class MessageList(VerticalScroll):
    DEFAULT_CSS = ""

    # In Edit mode the App owns up/down/home: they move the selection between
    # messages and scroll the selected one into view. VerticalScroll's inherited
    # scroll-by-arrow bindings only fall through to the App while the list fits
    # the viewport (action_scroll_* raises SkipAction when nothing can scroll);
    # once the list overflows they'd consume the keys and scroll instead of
    # navigating. Re-bind those keys to SkipAction unconditionally so navigation
    # always reaches the App. Programmatic scrolling (scroll_visible/scroll_end),
    # the mouse wheel, and pageup/pagedown/end are unaffected.
    BINDINGS = [
        Binding("up", "delegate_nav", show=False),
        Binding("down", "delegate_nav", show=False),
        Binding("home", "delegate_nav", show=False),
    ]

    def action_delegate_nav(self) -> None:
        raise SkipAction()

    async def add_node(self, node: Node) -> None:
        widget = MessageWidget(node)
        await self.mount(widget)
        self._apply_pass_margins()
        self.call_after_refresh(self.scroll_end)

    def _apply_pass_margins(self) -> None:
        widgets = list(self.query(MessageWidget))
        starts = _pass_starts([w._role for w in widgets])
        for widget, is_start in zip(widgets, starts, strict=True):
            widget.set_new_pass(is_start)

    def update_content(self, node_id: str, content: str) -> None:
        try:
            widget = self.query_one(f"#msg-{node_id}", MessageWidget)
        except Exception:
            return
        widget.update_content(content)
        self.call_after_refresh(self.scroll_end)
