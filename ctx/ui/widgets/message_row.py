"""The shared compact message-row renderer (task 36).

``MessageRow`` renders a single :class:`~ctx.models.nodes.Node` as the standard
two-line conversation row — a role-colored left bar, a right-docked meta slot
(drift glyph + weight %), and the node's (truncated) content. It is the single
surface behind every place the app shows a node as a compact row: the
conversation list (``MessageWidget`` subclasses it), the diff panes, and the
inspector splits.

The row owns no interaction state (cursor/selection/pass margins live on the
list's ``MessageWidget``). It also sets **no id** unless the caller supplies
one, so the same node can appear in more than one place (e.g. both diff panes)
without an id collision. Styling comes from ``widgets/message_list.css`` via the
``MessageRow`` type selector (which also matches its subclasses).
"""

from __future__ import annotations

from textual.color import Color
from textual.containers import Horizontal, Vertical
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


class MessageRow(Vertical):
    """A compact two-line node row (see module docstring)."""

    DEFAULT_CSS = ""

    def __init__(self, node: Node, *, truncate: bool = True, **kwargs) -> None:
        self.node = node
        self._role = node.role
        self._content = node.content
        # Rows in the diff *drill* view show a region's blocks in full (task 21);
        # the list and diff *overview* rows truncate per the role config.
        self._truncate = truncate
        extra = kwargs.pop("classes", "")
        super().__init__(classes=f"{node.role} {extra}".strip(), **kwargs)

    def on_mount(self) -> None:
        colors = get_config()["colors"]
        color_str = colors.get(self._role, colors["system"])
        self._border_color = Color.parse(color_str)
        style = "tall" if self._role in _TALL_ROLES else "solid"
        self.styles.border_left = (style, self._border_color)  # type: ignore[assignment]
        self._apply_truncation()

    def _apply_truncation(self) -> None:
        if not self._truncate:
            self.styles.max_height = None
            return
        truncation = get_config()["ui"]["truncation_lines"]
        limit = truncation.get(_TRUNCATION_KEY.get(self._role, "system"))
        if isinstance(limit, int):
            self.styles.max_height = limit
        else:  # "auto" (or anything non-int) disables truncation
            self.styles.max_height = None

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
        with Horizontal(classes="meta-slot"):
            yield Static("", classes="drift")
            yield Static("--%", classes="weight")
        if self._role in ("system", "context"):
            yield Static(self._content or "", classes="content")
        else:
            yield Markdown(self._content or "▌", classes="content")

    def update_content(self, content: str) -> None:
        self._content = content
        placeholder = "" if self._role == "system" else "▌"
        self.query_one(".content").update(content or placeholder)  # type: ignore[attr-defined]
