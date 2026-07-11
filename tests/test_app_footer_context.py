"""The Edit-mode footer surfaces only the selection-valid action (task 43c).

``x Expand`` is a valid key only on a compression ``K``; the footer hint must
advertise it precisely when a K is selected and drop it otherwise, so the hint
tracks the selected node type. The oracle is the public ``describe_state()``
``"footer"`` line (the same string ``AppFooter.current_hint`` renders).
"""

from textual.widgets import TextArea

from ctx.ui.widgets.app_footer import _HINTS
from ctx.ui.widgets.input_bar import InputBar


async def _two_turns(app) -> None:
    await app.on_input_bar_submitted(InputBar.Submitted("first"))
    await app.workers.wait_for_complete()
    await app.on_input_bar_submitted(InputBar.Submitted("second"))
    await app.workers.wait_for_complete()


async def test_footer_advertises_expand_only_on_a_compression_node(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await _two_turns(app)

        # A plain turn is selected: the base Edit hint, no expand action.
        await pilot.press("escape")  # → Edit, cursor on the last (assistant) node
        assert app._get_selected_node().node_type != "compression"
        assert app.describe_state()["footer"] == _HINTS["edit"]
        assert "x Expand" not in app.describe_state()["footer"]

        # Fold the whole range into one K, then select it: the hint gains Expand.
        await pilot.press("home")
        await pilot.press("v", "down", "down", "down")
        await pilot.press("c")
        app.query_one("#compress-output", TextArea).text = "SUMMARY"
        await pilot.press("ctrl+s")  # commit → Edit mode, selection cleared
        await pilot.press("escape")  # → Insert
        await pilot.press("escape")  # → Edit, selects the tip (the K)

        assert app._get_selected_node().node_type == "compression"
        assert "x Expand" in app.describe_state()["footer"]
