"""Pilot tests for expand — the Edit-mode ``x`` key (PRD Sprint 3, Task 13b;
originally Task 11; ADR-0016 A#3/A#5).

``x`` on a selected compression node ``K`` restores its folded children in place
(the non-destructive inverse of a commit): the children come back on the line,
``K`` leaves the view, the selection lands on the first restored child, and the
restored view round-trips through storage. A later turn then sees the children
verbatim — no ``<conversation_summary>`` wrapper. ``x`` on any other node is a
**silent no-op** (task 43b): no hint, no graph mutation — the footer advertises
``x`` only when a K is selected, so a warning there would be noise.

Task 13b removed the dead ``/expand`` slash command: expand is a selection-
dependent action, and a slash command can never carry a selection (entering
Insert to type it clears the selection). These tests therefore drive the real
``x`` key with ``pilot.press`` — deliberately NOT the old
``on_input_bar_submitted("/expand")`` back-door, which was the convention that
masked the CP4 defect.

The oracle is the acceptance criterion, asserted through the public
``describe_state()`` snapshot, ``app.core`` (for the graph), and a recording
provider (for the next turn's context).
"""

from conftest import RecordingProvider
from pilot_helpers import compress_range, select_tip_in_edit, two_turns

from ctx.ui.widgets.input_bar import InputBar


async def test_expand_restores_children_and_removes_k(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)
        await compress_range(app, pilot, "SUMMARY")
        assert sum(
            1 for n in app.describe_state()["nodes"] if n["node_type"] == "compression"
        ) == 1

        # Re-enter Edit (selects the tip = K), then expand it with the key.
        await select_tip_in_edit(app, pilot)
        assert app._get_selected_node().node_type == "compression"
        await pilot.press("x")

        state = app.describe_state()
        # The four children are back and no K survives in the view.
        assert not any(n["node_type"] == "compression" for n in state["nodes"])
        assert len(state["nodes"]) == 4
        # Selection moved to the first restored child.
        assert state["nodes"][0]["selected"] is True


async def test_expand_survives_restart(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)
        conv_id = app.core.conversation_id
        await compress_range(app, pilot, "SUMMARY")
        await select_tip_in_edit(app, pilot)
        await pilot.press("x")
        assert not any(
            n["node_type"] == "compression" for n in app.describe_state()["nodes"]
        )

    # A second app on the same DB resolves the identical expanded view (the E
    # event + cleared pointers round-trip).
    app2 = app_factory()
    async with app2.run_test():
        app2.core.resume_conversation(conv_id)
        state = app2.describe_state()
        assert not any(n["node_type"] == "compression" for n in state["nodes"])
        assert len(state["nodes"]) == 4


async def test_next_turn_sees_children_verbatim_after_expand(app_factory):
    provider = RecordingProvider(["reply"])
    app = app_factory(provider=provider)
    async with app.run_test() as pilot:
        await two_turns(app)
        await compress_range(app, pilot, "THE SUMMARY TEXT")
        await select_tip_in_edit(app, pilot)
        await pilot.press("x")

        # Next turn: the recording provider must receive the children verbatim
        # and no compression summary wrapper.
        await app.on_input_bar_submitted(InputBar.Submitted("third"))
        await app.workers.wait_for_complete()

        blob = "\n".join(str(m.get("content", "")) for m in provider.captured)
        assert "<conversation_summary>" not in blob
        assert "THE SUMMARY TEXT" not in blob
        # The original turns' text is present again.
        assert "first" in blob
        assert "second" in blob


async def test_expand_on_non_compression_is_a_silent_no_op(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)
        await pilot.press("escape")  # Edit mode, cursor on the last (assistant) node
        assert app._get_selected_node().node_type != "compression"

        before = len(app.describe_state()["nodes"])
        await pilot.press("x")

        state = app.describe_state()
        # Silent no-op (task 43b): no hint, no graph mutation.
        assert state["last_hint"] is None
        assert len(state["nodes"]) == before
