"""Pilot tests for conversation-switch UI reset (PRD Sprint 3, Task 13f).

``/new`` and ``/resume`` can fire (e.g. after a mouse click focuses the InputBar
without entering Insert) while an open draft editor or a running draft worker
still stands. Each handler must tear that transient state down via
``_reset_transient_ui()`` before the switch: close the editor without
committing, cancel a live draft worker, and clear the selection/last-draft
state. Otherwise the editor sits open over dead range ids and a live worker
survives the switch.

The oracle is the Task 13f acceptance criterion, asserted through the public
``describe_state()`` snapshot and ``app._draft_worker`` liveness. The handlers
are invoked directly — the mouse path (focus without a mode switch) has no Pilot
key equivalent.
"""

import asyncio

from conftest import BlockingProvider
from pilot_helpers import (
    open_editor_on_range,
    two_turns,
    wait_until,
)


async def _start_blocked_draft(app, pilot, gate) -> None:
    app.core._provider = BlockingProvider(["partial"], gate)
    await pilot.press("ctrl+d")
    live = await wait_until(
        pilot, lambda: app._draft_worker is not None and not app._draft_worker.is_finished
    )
    assert live


async def test_new_closes_an_open_editor_without_committing(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)
        await open_editor_on_range(pilot)
        assert app.describe_state()["compression_editor"]["open"] is True

        await app._handle_new_command()
        await pilot.pause()

        state = app.describe_state()
        assert state["compression_editor"]["open"] is False
        # No K was committed by the switch.
        assert not any(n["node_type"] == "compression" for n in state["nodes"])


async def test_new_cancels_a_live_draft_worker(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)
        await open_editor_on_range(pilot)
        gate = asyncio.Event()
        await _start_blocked_draft(app, pilot, gate)
        worker = app._draft_worker

        await app._handle_new_command()
        await pilot.pause()

        assert app._draft_worker is None
        for _ in range(200):
            if worker.is_finished:
                break
            await pilot.pause()
        assert worker.is_finished  # cancelled, not orphaned
        gate.set()
        await app.workers.wait_for_complete()
