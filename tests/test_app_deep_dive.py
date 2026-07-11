"""Pilot tests for the deep-dive browser (PRD Sprint 3, Task 12; ADR-0016 Q7/Q8/Q9).

A committed compression ``K`` can be *deep-dived*: ``g d`` in Edit mode replaces
the live message list with ``K``'s folded originals (full-view replacement, Q8),
adds a breadcrumb level ("Chat › K…"), and marks each child "not in context" (Q9).
The dive is read-only (``v``/``c`` are no-ops) and ephemeral. ``Ctrl+o``/``Esc``
pop one level; ``i`` exits the whole stack back to the live tip in Insert mode.

The oracle is the Task 12 acceptance criterion, asserted through the public
``describe_state()`` snapshot (which gains a ``"deep_dive"`` block) plus the rendered
weight widgets. The suite convention (a K must be *selected* in Edit mode) is set up
via the keyboard, then the chord is driven with real key presses.
"""

from textual.widgets import Static, TextArea

from ctx.core.provider import TestProvider as CannedProvider
from ctx.ui.app import ChatApp
from ctx.ui.widgets.input_bar import InputBar
from ctx.ui.widgets.message_list import MessageWidget


def _app(repo, workspace) -> ChatApp:
    return ChatApp(provider=CannedProvider(["ok"]), workspace=workspace, storage=repo)


async def _two_turns(app) -> None:
    await app.on_input_bar_submitted(InputBar.Submitted("first"))
    await app.workers.wait_for_complete()
    await app.on_input_bar_submitted(InputBar.Submitted("second"))
    await app.workers.wait_for_complete()


async def _compress_full_tip_range(app, pilot, summary: str) -> None:
    """Compress the whole (4-node) tip range into one K via the draft editor."""
    await pilot.press("escape")  # → Edit mode
    await pilot.press("home")  # cursor on the first node
    await pilot.press("v", "down", "down", "down")  # range = all 4 nodes (ends at tip)
    await pilot.press("c")  # open the draft editor
    app.query_one("#compress-output", TextArea).text = summary
    await pilot.press("ctrl+s")  # commit → one K in the view (Edit mode, no selection)


async def _select_k_in_edit(app, pilot) -> None:
    """Land in Edit mode with the selection on the freshly folded K (the tip).

    A commit clears the selection, so bounce out to Insert and back: re-entering
    Edit re-selects the tip."""
    if app.mode == "edit":
        await pilot.press("escape")  # → Insert
    await pilot.press("escape")  # → Edit, selects the tip (K)


async def _enter_deep_dive(app, pilot) -> None:
    await _two_turns(app)
    await _compress_full_tip_range(app, pilot, "SUMMARY")
    await _select_k_in_edit(app, pilot)
    assert app._get_selected_node().node_type == "compression"
    await pilot.press("g", "d")
    await pilot.pause()


async def test_gd_opens_deep_dive_with_children_and_breadcrumb(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _enter_deep_dive(app, pilot)

        state = app.describe_state()
        assert state["deep_dive"]["active"] is True
        # Breadcrumb has the root plus one dived level (3a depth is 1).
        assert len(state["deep_dive"]["breadcrumb"]) == 2
        assert state["deep_dive"]["breadcrumb"][0] == "Chat"
        # The four folded originals are the visible nodes (no K in the view).
        assert len(state["nodes"]) == 4
        assert not any(n["node_type"] == "compression" for n in state["nodes"])
        # Cursor landed on the first child.
        assert state["nodes"][0]["selected"] is True
        # Q9: each browsed original is off the live context → "not in context".
        for node in app._visible_nodes():
            weight = app.query_one(f"#msg-{node.id}", MessageWidget).query_one(
                ".weight", Static
            )
            assert "not in context" in str(weight.render())


async def test_ctrl_o_pops_back_to_live_view(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _enter_deep_dive(app, pilot)
        await pilot.press("ctrl+o")
        await pilot.pause()

        state = app.describe_state()
        assert state["deep_dive"]["active"] is False
        assert state["deep_dive"]["breadcrumb"] == ["Chat"]
        # Live view is back: the single K node.
        assert len(state["nodes"]) == 1
        assert state["nodes"][0]["node_type"] == "compression"


async def test_escape_pops_one_level(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _enter_deep_dive(app, pilot)
        # Esc backs out of the dive (does NOT toggle to Insert while diving).
        await pilot.press("escape")
        await pilot.pause()

        state = app.describe_state()
        assert state["deep_dive"]["active"] is False
        assert state["mode"] == "edit"
        assert len(state["nodes"]) == 1


async def test_i_exits_stack_to_insert(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _enter_deep_dive(app, pilot)
        await pilot.press("i")
        await pilot.pause()

        state = app.describe_state()
        assert state["deep_dive"]["active"] is False
        assert state["mode"] == "insert"
        assert state["focus"] == "input"
        # Live view restored (the K), not the browsed children.
        assert len(state["nodes"]) == 1
        assert state["nodes"][0]["node_type"] == "compression"


async def test_deep_dive_is_read_only(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _enter_deep_dive(app, pilot)
        # v (range anchor) and c (open editor) are inert while diving.
        await pilot.press("v")
        await pilot.pause()
        assert app.describe_state()["range_selection"] == []
        await pilot.press("c")
        await pilot.pause()
        state = app.describe_state()
        assert state["compression_editor"]["open"] is False
        assert state["deep_dive"]["active"] is True  # still diving, nothing mutated


async def test_gd_on_non_compression_does_nothing(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _two_turns(app)
        await pilot.press("escape")  # Edit mode, cursor on the last (assistant) node
        assert app._get_selected_node().node_type != "compression"

        await pilot.press("g", "d")
        await pilot.pause()

        state = app.describe_state()
        assert state["deep_dive"]["active"] is False
        # Live conversation untouched: the four turns are still the view.
        assert len(state["nodes"]) == 4
