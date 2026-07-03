from textual.actions import SkipAction
from textual.binding import Binding
from textual.color import Color
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Markdown, Static

from ctx.core.config import get_config
from ctx.models.nodes import Node

# Config key per node role for truncation lookups ("user" maps to "human").
_TRUNCATION_KEY = {
    "user": "human",
    "assistant": "assistant",
    "context": "context",
    "system": "system",
    # A compression summary stands in for a run of turns; truncate it like an
    # assistant reply (there is no separate "compression" truncation config).
    "compression": "assistant",
}

# Roles rendered as first-class turns: a "tall" left border (thick when the
# cursor selects them). Others (system) get a plain "solid" border.
_TALL_ROLES = ("user", "assistant", "context", "compression")

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
    """
    starts: list[bool] = []
    prev_side: str | None = None
    for role in roles:
        side = _SIDE.get(role, prev_side)
        starts.append(prev_side is not None and side != prev_side)
        if side is not None:
            prev_side = side
    return starts


class MessageWidget(Vertical):
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
        style = "tall" if self._role in _TALL_ROLES else "solid"
        self.styles.border_left = (style, self._border_color)  # type: ignore[assignment]
        self._apply_truncation()

    def _apply_truncation(self) -> None:
        truncation = get_config()["ui"]["truncation_lines"]
        limit = truncation.get(_TRUNCATION_KEY.get(self._role, "system"))
        if isinstance(limit, int):
            self.styles.max_height = limit
        else:  # "auto" (or anything non-int) disables truncation
            self.styles.max_height = None

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

    def set_weight_pct(self, pct: int | None) -> None:
        self.query_one(".weight", Static).update("--%" if pct is None else f"{pct}%")

    def set_weight_not_in_context(self) -> None:
        """Deep-dive rendering (Q9): a folded original is *not* part of the live
        context, so its weight slot reads "not in context" rather than a %."""
        self.query_one(".weight", Static).update("not in context")

    def set_drift(self, drifted: bool) -> None:
        """Toggle a subtle drift marker beside the weight slot (ADR-0016 concern
        "b", Q12/A#1, task 19): the AI turn's generation context has diverged from
        the current one. Deliberately quiet — many turns legitimately drift, so it
        is a single muted glyph, not an alarm."""
        self.set_class(drifted, "drifted")
        self.query_one(".drift", Static).update("Δ" if drifted else "")

    def compose(self):
        yield Static("--%", classes="weight")
        yield Static("", classes="drift")
        if self._role in ("system", "context"):
            yield Static(self._content or "", classes="content")
        else:
            yield Markdown(self._content or "▌", classes="content")

    def update_content(self, content: str) -> None:
        self._content = content
        placeholder = "" if self._role == "system" else "▌"
        self.query_one(".content").update(content or placeholder)  # type: ignore[attr-defined]


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
