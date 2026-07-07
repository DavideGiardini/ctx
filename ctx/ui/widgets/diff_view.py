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

# Uniform height (rows) each overview row/placeholder/filler occupies, so a
# region's blank-padded shorter side lines up with its taller side and the
# *next* region stays row-aligned across the two panes (task 50). Fixed rather
# than content-driven precisely so the padding count is deterministic; drill
# rows stay auto-height (full untruncated content, single region, no alignment).
OVERVIEW_ROW_HEIGHT = 2


def region_slot_count(region: DiffRegion) -> int:
    """Vertical row-slots a diff region occupies in *each* overview pane.

    Both panes render this many slots for the region — the taller side's row
    count — so the shorter side is blank-padded to match and the following
    region still lines up. An unchanged region's two sides are equal already,
    so this is just their shared length."""
    return max(len(region.left), len(region.right))


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
    /* Blank filler padding the shorter side of a changed region up to the
       taller side's slot count (task 50). Shares the row footprint (height set
       inline to OVERVIEW_ROW_HEIGHT + this margin) but carries no content and
       is never a cursor target. */
    DiffView .diff-filler { margin: 0 0 1 0; }
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
        pad_to: int | None = None,
    ) -> list[MessageRow]:
        """Mount one region-side's nodes as compact rows, returning the rows.

        A changed region with an empty side (a pure add/remove) mounts a muted
        placeholder so the asymmetry is visible; placeholders are not tracked for
        the cursor (there is no row to walk to).

        When ``pad_to`` is given (the overview), every row/placeholder is pinned
        to :data:`OVERVIEW_ROW_HEIGHT` and the side is blank-padded with filler
        rows up to ``pad_to`` slots, so a region occupies equal vertical space in
        both panes and following regions stay aligned (task 50). Fillers carry no
        content and are never cursor targets (like the ``(none)`` placeholder)."""
        rows: list[MessageRow] = []
        occupied = 0
        if not nodes:
            if changed:
                placeholder = Static("(none)", classes="diff-empty")
                await pane.mount(placeholder)
                if pad_to is not None:
                    placeholder.styles.height = OVERVIEW_ROW_HEIGHT
                occupied = 1
        else:
            for node in nodes:
                row = MessageRow(
                    node, truncate=truncate, classes="changed" if changed else ""
                )
                await pane.mount(row)
                if pad_to is not None:
                    # Override the per-role truncation max (system caps at 1) so
                    # every overview row is exactly one uniform slot tall.
                    row.styles.height = OVERVIEW_ROW_HEIGHT
                    row.styles.max_height = OVERVIEW_ROW_HEIGHT
                rows.append(row)
            occupied = len(nodes)
        if pad_to is not None:
            for _ in range(pad_to - occupied):
                filler = Static("", classes="diff-filler")
                await pane.mount(filler)
                filler.styles.height = OVERVIEW_ROW_HEIGHT
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
            slots = region_slot_count(region)
            left_rows = await self._mount_side(
                left_pane, region.left, changed=region.changed, pad_to=slots
            )
            right_rows = await self._mount_side(
                right_pane, region.right, changed=region.changed, pad_to=slots
            )
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
