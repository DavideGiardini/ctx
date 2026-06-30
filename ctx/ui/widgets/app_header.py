"""Top docked header: conversation title (left), CTX logo (center), context
gauge (right).

The context gauge shows the share of the model's input window the conversation
consumes. ``set_context_pct`` accepts ``None`` (window unknown → ``--%`` with an
empty bar) and an ``approximate`` flag: when the figure rests on the local token
estimate alone — no provider ``usage`` anchor yet, or the node set changed since
the last measured turn — the gauge wears a leading ``~`` to mark it as an
estimate rather than an exact count.
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

    def set_context_pct(self, pct: int | None, approximate: bool = False) -> None:
        self.query_one("#hdr-context", Static).update(self._gauge(pct, approximate))

    @staticmethod
    def _gauge(pct: int | None, approximate: bool = False) -> str:
        if pct is None:
            # Window unknown: there is no number to qualify, so no ``~``.
            return f"--% [{' ' * _BAR_WIDTH}]"
        filled = max(0, min(_BAR_WIDTH, round(pct / 100 * _BAR_WIDTH)))
        bar = "=" * filled + " " * (_BAR_WIDTH - filled)
        prefix = "~" if approximate else ""
        return f"{prefix}{pct}% [{bar}]"
