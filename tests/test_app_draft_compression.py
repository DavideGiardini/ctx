"""Pilot tests for AI-drafted compression (PRD Sprint 3, Task 9; Q4/Q10b).

``Ctrl+D`` in the draft editor streams ``core.draft_compression`` into the Bottom
split. It is a meta-operation, never a gauge anchor (Q10b), re-drafting overwrites
(Q4), and the prompt of the last draft is stamped onto the K a later ``Ctrl+S``
commits. The oracle is the Task 9 acceptance criterion, asserted through the
public ``describe_state()`` / editor state and ``app.core`` (for K's meta).
"""

from textual.widgets import TextArea

from ctx.core.provider import TestProvider as CannedProvider
from ctx.core.provider import Usage
from ctx.ui.app import ChatApp
from ctx.ui.widgets.input_bar import InputBar

# Provider that also reports a plausible usage: a normal turn would anchor the
# gauge, so a draft that (wrongly) anchored would be caught by the Q10b assert.
_DRAFT_TOKENS = ["draft ", "summary"]
_DRAFT_TEXT = "draft summary"


def _app(repo, workspace) -> ChatApp:
    return ChatApp(
        provider=CannedProvider(_DRAFT_TOKENS, usage=Usage(12, 5, 17)),
        workspace=workspace,
        storage=repo,
    )


async def _two_turns(app) -> None:
    await app.on_input_bar_submitted(InputBar.Submitted("first"))
    await app.workers.wait_for_complete()
    await app.on_input_bar_submitted(InputBar.Submitted("second"))
    await app.workers.wait_for_complete()


async def _open_editor_on_full_range(pilot) -> None:
    """Enter Edit, select the whole (4-node) view ending at the tip, open editor."""
    await pilot.press("escape")  # → Edit mode
    await pilot.press("home")  # cursor on the first node
    await pilot.press("v", "down", "down", "down")  # range = all 4 nodes (ends at tip)
    await pilot.press("c")  # open the draft editor


async def test_ctrl_d_streams_draft_into_bottom_without_anchoring(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _two_turns(app)
        await _open_editor_on_full_range(pilot)

        gen_before = app.core.usage_generation
        cal_before = app.core.calibration

        await pilot.press("ctrl+d")
        await app.workers.wait_for_complete()

        # The canned tokens land in the Bottom split, not the prompt split.
        assert app.query_one("#compress-output", TextArea).text == _DRAFT_TEXT
        assert app.describe_state()["compression_editor"]["output"] == _DRAFT_TEXT
        # A draft is a meta-operation: it never anchors the header gauge (Q10b).
        assert app.core.usage_generation == gen_before
        assert app.core.calibration == cal_before


async def test_redraft_overwrites_bottom(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _two_turns(app)
        await _open_editor_on_full_range(pilot)

        await pilot.press("ctrl+d")
        await app.workers.wait_for_complete()
        # Simulate stale/hand-edited output plus an edited prompt before re-draft.
        app.query_one("#compress-output", TextArea).text = "STALE HAND EDIT"
        app.query_one("#compress-prompt", TextArea).text = "focus on the decisions"

        await pilot.press("ctrl+d")
        await app.workers.wait_for_complete()

        # Re-draft clears first: the Bottom holds only the fresh draft, not the
        # stale text and not a doubled concatenation.
        assert app.query_one("#compress-output", TextArea).text == _DRAFT_TEXT


async def test_ctrl_s_after_draft_stamps_drafted_prompt_on_k(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _two_turns(app)
        await _open_editor_on_full_range(pilot)

        app.query_one("#compress-prompt", TextArea).text = "MY CUSTOM PROMPT"
        await pilot.press("ctrl+d")
        await app.workers.wait_for_complete()
        await pilot.press("ctrl+s")

        k = app.core.nodes[-1]
        assert k.node_type == "compression"
        # Summary = the drafted output; prompt = the Top text at draft time (not "").
        assert k.content == _DRAFT_TEXT
        assert k.meta["prompt"] == "MY CUSTOM PROMPT"


async def test_ctrl_d_inert_when_editor_closed(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _two_turns(app)
        await pilot.press("escape")  # Edit mode, editor NOT open

        await pilot.press("ctrl+d")
        await app.workers.wait_for_complete()

        # No editor → no draft ran; nothing was compressed or drafted.
        assert app.describe_state()["compression_editor"]["open"] is False
        assert not any(
            n["node_type"] == "compression" for n in app.describe_state()["nodes"]
        )
