"""Pilot tests for draft-prompt reset on cancel/failure (PRD Sprint 3e, Task 35).

``action_draft_compression`` records ``self._last_drafted_prompt`` *before* the
draft worker runs, so a later ``Ctrl+S`` can stamp it on the committed K
(distinguishing an AI-drafted K from a hand-written one, Q4). But a draft that
is **cancelled** (Esc) or **fails** must not leave that prompt lingering: a user
who then hand-writes a summary and commits would otherwise stamp the stale
prompt on the K, making a manual commit masquerade as AI-drafted.

Contract: after a cancelled or failed draft, a subsequent manual commit stamps
``K.meta["prompt"] == ""``. The oracle is the Task 35 acceptance criterion,
asserted through ``app.core`` (K's meta) and the public editor state.
"""

import asyncio

from conftest import BlockingProvider, ErroringProvider
from textual.widgets import TextArea

from ctx.ui.widgets.input_bar import InputBar


async def _two_turns(app) -> None:
    await app.on_input_bar_submitted(InputBar.Submitted("first"))
    await app.workers.wait_for_complete()
    await app.on_input_bar_submitted(InputBar.Submitted("second"))
    await app.workers.wait_for_complete()


async def _open_editor_on_full_range(pilot) -> None:
    await pilot.press("escape")  # → Edit mode
    await pilot.press("home")  # cursor on the first node
    await pilot.press("v", "down", "down", "down")  # range = all 4 nodes (ends at tip)
    await pilot.press("c")  # open the draft editor


def _last_k(app):
    k = app.core.nodes[-1]
    assert k.node_type == "compression"
    return k


async def test_manual_commit_after_cancelled_draft_stamps_empty_prompt(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await _two_turns(app)
        await _open_editor_on_full_range(pilot)

        # Draft with a custom prompt, then cancel the live worker via Esc.
        app.query_one("#compress-prompt", TextArea).text = "focus on the decisions"
        gate = asyncio.Event()
        app.core._provider = BlockingProvider(["partial"], gate)
        await pilot.press("ctrl+d")
        for _ in range(200):
            if app._draft_worker is not None and not app._draft_worker.is_finished:
                break
            await pilot.pause()
        worker = app._draft_worker
        assert worker is not None and not worker.is_finished

        await pilot.press("escape")  # cancels the worker, editor stays open
        for _ in range(200):
            if worker.is_finished:
                break
            await pilot.pause()
        assert worker.is_finished

        # Hand-write a summary and commit — this must be a MANUAL commit.
        app.query_one("#compress-output", TextArea).text = "hand written summary"
        await pilot.press("ctrl+s")

        k = _last_k(app)
        assert k.content == "hand written summary"
        assert k.meta["prompt"] == ""
        gate.set()
        await app.workers.wait_for_complete()


async def test_manual_commit_after_failed_draft_stamps_empty_prompt(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await _two_turns(app)
        await _open_editor_on_full_range(pilot)

        app.query_one("#compress-prompt", TextArea).text = "focus on the decisions"
        app.core._provider = ErroringProvider()
        await pilot.press("ctrl+d")
        await app.workers.wait_for_complete()

        # The draft failed; a subsequent hand-written commit is manual.
        app.query_one("#compress-output", TextArea).text = "hand written summary"
        await pilot.press("ctrl+s")

        k = _last_k(app)
        assert k.content == "hand written summary"
        assert k.meta["prompt"] == ""
