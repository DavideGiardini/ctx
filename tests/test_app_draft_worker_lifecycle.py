"""Pilot tests for draft-worker lifecycle safety (PRD Sprint 3, Task 13d).

A live ``Ctrl+D`` draft worker must never be orphaned:

* ``Ctrl+S`` while a draft still streams must refuse (breadcrumb, no commit) —
  committing then would fold a half-streamed summary.
* Closing the editor (Esc, or a successful commit) must **cancel** the worker
  before dropping the reference, so it cannot keep streaming into the hidden
  TextArea and overwrite a re-opened editor's Summary with the old draft.

The oracle is the Task 13d acceptance criterion, asserted through the public
``describe_state()`` / editor state, ``app._draft_worker`` liveness, and
``app.workers``. A ``_BlockingProvider`` (yields a partial token, then blocks on
a gate) keeps the draft worker live while the test drives the UI.
"""

import asyncio

from conftest import BlockingProvider
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


async def _start_blocked_draft(app, pilot, gate) -> None:
    """Swap in the blocking provider, Ctrl+D, and wait until the draft is live
    with its partial token rendered (so the worker is genuinely mid-stream)."""
    app.core._provider = BlockingProvider(["partial"], gate)
    await pilot.press("ctrl+d")
    for _ in range(200):
        if (
            app._draft_worker is not None
            and not app._draft_worker.is_finished
            and app.query_one("#compress-output", TextArea).text == "partial"
        ):
            break
        await pilot.pause()
    assert app._draft_worker is not None and not app._draft_worker.is_finished


def _compression_nodes(app) -> list[dict]:
    return [n for n in app.describe_state()["nodes"] if n["node_type"] == "compression"]


def _hint_shown(app, needle: str) -> bool:
    # Refusals surface as transient hints, not graph nodes (task 42).
    hint = app.describe_state()["last_hint"]
    return hint is not None and needle in hint.lower()


async def test_commit_mid_draft_is_refused(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await _two_turns(app)
        await _open_editor_on_full_range(pilot)
        gate = asyncio.Event()
        await _start_blocked_draft(app, pilot, gate)

        await pilot.press("ctrl+s")

        # No K committed, a transient hint warns, and the editor is still open.
        assert _compression_nodes(app) == []
        assert app.describe_state()["compression_editor"]["open"] is True
        assert _hint_shown(app, "draft in progress")

        gate.set()
        await app.workers.wait_for_complete()


async def test_esc_cancels_a_live_draft(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await _two_turns(app)
        await _open_editor_on_full_range(pilot)
        gate = asyncio.Event()
        await _start_blocked_draft(app, pilot, gate)
        worker = app._draft_worker

        await pilot.press("escape")  # first Esc cancels the draft, keeps editor open

        assert app.describe_state()["compression_editor"]["open"] is True
        for _ in range(200):
            if worker.is_finished:
                break
            await pilot.pause()
        assert worker.is_finished
        await app.workers.wait_for_complete()


async def test_close_cancels_a_live_worker(app_factory):
    # The close seam itself (used by future conversation-switch paths, not just
    # Esc) must cancel a live worker before dropping the reference.
    app = app_factory()
    async with app.run_test() as pilot:
        await _two_turns(app)
        await _open_editor_on_full_range(pilot)
        gate = asyncio.Event()
        await _start_blocked_draft(app, pilot, gate)
        worker = app._draft_worker

        app._close_compression_editor()

        assert app.describe_state()["compression_editor"]["open"] is False
        assert app._draft_worker is None
        for _ in range(200):
            if worker.is_finished:
                break
            await pilot.pause()
        # The close path leaves no live worker behind.
        assert worker.is_finished
        assert all(w.is_finished for w in app.workers)
        await app.workers.wait_for_complete()


async def test_reopened_editor_summary_is_clean_after_orphan(app_factory):
    # Without the cancel-on-close fix, the orphaned worker unblocks and writes
    # its draft into the RE-OPENED editor's Summary. With the fix it is dead.
    app = app_factory()
    async with app.run_test() as pilot:
        await _two_turns(app)
        await _open_editor_on_full_range(pilot)
        gate = asyncio.Event()
        await _start_blocked_draft(app, pilot, gate)

        app._close_compression_editor()  # close WITHOUT going through Esc

        # Re-open on a different (tip) range and let the old provider unblock.
        await pilot.press("home", "down", "down", "down")  # cursor on the tip
        await pilot.press("v", "up")  # range = last two nodes
        await pilot.press("c")
        gate.set()
        for _ in range(50):
            await pilot.pause()

        # The re-opened editor's Summary is untouched by the dead worker.
        assert app.query_one("#compress-output", TextArea).text == ""
        await app.workers.wait_for_complete()
