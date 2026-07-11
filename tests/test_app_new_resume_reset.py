"""Pilot tests for conversation-switch UI reset (PRD Sprint 3, Task 13f).

``/new`` and ``/resume`` can fire (e.g. after a mouse click focuses the InputBar
without entering Insert) while a deep-dive, an open draft editor, or a running
draft worker still stands. Each handler must tear that transient state down via
``_reset_transient_ui()`` before the switch: pop the whole deep-dive stack (and
its footer hint), close the editor without committing, cancel a live draft
worker, and clear the selection/chord/last-draft state. Otherwise a dead dive
frame resurrects the old conversation's folded children through
``_visible_nodes()``, the editor sits open over dead range ids, and a live worker
survives the switch.

The oracle is the Task 13f acceptance criterion, asserted through the public
``describe_state()`` snapshot, the footer hint, and ``app._draft_worker``
liveness. The handlers are invoked directly — the mouse path (focus without a
mode switch) has no Pilot key equivalent.
"""

import asyncio

from conftest import BlockingProvider
from pilot_helpers import (
    compress_range,
    open_editor_on_range,
    select_tip_in_edit,
    two_turns,
    wait_until,
)


async def _enter_deep_dive(app, pilot) -> None:
    await two_turns(app)
    await compress_range(app, pilot, "SUMMARY")
    # A commit clears the selection; re-select the K tip before diving.
    await select_tip_in_edit(app, pilot)
    assert app._get_selected_node().node_type == "compression"
    await pilot.press("g", "d")
    await pilot.pause()
    assert app.describe_state()["deep_dive"]["active"] is True


async def _start_blocked_draft(app, pilot, gate) -> None:
    app.core._provider = BlockingProvider(["partial"], gate)
    await pilot.press("ctrl+d")
    live = await wait_until(
        pilot, lambda: app._draft_worker is not None and not app._draft_worker.is_finished
    )
    assert live


async def test_new_resets_a_live_deep_dive(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await _enter_deep_dive(app, pilot)

        await app._handle_new_command()
        await pilot.pause()

        state = app.describe_state()
        # Dive gone: state reflects the fresh (empty) conversation, not the four
        # frozen folded children the dead dive frame would have resurrected.
        assert state["deep_dive"]["active"] is False
        assert state["deep_dive"]["breadcrumb"] == ["Chat"]
        assert state["nodes"] == []
        # Footer is back to the mode hint, not the deep-dive hint.
        assert "read-only" not in state["footer"]


async def test_resume_resets_a_live_deep_dive(app_factory, monkeypatch):
    app = app_factory()
    async with app.run_test() as pilot:
        await _enter_deep_dive(app, pilot)
        conv_id = app.core.conversation_id

        async def _fake_pick(screen):  # noqa: ANN001
            return conv_id

        monkeypatch.setattr(app, "push_screen_wait", _fake_pick)
        app._handle_resume_command()
        await app.workers.wait_for_complete()
        await pilot.pause()

        state = app.describe_state()
        assert state["deep_dive"]["active"] is False
        assert state["deep_dive"]["breadcrumb"] == ["Chat"]
        # The resumed view is the single folded K, not the four dive children.
        assert len(state["nodes"]) == 1
        assert state["nodes"][0]["node_type"] == "compression"


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
