"""Pilot tests for vim-style range selection (PRD Sprint 3, Task 6; ADR-0016 Q5).

In Edit mode ``v`` anchors a contiguous range at the cursor; Up/Down extend it;
``Esc`` clears the anchor but stays in Edit; entering Insert clears it. The
oracle is the Task 6 acceptance criterion, asserted through the public
``describe_state()`` snapshot (``range_selection`` = node *indices* into the
reported ``nodes`` array, in view order — 13i) and the ``.range-selected`` CSS
class the qa-tester harness can query.
"""

from ctx.ui.widgets.input_bar import InputBar
from ctx.ui.widgets.message_list import MessageWidget


async def test_v_then_down_down_selects_three_contiguous_ids(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        # Two turns → four nodes [u1, a1, u2, a2].
        await app.on_input_bar_submitted(InputBar.Submitted("first"))
        await app.workers.wait_for_complete()
        await app.on_input_bar_submitted(InputBar.Submitted("second"))
        await app.workers.wait_for_complete()

        view_ids = [n.id for n in app.core.nodes]
        assert len(view_ids) == 4

        await pilot.press("escape")  # → Edit mode (cursor on last node)
        await pilot.press("home")  # → cursor on the first node
        await pilot.press("v", "down", "down")

        state = app.describe_state()
        assert state["mode"] == "edit"
        # Three contiguous indices, in view order, starting at the anchor.
        assert state["range_selection"] == [0, 1, 2]

        # The widgets in the range carry .range-selected; the one outside does not.
        message_list = app.query_one("#messages")
        for node_id in view_ids[0:3]:
            widget = message_list.query_one(f"#msg-{node_id}", MessageWidget)
            assert widget.has_class("range-selected")
        outside = message_list.query_one(f"#msg-{view_ids[3]}", MessageWidget)
        assert not outside.has_class("range-selected")


async def test_range_selection_uses_hover_style_and_bridges_gaps(app_factory):
    """Task 41: a selected run wears the grey hover background (not solid blue)
    with a bold (``thick``) role-colored left bar, and bridges the inter-row gaps
    so it reads as one contiguous block — the interior rows carry the
    ``range-continues-*`` classes, the run's edges do not."""
    app = app_factory()
    async with app.run_test() as pilot:
        await app.on_input_bar_submitted(InputBar.Submitted("first"))
        await app.workers.wait_for_complete()
        await app.on_input_bar_submitted(InputBar.Submitted("second"))
        await app.workers.wait_for_complete()

        view_ids = [n.id for n in app.core.nodes]
        assert len(view_ids) == 4

        await pilot.press("escape")
        await pilot.press("home")
        await pilot.press("v", "down", "down")  # select rows 0,1,2

        message_list = app.query_one("#messages")
        top = message_list.query_one(f"#msg-{view_ids[0]}", MessageWidget)
        mid = message_list.query_one(f"#msg-{view_ids[1]}", MessageWidget)
        bottom = message_list.query_one(f"#msg-{view_ids[2]}", MessageWidget)
        outside = message_list.query_one(f"#msg-{view_ids[3]}", MessageWidget)

        # Hover-style bar: every selected row gets the bold `thick` left border —
        # on the inner body wrapper, not the outer row (task 49).
        for widget in (top, mid, bottom):
            assert widget._row_body().styles.border_left[0] == "thick"

        # Gap bridging: interior boundaries carry the continues-* classes; the
        # run's outer edges do not, so it detaches from the surrounding turns.
        assert top.has_class("range-continues-below")
        assert not top.has_class("range-continues-above")
        assert mid.has_class("range-continues-above")
        assert mid.has_class("range-continues-below")
        assert bottom.has_class("range-continues-above")
        assert not bottom.has_class("range-continues-below")

        # The row outside the range carries no selection styling at all.
        assert not outside.has_class("range-selected")
        assert not outside.has_class("range-continues-above")
        assert not outside.has_class("range-continues-below")
        assert outside._row_body().styles.border_left[0] == "tall"


async def test_esc_clears_range_and_stays_in_edit(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await app.on_input_bar_submitted(InputBar.Submitted("first"))
        await app.workers.wait_for_complete()

        await pilot.press("escape")  # → Edit mode
        await pilot.press("v", "down")
        assert len(app.describe_state()["range_selection"]) >= 1

        await pilot.press("escape")  # clears the range, stays in Edit
        state = app.describe_state()
        assert state["mode"] == "edit"
        assert state["range_selection"] == []
        for widget in app.query_one("#messages").query(MessageWidget):
            assert not widget.has_class("range-selected")


async def test_v_alone_is_range_of_one(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await app.on_input_bar_submitted(InputBar.Submitted("only turn"))
        await app.workers.wait_for_complete()

        await pilot.press("escape")  # → Edit mode, cursor on the last node
        await pilot.press("v")

        state = app.describe_state()
        assert len(state["range_selection"]) == 1
        assert state["range_selection"] == [state["selected_index"]]


async def test_down_at_bottom_edge_does_not_wrap(app_factory):
    """Task 13e: extending down from the last node clamps — it must not wrap to
    index 0 and swallow the whole conversation."""
    app = app_factory()
    async with app.run_test() as pilot:
        await app.on_input_bar_submitted(InputBar.Submitted("first"))
        await app.workers.wait_for_complete()
        await app.on_input_bar_submitted(InputBar.Submitted("second"))
        await app.workers.wait_for_complete()

        view_ids = [n.id for n in app.core.nodes]
        assert len(view_ids) == 4

        await pilot.press("escape")  # → Edit mode, cursor parked on the last node
        await pilot.press("v", "down")  # anchor at tip, try to extend past the edge

        # Clamped: the range stays a range-of-one at the tip, not the whole list.
        assert app.describe_state()["range_selection"] == [len(view_ids) - 1]


async def test_up_at_top_edge_does_not_wrap(app_factory):
    """Task 13e: extending up from the first node clamps at index 0."""
    app = app_factory()
    async with app.run_test() as pilot:
        await app.on_input_bar_submitted(InputBar.Submitted("first"))
        await app.workers.wait_for_complete()
        await app.on_input_bar_submitted(InputBar.Submitted("second"))
        await app.workers.wait_for_complete()

        await pilot.press("escape")
        await pilot.press("home")  # cursor on the first node
        await pilot.press("v", "up")  # anchor at first, try to extend past the top

        assert app.describe_state()["range_selection"] == [0]


async def test_in_bounds_extension_unchanged(app_factory):
    """Normal in-bounds extension is unaffected by the clamp."""
    app = app_factory()
    async with app.run_test() as pilot:
        await app.on_input_bar_submitted(InputBar.Submitted("first"))
        await app.workers.wait_for_complete()
        await app.on_input_bar_submitted(InputBar.Submitted("second"))
        await app.workers.wait_for_complete()

        await pilot.press("escape")
        await pilot.press("home")
        await pilot.press("v", "down", "down")

        assert app.describe_state()["range_selection"] == [0, 1, 2]
