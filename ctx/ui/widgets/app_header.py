"""Top docked header: conversation title (left), CTX logo (center), context
gauge (right).

The context gauge is a placeholder until token counting lands — ``set_context_pct``
accepts ``None`` and renders ``--%`` with an empty bar. The slot and wiring are
real so the percentage drops in later without a layout change.
"""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

_BAR_WIDTH = 10


class AppHeader(Horizontal):
    DEFAULT_CSS = """
    AppHeader {
        dock: top;
        height: 1;
        background: $panel;
    }
    AppHeader #hdr-title {
        width: 1fr;
        content-align: left middle;
        padding: 0 1;
    }
    AppHeader #hdr-logo {
        width: auto;
        content-align: center middle;
        text-style: bold;
    }
    AppHeader #hdr-context {
        width: auto;
        content-align: right middle;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="hdr-title")
        yield Static("CTX", id="hdr-logo")
        yield Static(self._gauge(None), id="hdr-context")

    def set_title(self, title: str) -> None:
        self.query_one("#hdr-title", Static).update(title or "untitled")

    def set_context_pct(self, pct: int | None) -> None:
        self.query_one("#hdr-context", Static).update(self._gauge(pct))

    @staticmethod
    def _gauge(pct: int | None) -> str:
        if pct is None:
            return f"--% [{' ' * _BAR_WIDTH}]"
        filled = max(0, min(_BAR_WIDTH, round(pct / 100 * _BAR_WIDTH)))
        bar = "=" * filled + " " * (_BAR_WIDTH - filled)
        return f"{pct}% [{bar}]"
