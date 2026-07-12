"""Pilot tests for the single-owner turn lifecycle (ctx0 Phase 1).

The core contract lives in tests/test_turn_lifecycle.py (spec: conversation.md
§Turn lifecycle). This file pins the UI half — the convergence point in
``on_worker_state_changed`` — and above all the **load-bearing assumption** the
whole robust-clear design rests on (review §Turn lifecycle): Textual delivers a
terminal CANCELLED for a worker cancelled *before its first tick*, so the flag
clears even though the stream generator never ran its own code.

Cancellation choreography per tests/specs/conversation.md: cancel the consuming
worker and ``await worker.wait()`` (``pilot.pause()`` alone never advances a
blocked worker to CANCELLED), suppressing the expected ``WorkerCancelled``.
"""

import asyncio
import contextlib

from conftest import BlockingProvider, ErroringProvider
from pilot_helpers import turn, wait_until
from textual.worker import WorkerCancelled

from ctx.ui.widgets.input_bar import InputBar
from ctx.ui.widgets.message_list import MessageList


async def _settle_worker(worker) -> None:
    with contextlib.suppress(WorkerCancelled):
        await worker.wait()


async def test_cancel_before_first_tick_lowers_flag_and_frees_next_submit(
    app_factory,
):
    """THE assumption pin: a worker cancelled before its first tick still
    reaches on_worker_state_changed as CANCELLED, so end_turn lowers the flag
    (the old generator-finally could never see this case) and the next submit
    is accepted."""
    app = app_factory()
    async with app.run_test() as pilot:
        scripted = app.core._provider
        gate = asyncio.Event()
        app.core._provider = BlockingProvider([], gate)
        await app.on_input_bar_submitted(InputBar.Submitted("cancel me instantly"))
        worker = app._stream_worker
        assert worker is not None
        worker.cancel()  # before any tick: no pause between submit and cancel
        await _settle_worker(worker)

        assert await wait_until(pilot, lambda: not app.core.streaming)
        assert app._stream_worker is None

        # The slot is genuinely free: a normal scripted turn now completes.
        app.core._provider = scripted
        await turn(app, "and now a real question")
        assert not app.core.streaming
        roles = [n.role for n in app.core.nodes]
        assert roles.count("user") == 2


async def test_second_submit_mid_stream_refused_and_typed_text_kept(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        gate = asyncio.Event()
        scripted = app.core._provider
        app.core._provider = BlockingProvider(["Thinking "], gate)
        await app.on_input_bar_submitted(InputBar.Submitted("long question"))
        assert await wait_until(pilot, lambda: app.core.streaming)
        nodes_before = [n.id for n in app.core.nodes]

        # The user types ahead and hits Enter mid-stream.
        bar = app.query_one(InputBar)
        bar.value = "typed-ahead follow-up"
        await app.on_input_bar_submitted(InputBar.Submitted("typed-ahead follow-up"))

        assert bar.value == "typed-ahead follow-up"  # refusal never clears
        assert app.core.streaming  # live turn undamaged
        assert [n.id for n in app.core.nodes] == nodes_before  # nothing appended

        # Release and finish the blocked turn; the kept text can now be sent.
        gate.set()
        await app.workers.wait_for_complete()
        assert not app.core.streaming
        app.core._provider = scripted
        await app.on_input_bar_submitted(InputBar.Submitted(bar.value))
        await app.workers.wait_for_complete()
        user_texts = [n.content for n in app.core.nodes if n.role == "user"]
        assert user_texts == ["long question", "typed-ahead follow-up"]


async def test_new_mid_stream_cancels_worker_without_corruption(app_factory, repo):
    app = app_factory()
    async with app.run_test() as pilot:
        old_conv: str = ""
        gate = asyncio.Event()
        app.core._provider = BlockingProvider(["Partial "], gate)
        await app.on_input_bar_submitted(InputBar.Submitted("abandon me"))
        assert await wait_until(pilot, lambda: app.core.streaming)
        old_conv = app.core.conversation_id
        worker = app._stream_worker

        await app._handle_new_command()

        assert not app.core.streaming
        assert worker.is_cancelled or worker.is_finished
        await _settle_worker(worker)
        await pilot.pause()
        # The late CANCELLED arrived at the convergence point: the stale-turn
        # guard means the old conversation gained no mark and the fresh one
        # got nothing persisted into it.
        assert app.core.conversation_id == ""
        stored = repo.load(old_conv)
        assert all("interrupted" not in n.meta for n in stored)
        assert not app.core.streaming


async def test_error_turn_marks_node_durably_and_keeps_app_alive(app_factory, repo):
    app = app_factory()
    async with app.run_test() as pilot:
        app.core._provider = ErroringProvider()
        await app.on_input_bar_submitted(InputBar.Submitted("doomed question"))
        assert await wait_until(pilot, lambda: not app.core.streaming)
        assert app._stream_worker is None

        conv = app.core.conversation_id
        stored = repo.load(conv)
        errored = [n for n in stored if n.meta.get("error")]
        assert len(errored) == 1
        assert errored[0].meta["error"] == "boom"

        # The row renders from the durable mark, not one-shot widget text.
        row = app.query_one(MessageList).query_one(f"#msg-{errored[0].id}")
        assert "Error:" in row._content  # type: ignore[attr-defined]


async def test_ctrl_c_cancels_live_draft_not_the_app(app_factory):
    from pilot_helpers import open_editor_on_range, two_turns

    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)
        await open_editor_on_range(pilot)
        gate = asyncio.Event()
        app.core._provider = BlockingProvider(["drafting "], gate)
        await pilot.press("ctrl+d")
        assert await wait_until(
            pilot,
            lambda: app._draft_worker is not None
            and not app._draft_worker.is_finished,
        )

        app.action_cancel_stream()
        await _settle_worker(app._draft_worker)

        assert app.is_running
        assert app._draft_worker.is_cancelled
