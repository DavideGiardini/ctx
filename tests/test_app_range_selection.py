"""Pilot tests for vim-style range selection (PRD Sprint 3, Task 6; ADR-0016 Q5).

In Edit mode ``v`` anchors a contiguous range at the cursor; Up/Down extend it;
``Esc`` clears the anchor but stays in Edit; entering Insert clears it. The
oracle is the Task 6 acceptance criterion, asserted through the public
``describe_state()`` snapshot (``range_selection`` = node ids in view order) and
the ``.range-selected`` CSS class the qa-tester harness can query.
"""

from ctx.core.provider import TestProvider as CannedProvider
from ctx.ui.app import ChatApp
from ctx.ui.widgets.input_bar import InputBar
from ctx.ui.widgets.message_list import MessageWidget


async def _four_node_app(repo, workspace) -> ChatApp:
    return ChatApp(
        provider=CannedProvider(["ok"]),
        workspace=workspace,
        storage=repo,
    )


async def test_v_then_down_down_selects_three_contiguous_ids(repo, workspace):
    app = await _four_node_app(repo, workspace)
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
        # Three contiguous ids, in view order, starting at the anchor.
        assert state["range_selection"] == view_ids[0:3]

        # The widgets in the range carry .range-selected; the one outside does not.
        message_list = app.query_one("#messages")
        for node_id in view_ids[0:3]:
            widget = message_list.query_one(f"#msg-{node_id}", MessageWidget)
            assert widget.has_class("range-selected")
        outside = message_list.query_one(f"#msg-{view_ids[3]}", MessageWidget)
        assert not outside.has_class("range-selected")


async def test_esc_clears_range_and_stays_in_edit(repo, workspace):
    app = await _four_node_app(repo, workspace)
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


async def test_v_alone_is_range_of_one(repo, workspace):
    app = await _four_node_app(repo, workspace)
    async with app.run_test() as pilot:
        await app.on_input_bar_submitted(InputBar.Submitted("only turn"))
        await app.workers.wait_for_complete()

        await pilot.press("escape")  # → Edit mode, cursor on the last node
        await pilot.press("v")

        state = app.describe_state()
        assert len(state["range_selection"]) == 1
        assert state["range_selection"] == [app.core.nodes[state["selected_index"]].id]


async def test_down_at_bottom_edge_does_not_wrap(repo, workspace):
    """Task 13e: extending down from the last node clamps — it must not wrap to
    index 0 and swallow the whole conversation."""
    app = await _four_node_app(repo, workspace)
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
        assert app.describe_state()["range_selection"] == [view_ids[-1]]


async def test_up_at_top_edge_does_not_wrap(repo, workspace):
    """Task 13e: extending up from the first node clamps at index 0."""
    app = await _four_node_app(repo, workspace)
    async with app.run_test() as pilot:
        await app.on_input_bar_submitted(InputBar.Submitted("first"))
        await app.workers.wait_for_complete()
        await app.on_input_bar_submitted(InputBar.Submitted("second"))
        await app.workers.wait_for_complete()

        view_ids = [n.id for n in app.core.nodes]

        await pilot.press("escape")
        await pilot.press("home")  # cursor on the first node
        await pilot.press("v", "up")  # anchor at first, try to extend past the top

        assert app.describe_state()["range_selection"] == [view_ids[0]]


async def test_in_bounds_extension_unchanged(repo, workspace):
    """Normal in-bounds extension is unaffected by the clamp."""
    app = await _four_node_app(repo, workspace)
    async with app.run_test() as pilot:
        await app.on_input_bar_submitted(InputBar.Submitted("first"))
        await app.workers.wait_for_complete()
        await app.on_input_bar_submitted(InputBar.Submitted("second"))
        await app.workers.wait_for_complete()

        view_ids = [n.id for n in app.core.nodes]

        await pilot.press("escape")
        await pilot.press("home")
        await pilot.press("v", "down", "down")

        assert app.describe_state()["range_selection"] == view_ids[0:3]
