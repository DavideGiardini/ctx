"""Pilot tests for compression commit (PRD Sprint 3, Task 8; Q3/Q9).

``Ctrl+S`` in the draft editor with a non-empty summary folds the selected
range into a single compression node ``K``: the children leave the view, one K
widget replaces them (numeric ``weight_pct``, ``meta["prompt"] == ""`` for a
manual commit), and the resolved view round-trips through storage. An empty
summary shows a transient hint instead of committing (task 42).

The oracle is the Task 8 acceptance criterion, asserted through the public
``describe_state()`` snapshot and ``app.core`` (for K's meta, an implementation
detail describe_state deliberately omits).
"""

from pilot_helpers import open_editor_on_range, two_turns
from textual.widgets import TextArea

from ctx.ui.widgets.compression_editor import CompressionEditor
from ctx.ui.widgets.detail_inspector import DetailInspector
from ctx.ui.widgets.message_list import MessageList, MessageWidget, Separator


async def test_ctrl_s_commits_folds_range_to_single_k(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)
        await open_editor_on_range(pilot)

        app.query_one("#compress-output", TextArea).text = "SUMMARY OF THE FIRST TWO TURNS"
        await pilot.press("ctrl+s")

        state = app.describe_state()
        comp = [n for n in state["nodes"] if n["node_type"] == "compression"]
        # The four children folded into exactly one K; nothing else survives.
        assert len(state["nodes"]) == 1
        assert len(comp) == 1
        assert comp[0]["content"] == "SUMMARY OF THE FIRST TWO TURNS"
        # K goes to the model → it carries a numeric weight (Q9), not "--%".
        assert isinstance(comp[0]["weight_pct"], int)

        # A K widget actually rendered in the list with the compression role.
        assert app.query_one(CompressionEditor).display is False
        assert app.query_one(DetailInspector).display is True

        # Manual commit → empty prompt; range records the four folded child ids.
        k = app.core.nodes[-1]
        assert k.node_type == "compression"
        assert k.meta["prompt"] == ""
        assert len(k.meta["range"]) == 4


async def test_tab_reaches_summary_split_for_keyboard_only_commit(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)
        await open_editor_on_range(pilot)

        # On open the prompt split is focused; Tab must reach the summary split
        # (the app routes Tab into the editor while it owns the left pane) so a
        # real user can type the summary without a mouse.
        await pilot.press("tab")
        assert app.query_one("#compress-output", TextArea).has_focus
        await pilot.press("t", "e", "s", "t")
        await pilot.press("ctrl+s")

        state = app.describe_state()
        comp = [n for n in state["nodes"] if n["node_type"] == "compression"]
        assert len(comp) == 1
        assert comp[0]["content"] == "test"


async def test_ctrl_s_empty_summary_breadcrumbs_no_commit(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)
        await open_editor_on_range(pilot)

        # Leave the summary empty.
        await pilot.press("ctrl+s")

        state = app.describe_state()
        assert not any(n["node_type"] == "compression" for n in state["nodes"])
        # No commit → editor stays open so the user can keep drafting.
        assert state["compression_editor"]["open"] is True
        # A transient hint explains why nothing happened — not a graph node (task 42).
        assert state["last_hint"] is not None
        assert "summary" in state["last_hint"].lower()


async def test_ctrl_s_inert_when_editor_closed(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)
        await pilot.press("escape")  # Edit mode, editor NOT open

        await pilot.press("ctrl+s")  # must be a no-op

        state = app.describe_state()
        assert not any(n["node_type"] == "compression" for n in state["nodes"])
        assert state["compression_editor"]["open"] is False


async def test_committed_k_after_assistant_carries_pass_start_margin(app_factory):
    # Compress only the *last two* nodes (user2 + assistant2) so the K lands
    # right after assistant1 in the view. Both are on the assistant side, so
    # without the task-40 fix the K would hug the reply above it with no gap.
    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)  # view = [user1, assistant1, user2, assistant2]
        await pilot.press("escape")  # → Edit mode
        await pilot.press("home")  # cursor on user1
        await pilot.press("down", "down")  # cursor on user2 (index 2)
        await pilot.press("v", "down")  # range = [user2, assistant2] (ends at tip)
        await pilot.press("c")  # open the draft editor

        app.query_one("#compress-output", TextArea).text = "SUMMARY"
        await pilot.press("ctrl+s")

        k_widgets = [w for w in app.query(MessageWidget) if w._role == "compression"]
        assert len(k_widgets) == 1
        # The K begins its own pass, so the list places a blank-line Separator
        # immediately above it (task 40) — it never hugs the assistant reply above.
        children = list(app.query_one(MessageList).children)
        k_index = children.index(k_widgets[0])
        assert k_index > 0 and isinstance(children[k_index - 1], Separator)


async def test_committed_k_round_trips_across_app_instances(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)
        conv_id = app.core.conversation_id
        await open_editor_on_range(pilot)

        app.query_one("#compress-output", TextArea).text = "ROUND TRIP SUMMARY"
        await pilot.press("ctrl+s")
        assert sum(
            1 for n in app.describe_state()["nodes"] if n["node_type"] == "compression"
        ) == 1

    # A second app on the same DB resolves the identical folded view.
    app2 = app_factory()
    async with app2.run_test():
        app2.core.resume_conversation(conv_id)
        state = app2.describe_state()
        comp = [n for n in state["nodes"] if n["node_type"] == "compression"]
        assert len(state["nodes"]) == 1
        assert len(comp) == 1
        assert comp[0]["content"] == "ROUND TRIP SUMMARY"
