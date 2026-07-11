"""Pilot tests for dropping a zero-token interrupted node on cancel (Task 48).

Cancelling a turn-stream that produced **no** tokens must not leave the empty
assistant node lingering as a phantom ``▌`` row: the tip rewinds to the preceding
user turn (append-only — the empty node survives as an invisible abandoned tail,
never a hard delete) and the message list reconciles it away. A **partial** stream
(any tokens) is left exactly as-is — its text and its place on the line stay.

The oracle is the Task 48 acceptance criterion, asserted through ``describe_state``
(the visible node array) and the core's active tip. A ``_BlockingProvider`` yields
its ``before`` tokens then blocks, so the stream worker is genuinely mid-stream when
the test cancels it (cancelling the consuming worker, never ``athrow`` — see
``tests/specs/conversation.md``).
"""

import asyncio
import contextlib

from conftest import BlockingProvider
from textual.worker import WorkerCancelled

from ctx.core.provider import TestProvider as CannedProvider
from ctx.ui.app import ChatApp
from ctx.ui.widgets.input_bar import InputBar


async def _cancel_and_settle(app) -> None:
    """Cancel the live turn-stream and let the cancellation actually propagate.

    ``pilot.pause()`` alone does not advance a worker blocked in an ``await`` to
    its CANCELLED state; awaiting the worker does (it re-raises ``WorkerCancelled``,
    which is the expected terminal signal here, so it is suppressed)."""
    worker = app._stream_worker
    app.action_cancel_stream()
    with contextlib.suppress(WorkerCancelled):
        await worker.wait()


def _app(repo, workspace) -> ChatApp:
    return ChatApp(
        provider=CannedProvider(["ok"]),
        workspace=workspace,
        storage=repo,
    )


async def _submit_blocked(app, pilot, before: list[str], gate: asyncio.Event) -> None:
    """Swap in the blocking provider, submit a turn, and wait until the stream
    worker is live with its ``before`` tokens rendered onto the assistant node."""
    app.core._provider = BlockingProvider(before, gate)
    await app.on_input_bar_submitted(InputBar.Submitted("hello"))
    want = "".join(before)
    for _ in range(200):
        node = app._streaming_node
        if (
            app._stream_worker is not None
            and not app._stream_worker.is_finished
            and node is not None
            and node.content == want
        ):
            break
        await pilot.pause()
    assert app._stream_worker is not None and not app._stream_worker.is_finished


def _nodes(app) -> list[dict]:
    nodes: list[dict] = app.describe_state()["nodes"]
    return nodes


async def test_zero_token_cancel_drops_the_empty_node(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        gate = asyncio.Event()
        await _submit_blocked(app, pilot, before=[], gate=gate)

        # Before cancel: user + empty assistant tip.
        before = _nodes(app)
        assert [n["role"] for n in before] == ["user", "assistant"]
        assert before[-1]["content"] == ""
        user_id = app.core.current_view()[0].id

        await _cancel_and_settle(app)
        for _ in range(200):  # then wait for the drop worker to reconcile
            if len(_nodes(app)) == 1:
                break
            await pilot.pause()

        after = _nodes(app)
        assert [n["role"] for n in after] == ["user"]
        assert app.core._active_leaf_id == user_id
        await app.workers.wait_for_complete()


async def test_partial_cancel_keeps_the_node(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        gate = asyncio.Event()
        await _submit_blocked(app, pilot, before=["partial"], gate=gate)

        await _cancel_and_settle(app)
        for _ in range(20):
            await pilot.pause()

        after = _nodes(app)
        assert [n["role"] for n in after] == ["user", "assistant"]
        assert after[-1]["content"] == "partial"
        await app.workers.wait_for_complete()
