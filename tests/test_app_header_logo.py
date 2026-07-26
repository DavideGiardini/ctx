"""The CTX logo sits on the pane seam at every terminal width.

A layout invariant, so it belongs here rather than with qa-tester (which cannot
see computed columns). Asserted against the *rendered* row and the seam's real
region: re-deriving the centering arithmetic would only restate the code, and it
was exactly a stale derivation — the header assuming where the divider fell —
that knocked the logo off in the first place.
"""

import pytest
from textual.geometry import Region
from textual.widgets import Static

from ctx.ui.app import ChatApp
from ctx.ui.widgets.pane_seam import PaneSeam


def logo_column(app: ChatApp) -> int:
    """The screen column of the logo's middle glyph."""
    logo = app.query_one("#hdr-logo", Static)
    rendered: str = logo.render_lines(Region(0, 0, logo.size.width, 1))[0].text
    return logo.region.x + rendered.index("CTX") + 1


@pytest.mark.parametrize("width", [40, 41, 60, 61, 80, 81, 120, 121])
async def test_logo_sits_on_the_seam(app_factory, width):
    app = app_factory()
    async with app.run_test(size=(width, 12)) as pilot:
        await pilot.pause()
        await pilot.pause()
        assert logo_column(app) == app.query_one(PaneSeam).region.x


async def test_logo_follows_the_seam_across_a_resize(app_factory):
    app = app_factory()
    async with app.run_test(size=(80, 12)) as pilot:
        await pilot.pause()
        await pilot.pause()
        before = logo_column(app)

        await pilot.resize_terminal(101, 12)
        await pilot.pause()
        await pilot.pause()

        assert logo_column(app) != before
        assert logo_column(app) == app.query_one(PaneSeam).region.x
