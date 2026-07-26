"""Bottom docked footer: nano-style keybinding hints that change with the mode
(and, in Edit mode, the detail-pane sub-state), plus the active model. Single
source of truth for the hint strings (the agent snapshot reads ``current_hint``
to assert transitions).
"""

from textual.widgets import Static

# The Edit-mode hint is contextual (task 43c): the always-valid keys frame a
# middle slot that surfaces only the action valid for the current selection —
# ``x Expand`` on a compression K, nothing otherwise. ``_HINTS["edit"]`` is the
# no-selection base (head + tail).
_EDIT_HEAD = "↑↓ Nav  v Select  c Compress"
_EDIT_TAIL = "i/Esc Insert  Tab Pane  1/2/3 Splits  ^C Cancel"

_HINTS = {
    "insert": "Esc Edit  / Commands  ⇧↵/⌥↵ Newline  ^C Cancel",
    "edit": f"{_EDIT_HEAD}  {_EDIT_TAIL}",
    "browse": "↑↓ Move  Enter Select  1/2/3 Open  Esc Back  Tab Conversation",
    "maximized": "↑↓/PgUp/PgDn Scroll  1/2/3 Switch  Esc Back  Tab Conversation",
    "editor": "Tab Split  ^D Draft  ^S Commit  Esc Cancel",
}


class AppFooter(Static):
    DEFAULT_CSS = """
    AppFooter {
        dock: bottom;
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._mode = "insert"
        self._detail = "none"
        self._editor = False
        self._selected_type: str | None = None

    def on_mount(self) -> None:
        self._refresh()

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._detail = "none"  # a mode change resets any detail sub-state
        self._refresh()

    def set_detail(self, pane_mode: str) -> None:
        self._detail = pane_mode
        self._refresh()

    def set_editor(self, active: bool) -> None:
        self._editor = active
        self._refresh()

    def set_selection(self, node_type: str | None) -> None:
        """Record the current selection so the Edit-mode hint can advertise only
        its valid selection-dependent action (task 43c). ``node_type`` is the
        selected node's type (``None`` when nothing is selected)."""
        self._selected_type = node_type
        self._refresh()

    def _edit_hint(self) -> str:
        middle = "  x Expand" if self._selected_type == "compression" else ""
        return f"{_EDIT_HEAD}{middle}  {_EDIT_TAIL}"

    def current_hint(self) -> str:
        # The draft editor owns the pane while open, so its keys win outright.
        if self._editor:
            return _HINTS["editor"]
        if self._mode == "edit" and self._detail in ("browse", "maximized"):
            return _HINTS[self._detail]
        if self._mode == "edit":
            return self._edit_hint()
        return _HINTS.get(self._mode, _HINTS["insert"])

    def _refresh(self) -> None:
        self.update(self.current_hint())
