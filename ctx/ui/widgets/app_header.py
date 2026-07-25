"""Top docked header: active model (left), CTX logo (center), context
gauge (right).

The context gauge shows the share of the model's input window the conversation
consumes. ``set_context_pct`` accepts ``None`` (window unknown → ``--%`` with an
empty bar) and an ``approximate`` flag: when the figure rests on the local token
estimate alone — no provider ``usage`` anchor yet, or the node set changed since
the last measured turn — the gauge wears a leading ``~`` to mark it as an
estimate rather than an exact count.
"""

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

_BAR_WIDTH = 10


class AppHeader(Container):
    DEFAULT_CSS = """
    AppHeader {
        dock: top;
        height: 1;
        layers: logo labels;
    }
    /* CTX spans the full header width and centers, so its middle glyph lands on
       the body's horizontal center — the same column as the pane divider. It
       lives on its own layer so the model/gauge box widths can never shift it
       (the earlier flex layout only aligned by rounding luck). Model/gauge text
       use the config muted color ($ctx-muted): $text-muted (ansi_default 50%)
       renders full-strength because the dim attribute only kicks in below 50%. */
    AppHeader #hdr-logo {
        layer: logo;
        width: 100%;
        height: 1;
        content-align: center middle;
        text-style: bold;
    }
    AppHeader #hdr-model {
        layer: labels;
        dock: left;
        width: auto;
        color: $ctx-muted;
        padding: 0 1;
    }
    AppHeader #hdr-context {
        layer: labels;
        dock: right;
        width: auto;
        content-align: right middle;
        color: $ctx-muted;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("CTX", id="hdr-logo")
        yield Static("", id="hdr-model")
        yield Static(self._gauge(None), id="hdr-context")

    def on_resize(self) -> None:
        self._align_logo()

    def _align_logo(self) -> None:
        """Sit the CTX logo's middle glyph exactly on the pane divider.

        The body is two 1fr panes with a 1-cell ``border-right`` on the left one
        (app.css), so the divider column is always ``width // 2 - 1``. A plain
        ``content-align: center`` puts the 3-char logo's middle glyph at
        ``(width - 3) // 2 + 1`` — which matches the divider on even widths but
        lands one cell right of it on odd widths. Nudge the logo by that exact
        delta (0 or -1) so it aligns at every terminal width, not just even ones.
        """
        w = self.size.width
        if w <= 0:
            return
        divider = w // 2 - 1
        centered_glyph = (w - 3) // 2 + 1
        logo = self.query_one("#hdr-logo", Static)
        logo.styles.offset = (divider - centered_glyph, 0)

    def set_model(self, model: str) -> None:
        self.query_one("#hdr-model", Static).update(model or "")

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
