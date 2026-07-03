"""Left-pane Detail Inspector.

A deep widget: the interface is essentially "show this node." It hides the
branching between the standard view (full Markdown for human/assistant, italic
text for system) and the 3-split context view (Prompt / Content / Output), the
hiding of empty splits, and the in-place streaming append used while the view is
locked to the last node.

``NodeView`` decouples the widget from the core ``Node`` model — the app maps a
``Node`` into a ``NodeView`` at the seam.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Container, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Markdown, Static


@dataclass(frozen=True)
class NodeView:
    node_id: str
    role: str
    node_type: str
    content: str
    prompt: str = ""
    output: str = ""
    source_path: str | None = None


class _Split(VerticalScroll):
    """A focusable scroll region — one of the three context splits."""

    can_focus = True

    def action_page_up(self) -> None:
        self.scroll_page_up(animate=False)

    def action_page_down(self) -> None:
        self.scroll_page_down(animate=False)


# Logical split name -> (container id, text-widget id).
_SPLITS = {
    "prompt": ("#detail-prompt", "#detail-prompt-text"),
    "content": ("#detail-content", "#detail-content-text"),
    "output": ("#detail-output", "#detail-output-text"),
}

# Node types rendered as the 3-split view (vs. the standard Markdown view). A
# compression K reuses the context view's split machinery (browse/maximize/1-2-3)
# with per-type labels (ADR-0016, task 10): Prompt / Originals / Summary.
_SPLIT_VIEW_TYPES = ("context", "compression")

_SPLIT_LABELS = {
    "context": {"prompt": "Prompt", "content": "Content", "output": "Output"},
    "compression": {"prompt": "Prompt", "content": "Originals", "output": "Summary"},
}


class DetailInspector(Container):
    DEFAULT_CSS = """
    DetailInspector #detail-standard { height: 1fr; }
    DetailInspector #detail-context { height: 1fr; }
    DetailInspector #detail-prompt { height: 1fr; }
    DetailInspector #detail-content { height: 3fr; }
    DetailInspector #detail-output { height: 1fr; }
    DetailInspector .split-label {
        color: $text-muted;
        text-style: italic;
    }
    DetailInspector _Split:focus {
        background: $surface-lighten-1;
    }
    DetailInspector _Split.highlighted {
        background: $primary 20%;
    }
    DetailInspector #detail-empty {
        color: $text-disabled;
        padding: 1;
    }
    DetailInspector #detail-standard-text { text-style: italic; }
    """

    can_focus = True

    node_state: reactive[NodeView | None] = reactive(None, layout=True)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # Sub-state machine for keyboard navigation of the pane:
        #   "none"      — not entered (focus is elsewhere)
        #   "browse"    — 2+ splits shown, one highlighted (↑/↓ move highlight)
        #   "maximized" — one split fills the pane (↑/↓ scroll it)
        self.pane_mode: str = "none"
        self._highlight: str | None = None
        self._max_box: str | None = None
        self._maximized_name: str | None = None

    def compose(self) -> ComposeResult:
        with _Split(id="detail-standard"):
            yield Markdown("", id="detail-standard-md")
            yield Static("", id="detail-standard-text")
        with Vertical(id="detail-context"):
            with _Split(id="detail-prompt"):
                yield Static("Prompt", classes="split-label", id="detail-prompt-label")
                yield Static("", id="detail-prompt-text")
            with _Split(id="detail-content"):
                yield Static("Content", classes="split-label", id="detail-content-label")
                yield Static("", id="detail-content-text")
            with _Split(id="detail-output"):
                yield Static("Output", classes="split-label", id="detail-output-label")
                yield Static("", id="detail-output-text")
        yield Static("No node selected.", id="detail-empty")

    def on_mount(self) -> None:
        self._render_node(None)

    # --- interface -------------------------------------------------------

    def show(self, view: NodeView | None) -> None:
        self.node_state = view

    def append_stream(self, content: str) -> None:
        """Update the currently-shown node's body in place (per streaming token)
        without reassigning ``node_state`` (which would rebuild the subtree)."""
        if self.node_state is None or self.node_state.node_type in _SPLIT_VIEW_TYPES:
            return
        self.query_one("#detail-standard-md", Markdown).update(content)
        box = self.query_one("#detail-standard", VerticalScroll)
        self.call_after_refresh(lambda: box.scroll_end(animate=False))

    def enter_pane(self) -> str:
        """Tab into the pane. Returns the sub-state entered: "none" (empty),
        "browse" (2+ context splits) or "maximized" (single split / standard)."""
        kind = self.view_kind
        if kind == "empty":
            self.pane_mode = "none"
            return "none"
        if kind == "standard":
            self._maximize_box("#detail-standard", None)
            return "maximized"
        visible = self.splits_visible()
        if len(visible) <= 1:
            name = visible[0] if visible else "content"
            self._maximize_box(_SPLITS[name][0], name)
            return "maximized"
        self._enter_browse(visible)
        return "browse"

    def _enter_browse(self, visible: list[str]) -> None:
        self.pane_mode = "browse"
        self._max_box = None
        self._maximized_name = None
        self._highlight = visible[0]  # topmost visible split
        self._apply_highlight()

    def _apply_highlight(self) -> None:
        for name, (box_id, _) in _SPLITS.items():
            box = self.query_one(box_id, _Split)
            box.set_class(self.pane_mode == "browse" and name == self._highlight, "highlighted")

    def highlight_next(self) -> None:
        self._move_highlight(1)

    def highlight_prev(self) -> None:
        self._move_highlight(-1)

    def _move_highlight(self, step: int) -> None:
        if self.pane_mode != "browse":
            return
        visible = self.splits_visible()
        if self._highlight not in visible:
            return
        i = (visible.index(self._highlight) + step) % len(visible)
        self._highlight = visible[i]
        self._apply_highlight()

    def maximize(self, split: str | None = None) -> None:
        """Maximize the highlighted split (Enter in Browse)."""
        if self.pane_mode != "browse":
            return
        target = split or self._highlight
        if target:
            self._maximize_box(_SPLITS[target][0], target)

    def maximize_named(self, which: str) -> bool:
        """Maximize a named context split from any state (the 1/2/3 shortcut).
        No-op (returns False) when the split is hidden/absent."""
        ids = _SPLITS.get(which)
        view = self.node_state
        if not ids or view is None or view.node_type not in _SPLIT_VIEW_TYPES:
            return False
        value = {"prompt": view.prompt, "content": view.content, "output": view.output}[which]
        if not value:
            return False
        # Restore the full context layout first so switching the maximized split works.
        self._render_context(view)
        self._maximize_box(ids[0], which)
        return True

    def _maximize_box(self, box_id: str, split: str | None) -> None:
        self.pane_mode = "maximized"
        self._max_box = box_id
        self._maximized_name = split
        self._highlight = None
        if box_id != "#detail-standard":
            for _name, (bid, _) in _SPLITS.items():
                self.query_one(bid, _Split).display = bid == box_id
        for _name, (bid, _) in _SPLITS.items():
            self.query_one(bid, _Split).remove_class("highlighted")
        self.query_one(box_id, _Split).focus()

    def scroll_lines(self, delta: int) -> None:
        if self.pane_mode == "maximized" and self._max_box:
            self.query_one(self._max_box, _Split).scroll_relative(y=delta, animate=False)

    def back(self) -> str:
        """Esc: step back one level. Returns "browse" (un-maximized to Browse) or
        "exit" (caller should refocus the conversation)."""
        view = self.node_state
        if (
            self.pane_mode == "maximized"
            and view is not None
            and view.node_type in _SPLIT_VIEW_TYPES
        ):
            prev = self._maximized_name
            self._render_context(view)  # restore all visible splits
            visible = self.splits_visible()
            if len(visible) >= 2:
                self._enter_browse(visible)
                if prev in visible:
                    self._highlight = prev
                    self._apply_highlight()
                return "browse"
        self.exit_pane()
        return "exit"

    def exit_pane(self) -> None:
        self.pane_mode = "none"
        self._highlight = None
        self._max_box = None
        self._maximized_name = None
        for _name, (bid, _) in _SPLITS.items():
            self.query_one(bid, _Split).remove_class("highlighted")
        self._render_node(self.node_state)  # restore default visibility/sizes

    def highlighted_split(self) -> str | None:
        return self._highlight if self.pane_mode == "browse" else None

    def maximized_split(self) -> str | None:
        return self._maximized_name if self.pane_mode == "maximized" else None

    def splits_visible(self) -> list[str]:
        return [
            name
            for name, (box_id, _) in _SPLITS.items()
            if self.query_one(box_id, _Split).display
        ]

    @property
    def view_kind(self) -> str:
        view = self.node_state
        if view is None:
            return "empty"
        return "context" if view.node_type in _SPLIT_VIEW_TYPES else "standard"

    # --- rendering -------------------------------------------------------

    def watch_node_state(self, old: NodeView | None, new: NodeView | None) -> None:
        # A new node always resets the navigation sub-state (re-entry is fresh).
        self.pane_mode = "none"
        self._highlight = None
        self._max_box = None
        self._maximized_name = None
        self._render_node(new)

    def _render_node(self, view: NodeView | None) -> None:
        standard = self.query_one("#detail-standard", VerticalScroll)
        context = self.query_one("#detail-context", Vertical)
        empty = self.query_one("#detail-empty", Static)

        if view is None:
            standard.display = False
            context.display = False
            empty.display = True
            return

        empty.display = False
        if view.node_type in _SPLIT_VIEW_TYPES:
            standard.display = False
            context.display = True
            self._render_context(view)
        else:
            context.display = False
            standard.display = True
            self._render_standard(view)

    def _render_standard(self, view: NodeView) -> None:
        md = self.query_one("#detail-standard-md", Markdown)
        text = self.query_one("#detail-standard-text", Static)
        if view.role == "system":
            md.display = False
            text.display = True
            text.update(view.content)
        else:
            text.display = False
            md.display = True
            md.update(view.content)

    def _render_context(self, view: NodeView) -> None:
        values = {"prompt": view.prompt, "content": view.content, "output": view.output}
        labels = _SPLIT_LABELS.get(view.node_type, _SPLIT_LABELS["context"])
        any_visible = False
        for name, (box_id, text_id) in _SPLITS.items():
            box = self.query_one(box_id, _Split)
            value = values[name]
            box.display = bool(value)
            any_visible = any_visible or bool(value)
            self.query_one(text_id, Static).update(value)
            self.query_one(f"#detail-{name}-label", Static).update(labels[name])
        if not any_visible:
            # Defensive: a context node with no data at all still shows Content.
            self.query_one("#detail-content", _Split).display = True
            self.query_one("#detail-content-text", Static).update("(no content)")
