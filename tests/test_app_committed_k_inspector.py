"""Pilot tests for the committed-K inspector 3-split (PRD Sprint 3, Task 10; Q4/Q8).

Selecting a compression node ``K`` in Edit mode shows the left inspector as a
3-split — Prompt (``K.meta["prompt"]``, hidden when empty), Originals (the folded
children, off-view and reached via ``core.folded_children``), and Summary
(``K.content``) — reusing the context view's split machinery so the ``1``/``2``/``3``
maximize shortcuts still work.

The oracle is the Task 10 acceptance, asserted through ``describe_state()`` and the
inspector's ``NodeView``/``splits_visible`` (the split *contents* are an inspector
detail describe_state omits).
"""

from pilot_helpers import two_turns
from textual.widgets import TextArea

from ctx.core.conversation import DEFAULT_COMPRESSION_PROMPT
from ctx.ui.widgets.detail_inspector import DetailInspector


async def _open_editor_on_full_range(pilot) -> None:
    await pilot.press("escape")  # → Edit mode
    await pilot.press("home")  # cursor on the first node
    await pilot.press("v", "down", "down", "down")  # range = all 4 nodes (ends at tip)
    await pilot.press("c")  # open the draft editor


async def test_drafted_k_inspector_shows_prompt_originals_summary(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)
        await _open_editor_on_full_range(pilot)

        # Draft (Ctrl+D) so the committed K carries a non-empty prompt.
        await pilot.press("ctrl+d")
        await app.workers.wait_for_complete()
        await pilot.press("ctrl+s")  # commit; summary = drafted tokens

        await pilot.press("home")  # select the (only) node — the K
        await pilot.pause()

        view = app.query_one(DetailInspector).node_state
        assert view is not None
        assert view.node_type == "compression"
        # Prompt = the drafting instruction; Originals = the folded children's
        # content; Summary = K's own content.
        assert view.prompt == DEFAULT_COMPRESSION_PROMPT
        assert "first" in view.content and "second" in view.content
        assert view.output == "ok"

        state = app.describe_state()
        assert state["detail"]["view"] == "context"
        assert app.query_one(DetailInspector).splits_visible() == [
            "prompt",
            "content",
            "output",
        ]


async def test_manual_k_inspector_hides_empty_prompt_split(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)
        await _open_editor_on_full_range(pilot)

        app.query_one("#compress-output", TextArea).text = "MANUAL SUMMARY"
        await pilot.press("ctrl+s")  # manual commit → prompt == ""

        await pilot.press("home")  # select the K
        await pilot.pause()

        inspector = app.query_one(DetailInspector)
        view = inspector.node_state
        assert view is not None and view.prompt == ""
        assert view.output == "MANUAL SUMMARY"
        # Empty prompt hides the Top split; Originals + Summary remain.
        assert inspector.splits_visible() == ["content", "output"]


async def test_k_inspector_originals_split_renders_compact_rows(app_factory):
    """Task 38: the Originals (content) split renders the folded children as the
    shared compact MessageRows — not a plain markdown-bold text dump — and a
    visible divider sits between the three splits."""
    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)
        await _open_editor_on_full_range(pilot)

        app.query_one("#compress-output", TextArea).text = "SUMMARY"
        await pilot.press("ctrl+s")  # commit -> K folding all 4 nodes
        await pilot.press("home")  # select the K
        await pilot.pause()
        await pilot.pause()

        inspector = app.query_one(DetailInspector)
        # One compact row per folded child (user1, assistant1, user2, assistant2).
        rows = list(inspector.query("#detail-content-rows MessageRow"))
        assert len(rows) == 4
        # The plain-text content Static is hidden in favour of the rows.
        assert inspector.query_one("#detail-content-text").display is False
        # A visible divider (border) separates the splits.
        assert inspector.query_one("#detail-content").styles.border_bottom[0]


async def test_number_keys_maximize_k_splits(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)
        await _open_editor_on_full_range(pilot)

        app.query_one("#compress-output", TextArea).text = "SUMMARY"
        await pilot.press("ctrl+s")
        await pilot.press("home")  # select the K
        await pilot.pause()

        inspector = app.query_one(DetailInspector)
        await pilot.press("2")  # maximize Originals (content split)
        assert inspector.maximized_split() == "content"
        assert app.describe_state()["detail"]["maximized_split"] == "content"

        await pilot.press("3")  # switch to Summary (output split)
        assert inspector.maximized_split() == "output"
