"""Pilot tests for leaving the Detail Inspector's split navigation.

Two invariants live here, both about what the left pane *looks* like and where
focus lands — the kind of thing qa-tester can't see:

1. Only Browse paints a split with the selection tint. A maximized split holds
   keyboard focus (it has to, to take the scroll keys) but must not be tinted:
   it fills the pane, so tinting it reads as "the whole left pane is selected".
2. Esc leaves the pane in one step — from Browse or from a maximized split — and
   lands on the conversation in Edit mode with the same node still selected.
"""

from pilot_helpers import compress_range, inspector_settled, select_tip_in_edit, two_turns

from ctx.ui.widgets.detail_inspector import DetailInspector, _Split
from ctx.ui.widgets.message_list import MessageList


def _tinted_splits(inspector: DetailInspector) -> list[str | None]:
    """Split ids whose computed background is the selection tint. Reads the
    *computed* style (not the class) so a stray pseudo-class rule — e.g. a
    ``_Split:focus`` background — is caught too."""
    tint = inspector.app.get_css_variables()["ctx-selection"]
    return [
        split.id
        for split in inspector.query(_Split)
        if split.display and split.styles.background.hex.lower() == tint.lower()
    ]


async def _k_selected(app, pilot) -> DetailInspector:
    """Fold the conversation into one K and select it in Edit mode, so the
    inspector shows the 3-split view."""
    await two_turns(app)
    await compress_range(app, pilot, "SUMMARY")
    await select_tip_in_edit(app, pilot)
    await inspector_settled(pilot)
    inspector: DetailInspector = app.query_one(DetailInspector)
    return inspector


async def test_maximized_split_does_not_tint_the_pane(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        inspector = await _k_selected(app, pilot)

        await pilot.press("tab")  # enter the pane → Browse
        assert inspector.pane_mode == "browse"
        assert _tinted_splits(inspector) == ["detail-content"]  # topmost visible

        await pilot.press("2")  # maximize Originals
        assert inspector.maximized_split() == "content"
        assert _tinted_splits(inspector) == []


async def test_escape_from_maximized_returns_to_the_conversation(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        inspector = await _k_selected(app, pilot)
        selected = app.describe_state()["selected_index"]

        await pilot.press("2")  # maximize a split straight from Edit
        assert inspector.pane_mode == "maximized"

        await pilot.press("escape")
        # One step out: no intermediate Browse, nothing left tinted, still Edit
        # mode on the same node.
        assert inspector.pane_mode == "none"
        assert _tinted_splits(inspector) == []
        assert app.mode == "edit"
        assert app.focused is app.query_one(MessageList)
        assert app.describe_state()["selected_index"] == selected


async def test_escape_from_browse_returns_to_the_conversation(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        inspector = await _k_selected(app, pilot)

        await pilot.press("tab")  # enter the pane → Browse
        await pilot.press("escape")

        assert inspector.pane_mode == "none"
        assert _tinted_splits(inspector) == []
        assert app.mode == "edit"
        assert app.focused is app.query_one(MessageList)
