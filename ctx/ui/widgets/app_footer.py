"""Bottom docked footer: nano-style keybinding hints that change with the mode
(and, in Edit mode, the detail-pane sub-state), plus the active model. Single
source of truth for the hint strings (the agent snapshot reads ``current_hint``
to assert transitions).
"""

from textual.widgets import Static

_HINTS = {
    "insert": "Esc Edit  / Commands  ^C Cancel",
    "edit": (
        "↑↓ Nav  v Select  c Compress  x Expand  "
        "i/Esc Insert  Tab Pane  1/2/3 Splits  ^C Cancel"
    ),
    "browse": "↑↓ Move  Enter Select  1/2/3 Open  Esc Back  Tab Conversation",
    "maximized": "↑↓/PgUp/PgDn Scroll  1/2/3 Switch  Esc Back  Tab Conversation",
    "deep_dive": "↑↓ Nav  ^o/Esc Back  i Exit  Tab Pane  (read-only)",
}


class AppFooter(Static):
    DEFAULT_CSS = """
    AppFooter {
        dock: bottom;
        height: 1;
        background: $panel;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._mode = "insert"
        self._detail = "none"
        self._deep_dive = False
        self._model = ""

    def on_mount(self) -> None:
        self._refresh()

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._detail = "none"  # a mode change resets any detail sub-state
        self._refresh()

    def set_detail(self, pane_mode: str) -> None:
        self._detail = pane_mode
        self._refresh()

    def set_deep_dive(self, active: bool) -> None:
        self._deep_dive = active
        self._refresh()

    def set_model(self, model: str) -> None:
        self._model = model
        self._refresh()

    def current_hint(self) -> str:
        if self._mode == "edit" and self._detail in ("browse", "maximized"):
            return _HINTS[self._detail]
        if self._deep_dive:
            return _HINTS["deep_dive"]
        return _HINTS.get(self._mode, _HINTS["insert"])

    def _refresh(self) -> None:
        hint = self.current_hint()
        line = f"{hint}    [dim]{self._model}[/dim]" if self._model else hint
        self.update(line)
