"""Full right-pane context-diff view (ADR-0016 concern "b", Q12; task 20).

Replaces the message list while inspecting *how a turn's context drifted*: the
left column is the context the turn saw at generation
(``reconstruction.context_at_generation``), the right column that same ancestor
prefix as it stands now (``reconstruction.now_prefix``). Blocks are aligned **by
node id** (H6 — shared blocks are byte-identical, never a text diff); contiguous
changed regions are marked and a region cursor (``up``/``down``) walks them.

A warning banner is shown when reconstruction could not be verified against the
turn's stored ``ctx_hash`` (H4 honesty: refuse to confidently present a possibly
wrong left pane, cf. ``git fsck``).
"""

from __future__ import annotations

import contextlib

from textual.actions import SkipAction
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static

from ctx.core.reconstruction import DiffRegion


def _column(nodes) -> str:
    """Render one side of a region as plain text, one block per node."""
    if not nodes:
        return "(empty)"
    return "\n".join(f"[{n.role}] {n.content}" for n in nodes)


class DiffView(VerticalScroll):
    """Right-pane replacement rendering a turn's context-drift block diff."""

    can_focus = True

    # Let the App own up/down while the diff is focused: they move the region
    # cursor, not the scrollbar (mirrors MessageList's delegate_nav). Mouse wheel
    # and pageup/pagedown still scroll normally.
    BINDINGS = [
        Binding("up", "delegate_nav", show=False),
        Binding("down", "delegate_nav", show=False),
    ]

    def action_delegate_nav(self) -> None:
        raise SkipAction()

    DEFAULT_CSS = """
    DiffView {
        display: none;
        width: 1fr;
        height: 1fr;
    }
    DiffView #diff-warning {
        display: none;
        color: $warning;
        text-style: bold;
        padding: 0 1;
    }
    DiffView #diff-warning.shown { display: block; }
    DiffView .diff-region {
        height: auto;
        border-left: solid $surface;
        margin-bottom: 1;
    }
    DiffView .diff-region.changed { border-left: tall $warning; }
    DiffView .diff-region.cursor { border-left: thick $warning; }
    DiffView .diff-side { width: 1fr; padding: 0 1; }
    DiffView .diff-side-label { color: $text-muted; text-style: italic; }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="diff-warning")
        yield Vertical(id="diff-regions")

    async def show(self, regions: list[DiffRegion], warning: bool) -> None:
        """Render ``regions`` and toggle the reconstruction-inexact banner.

        The region cursor lands on the first **changed** region (the only ones
        the user navigates); an all-unchanged diff has no cursor.
        """
        banner = self.query_one("#diff-warning", Static)
        banner.update("⚠ reconstruction may be inexact" if warning else "")
        banner.set_class(warning, "shown")

        container = self.query_one("#diff-regions", Vertical)
        for child in list(container.children):
            await child.remove()
        for i, region in enumerate(regions):
            row = Horizontal(
                Vertical(
                    Static("was", classes="diff-side-label"),
                    Static(_column(region.left)),
                    classes="diff-side",
                ),
                Vertical(
                    Static("now", classes="diff-side-label"),
                    Static(_column(region.right)),
                    classes="diff-side",
                ),
                classes="diff-region changed" if region.changed else "diff-region",
                id=f"diff-region-{i}",
            )
            await container.mount(row)
        self._changed_indices = [i for i, r in enumerate(regions) if r.changed]
        self.set_cursor(0)
        self.display = True

    def close(self) -> None:
        """Hide the view (the caller restores the live message list)."""
        self.display = False

    def set_cursor(self, changed_pos: int) -> None:
        """Highlight the ``changed_pos``-th changed region (clamped; no-op when
        there are no changed regions)."""
        for row in self.query(".diff-region"):
            row.remove_class("cursor")
        if not self._changed_indices:
            return
        pos = max(0, min(changed_pos, len(self._changed_indices) - 1))
        self._cursor = pos
        region_index = self._changed_indices[pos]
        with contextlib.suppress(Exception):
            self.query_one(f"#diff-region-{region_index}").add_class("cursor")

    def move_cursor(self, step: int) -> None:
        """Move the changed-region cursor by ``step`` (clamped at the ends)."""
        if not self._changed_indices:
            return
        self.set_cursor(self._cursor + step)

    _changed_indices: list[int] = []
    _cursor: int = 0
