"""The vertical seam between the two panes.

Its own one-column widget rather than a neighbour's ``border-right``, so that the
horizontal rules running into it can actually *meet* it. Two CSS borders never
join: ``─`` paints the full width of its cell while ``│`` paints only the middle
of the next one, so every rule appears to stop half a cell short of the seam.
Owning the column lets the meeting row carry a real junction glyph instead.

Which rows are junctions is derived from the layout rather than configured: any
widget wearing the ``seam-rule`` class whose region runs flush against this
column contributes its top or bottom border row, on whichever side it sits. Move
a rule, hide a split, grow the input — the seam follows.
"""

from __future__ import annotations

from rich.segment import Segment
from textual.strip import Strip
from textual.widget import Widget

# Class a widget wears to declare that its horizontal border is part of the
# chrome and should join the seam where the two meet.
RULE_CLASS = "seam-rule"

# (a rule arrives from the left, a rule arrives from the right) -> glyph
_GLYPHS = {
    (False, False): "│",
    (True, False): "┤",
    (False, True): "├",
    (True, True): "┼",
}

_Junctions = tuple[frozenset[int], frozenset[int]]


class PaneSeam(Widget):
    DEFAULT_CSS = """
    PaneSeam {
        width: 1;
        height: 1fr;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._junctions: _Junctions = (frozenset(), frozenset())
        self._rules: list[Widget] | None = None

    def on_mount(self) -> None:
        self.call_after_refresh(self.sync)

    def on_resize(self) -> None:
        self.sync()

    def sync(self) -> None:
        """Recompute the junction rows, repainting only if they moved.

        Called on every idle tick (``ChatApp.on_idle``) because there is no event
        to listen for: a sibling growing or a split hiding never touches this
        widget's own geometry, and Textual repaints only regions that changed, so
        the seam would keep a stale junction. The check reads three regions and
        the repaint is one column, so polling costs nothing.
        """
        if not self.is_mounted:
            return
        junctions = self._discover()
        if junctions != self._junctions:
            self._junctions = junctions
            self.refresh()

    # AIDEV-NOTE: resolved once — every rule-bearing widget is composed up front.
    # One mounted later would go unnoticed; drop the cache if that changes (the
    # query walks the whole message list, and this runs on every idle tick).
    def _rule_widgets(self) -> list[Widget]:
        if self._rules is None:
            self._rules = list(self.screen.query(f".{RULE_CLASS}"))
        return self._rules

    def _discover(self) -> _Junctions:
        column = self.region.x
        left: set[int] = set()
        right: set[int] = set()
        for widget in self._rule_widgets():
            region = widget.region
            if not region.area:
                continue
            if region.right == column:
                rows = left
            elif region.x == column + 1:
                rows = right
            else:
                continue
            if widget.styles.border_top[0]:
                rows.add(region.y)
            if widget.styles.border_bottom[0]:
                rows.add(region.bottom - 1)
        return frozenset(left), frozenset(right)

    def render_line(self, y: int) -> Strip:
        left, right = self._junctions
        row = self.region.y + y
        return Strip([Segment(_GLYPHS[(row in left, row in right)], self.rich_style)], 1)
