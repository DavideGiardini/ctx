"""Pilot tests for deep-dive/editor interaction hardening (PRD Sprint 3, Task 13h).

Three related state bugs around the deep-dive view and the commit path:

1. A range anchor set *before* diving must be cleared on dive entry — dive widgets
   never render the range highlight, so a lingering anchor would silently swallow
   the first Esc instead of popping the dive.
2. Async node-appenders (breadcrumbs, the connectivity worker, the submit path)
   must not mount widgets into the read-only dive frame: they append to the core
   but the widget mount is gated on the dive stack, so the node surfaces only when
   the live view returns.
3. Committing a K must reset the DetailInspector to its placeholder — the node it
   was showing has just been folded away.

The oracle is the Task 13h acceptance criteria, asserted through ``describe_state()``
and the rendered widget count.
"""

from pilot_helpers import two_turns
from textual.widgets import TextArea

from ctx.ui.widgets.message_list import MessageWidget


async def _compress_full_tip_range(app, pilot, summary: str) -> None:
    await pilot.press("escape")  # → Edit mode
    await pilot.press("home")  # cursor on the first node
    await pilot.press("v", "down", "down", "down")  # range = all 4 nodes
    await pilot.press("c")  # open the draft editor
    app.query_one("#compress-output", TextArea).text = summary
    await pilot.press("ctrl+s")  # commit → one K in the view


async def _select_k_in_edit(app, pilot) -> None:
    if app.mode == "edit":
        await pilot.press("escape")  # → Insert
    await pilot.press("escape")  # → Edit, selects the tip (K)


async def test_single_esc_pops_dive_when_anchored_before_diving(app_factory):
    """(a) `v` on a K then `g d`: the pre-dive anchor is cleared on entry, so a
    SINGLE Esc pops the dive rather than being eaten by a stale range clear."""
    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)
        await _compress_full_tip_range(app, pilot, "SUMMARY")
        await _select_k_in_edit(app, pilot)
        assert app._get_selected_node().node_type == "compression"

        await pilot.press("v")  # anchor a range on the K BEFORE diving
        await pilot.press("g", "d")
        await pilot.pause()

        state = app.describe_state()
        assert state["deep_dive"]["active"] is True
        assert state["range_selection"] == []  # anchor cleared on dive entry

        await pilot.press("escape")  # a SINGLE Esc must pop the dive
        await pilot.pause()

        state = app.describe_state()
        assert state["deep_dive"]["active"] is False
        assert state["mode"] == "edit"  # popped the dive, did not toggle mode


async def test_connectivity_node_gated_out_of_dive_then_surfaces(app_factory):
    """(b) A connectivity worker completing mid-dive must not mount into the dive
    frame; exiting the dive surfaces it in the live view."""
    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)
        await _compress_full_tip_range(app, pilot, "SUMMARY")
        await _select_k_in_edit(app, pilot)
        await pilot.press("g", "d")
        await pilot.pause()

        count_before = len(app.query(MessageWidget))
        app._check_connectivity("some/model")
        await app.workers.wait_for_complete()
        await pilot.pause()

        # Dive frame unchanged: the connectivity node did not mount here.
        assert len(app.query(MessageWidget)) == count_before
        assert app.describe_state()["deep_dive"]["active"] is True

        await pilot.press("ctrl+o")  # exit the dive → live view rebuilds
        await pilot.pause()
        contents = [n["content"] for n in app.describe_state()["nodes"]]
        assert any("Connected to some/model" in c for c in contents)


async def test_model_command_gated_out_of_dive_then_surfaces(app_factory):
    """(b, task 31) `/model x` issued mid-dive must not mount its reply widget into
    the read-only dive frame; exiting the dive surfaces the switch breadcrumb in the
    live view. Completes 13h#2 — the command handler appended directly, bypassing the
    dive gate."""
    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)
        await _compress_full_tip_range(app, pilot, "SUMMARY")
        await _select_k_in_edit(app, pilot)
        await pilot.press("g", "d")
        await pilot.pause()
        assert app.describe_state()["deep_dive"]["active"] is True

        count_before = len(app.query(MessageWidget))
        await app._handle_model_command("/model gpt-test")
        await app.workers.wait_for_complete()  # drain the connectivity worker too
        await pilot.pause()

        # Dive frame unchanged: neither the switch node nor the connectivity node
        # mounted here.
        assert len(app.query(MessageWidget)) == count_before
        assert app.describe_state()["deep_dive"]["active"] is True

        await pilot.press("ctrl+o")  # exit the dive → live view rebuilds
        await pilot.pause()
        contents = [n["content"] for n in app.describe_state()["nodes"]]
        assert any("Model set to: gpt-test" in c for c in contents)


async def test_commit_resets_inspector_to_placeholder(app_factory):
    """(c) After Ctrl+S the inspector shows the empty/placeholder state, not the
    node that was just folded away."""
    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)
        await _compress_full_tip_range(app, pilot, "SUMMARY")
        await pilot.pause()

        state = app.describe_state()
        assert state["detail"]["view"] == "empty"
        assert state["detail"]["node_index"] is None
        assert state["range_selection"] == []
