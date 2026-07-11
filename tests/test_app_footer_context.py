"""The Edit-mode footer surfaces only the selection-valid action (task 43c).

``x Expand`` is a valid key only on a compression ``K``; the footer hint must
advertise it precisely when a K is selected and drop it otherwise, so the hint
tracks the selected node type. The oracle is the public ``describe_state()``
``"footer"`` line (the same string ``AppFooter.current_hint`` renders).
"""

from pilot_helpers import select_tip_in_edit, two_turns
from textual.widgets import TextArea

from ctx.ui.widgets.app_footer import _HINTS


async def test_footer_advertises_expand_only_on_a_compression_node(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)

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
        await select_tip_in_edit(app, pilot)

        assert app._get_selected_node().node_type == "compression"
        assert "x Expand" in app.describe_state()["footer"]
