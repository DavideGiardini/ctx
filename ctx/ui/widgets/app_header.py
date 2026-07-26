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
    /* CTX spans the full header width and centers, then ``align_logo`` nudges it
       onto the seam column. It lives on its own layer so the model/gauge box
       widths can never shift it (the earlier flex layout only aligned by rounding
       luck). Model/gauge text use the config muted color ($ctx-muted):
       $text-muted (ansi_default 50%) renders full-strength because the dim
       attribute only kicks in below 50%. */
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

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._logo_offset: int | None = None

    def compose(self) -> ComposeResult:
        yield Static("CTX", id="hdr-logo")
        yield Static("", id="hdr-model")
        yield Static(self._gauge(None), id="hdr-context")

    def align_logo(self, column: int) -> None:
        """Sit the logo's middle glyph on ``column`` — the pane seam.

        The caller passes the seam's real column rather than the header working
        it out: the header has no business knowing how the body splits, and every
        version of that guess has eventually gone stale (it used to assume two
        1fr panes divided by a border, which rounding alone broke on odd widths).

        ``content-align: center`` puts the 3-glyph logo's middle at
        ``(width - 3) // 2 + 1``; the offset is whatever closes the gap from there.
        """
        if column < 0 or self.size.width <= 0:
            return
        offset = column - ((self.size.width - 3) // 2 + 1)
        if offset == self._logo_offset:
            return
        self._logo_offset = offset
        self.query_one("#hdr-logo", Static).styles.offset = (offset, 0)

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
