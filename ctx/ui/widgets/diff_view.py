"""Full-screen two-pane context-diff view (ADR-0016 concern "b", Q12; tasks 20/21/37).

Replaces the whole body while inspecting *how a turn's context drifted*. Two
side-by-side panes render the turn's context as the standard compact node rows
(the shared :class:`~ctx.ui.widgets.message_row.MessageRow`): the **left** pane is
the context the turn saw at generation (``reconstruction.context_at_generation``),
the **right** pane that same ancestor prefix as it stands now
(``reconstruction.now_prefix``). Rows are aligned **by node id** (H6 — shared
blocks are byte-identical, never a text diff); the rows of each contiguous
*changed* region are highlighted and a region cursor (``up``/``down``) walks them.

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
from ctx.ui.widgets.message_row import MessageRow


class DiffView(Vertical):
    """Full-screen two-pane context-drift diff (compact rows, aligned by id)."""

    can_focus = True

    # Let the App own up/down while the diff is focused: they move the region
    # cursor, not a scrollbar (mirrors MessageList's delegate_nav). Mouse wheel
    # and pageup/pagedown still scroll the panes normally.
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
    DiffView .diff-panes { height: 1fr; }
    DiffView .diff-pane { width: 1fr; height: 1fr; }
    /* A visible seam between the two panes. */
    DiffView #diff-left, DiffView #diff-drill-left { border-right: solid $surface; }
    DiffView .diff-side-label {
        color: $text-muted;
        text-style: italic;
        padding: 0 1;
        height: 1;
    }
    DiffView .diff-rows { height: 1fr; scrollbar-size: 1 1; }
    /* Highlight the rows of a changed region; brighten the cursored one. */
    DiffView MessageRow.changed { background: $warning 15%; }
    DiffView MessageRow.cursor { background: $warning 30%; }
    DiffView .diff-empty {
        color: $text-disabled;
        text-style: italic;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    DiffView #diff-drill { display: none; }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="diff-warning")
        with Horizontal(id="diff-overview", classes="diff-panes"):
            with Vertical(classes="diff-pane"):
                yield Static("was — context at generation", classes="diff-side-label")
                yield VerticalScroll(id="diff-left", classes="diff-rows")
            with Vertical(classes="diff-pane"):
                yield Static("now — current context", classes="diff-side-label")
                yield VerticalScroll(id="diff-right", classes="diff-rows")
        with Horizontal(id="diff-drill", classes="diff-panes"):
            with Vertical(classes="diff-pane"):
                yield Static("was", classes="diff-side-label")
                yield VerticalScroll(id="diff-drill-left", classes="diff-rows")
            with Vertical(classes="diff-pane"):
                yield Static("now", classes="diff-side-label")
                yield VerticalScroll(id="diff-drill-right", classes="diff-rows")

    async def _mount_side(
        self,
        pane: VerticalScroll,
        nodes: list,
        *,
        changed: bool,
        truncate: bool = True,
    ) -> list[MessageRow]:
        """Mount one region-side's nodes as compact rows, returning the rows.

        A changed region with an empty side (a pure add/remove) mounts a muted
        placeholder so the asymmetry is visible; placeholders are not tracked for
        the cursor (there is no row to walk to)."""
        rows: list[MessageRow] = []
        if not nodes:
            if changed:
                await pane.mount(Static("(none)", classes="diff-empty"))
            return rows
        for node in nodes:
            row = MessageRow(
                node, truncate=truncate, classes="changed" if changed else ""
            )
            await pane.mount(row)
            rows.append(row)
        return rows

    async def show(self, regions: list[DiffRegion], warning: bool) -> None:
        """Render ``regions`` into the two panes and toggle the banner.

        The left pane is filled with every region's ``left`` blocks and the right
        pane with every region's ``right`` blocks (aligned by id via the region
        sequence). The region cursor lands on the first **changed** region (the
        only ones the user navigates); an all-unchanged diff has no cursor.
        """
        banner = self.query_one("#diff-warning", Static)
        banner.update("⚠ reconstruction may be inexact" if warning else "")
        banner.set_class(warning, "shown")

        left_pane = self.query_one("#diff-left", VerticalScroll)
        right_pane = self.query_one("#diff-right", VerticalScroll)
        for pane in (left_pane, right_pane):
            for child in list(pane.children):
                await child.remove()

        self._region_rows = []
        self._changed_indices = []
        for i, region in enumerate(regions):
            left_rows = await self._mount_side(left_pane, region.left, changed=region.changed)
            right_rows = await self._mount_side(right_pane, region.right, changed=region.changed)
            self._region_rows.append([*left_rows, *right_rows])
            if region.changed:
                self._changed_indices.append(i)
        self.set_cursor(0)
        self.close_drill()
        self.display = True

    async def show_drill(self, region: DiffRegion) -> None:
        """Drill into one changed ``region``: render its left/right block
        sequences in full (untruncated) and hide the overview (H6 many-to-many;
        task 21)."""
        left = self.query_one("#diff-drill-left", VerticalScroll)
        right = self.query_one("#diff-drill-right", VerticalScroll)
        for pane in (left, right):
            for child in list(pane.children):
                await child.remove()
        await self._mount_side(left, region.left, changed=region.changed, truncate=False)
        await self._mount_side(right, region.right, changed=region.changed, truncate=False)
        self.query_one("#diff-overview").display = False
        self.query_one("#diff-drill").display = True

    def close_drill(self) -> None:
        """Return from a drilled region to the overview (no-op if not drilled)."""
        self.query_one("#diff-drill").display = False
        self.query_one("#diff-overview").display = True

    @property
    def cursor(self) -> int:
        """Position of the cursored region among the changed regions."""
        return self._cursor

    def close(self) -> None:
        """Hide the view (the caller restores the live message list)."""
        self.close_drill()
        self.display = False

    def set_cursor(self, changed_pos: int) -> None:
        """Highlight the ``changed_pos``-th changed region's rows (clamped; no-op
        when there are no changed regions)."""
        for rows in self._region_rows:
            for row in rows:
                row.remove_class("cursor")
        if not self._changed_indices:
            self._cursor = 0
            return
        pos = max(0, min(changed_pos, len(self._changed_indices) - 1))
        self._cursor = pos
        region_index = self._changed_indices[pos]
        cursored = self._region_rows[region_index]
        for row in cursored:
            row.add_class("cursor")
        if cursored:
            with contextlib.suppress(Exception):
                cursored[0].scroll_visible(animate=False)

    def move_cursor(self, step: int) -> None:
        """Move the changed-region cursor by ``step`` (clamped at the ends)."""
        if not self._changed_indices:
            return
        self.set_cursor(self._cursor + step)

    _region_rows: list[list[MessageRow]] = []
    _changed_indices: list[int] = []
    _cursor: int = 0
