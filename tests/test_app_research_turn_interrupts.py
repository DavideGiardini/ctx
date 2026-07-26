"""Interrupting a *research* turn — the two clauses qa-tester cannot observe.

The Phase 4 QA brief (plan §5.2 step 9 and its negative probes) asks what happens
when a multi-round tool turn is interrupted mid-loop. Through the MCP harness that
is unobservable on principle: the doubles never await, so every research turn
settles between two MCP calls and a ``Ctrl+C`` aimed at a live turn always lands on
an idle app instead. These are the deterministic stand-ins, gated so the turn is
genuinely suspended with its search node already appended.

The ordinary-turn versions of both interrupts live in
``test_app_turn_lifecycle.py``; what is different here is that a research turn
appends nodes from *inside* the worker, so an interrupt has completed graph state
to preserve (D12) and a late append that could leak into a cleared conversation.
"""

import asyncio
import contextlib

from conftest import GatedHarnessProvider
from pilot_helpers import wait_until
from textual.worker import WorkerCancelled

from ctx.ui.widgets.input_bar import InputBar
from ctx.ui.widgets.message_list import MessageList
from tools.agent.harness import HarnessSearch


async def _settle_worker(worker) -> None:
    """Await a worker the test has just interrupted, suppressing the expected
    ``WorkerCancelled`` (``pilot.pause()`` alone never advances a blocked worker
    to CANCELLED).

    Callers assert the worker is *already* cancelled or finished before calling
    this. That order is load-bearing: a regression that left the worker suspended
    on the gate would make this ``wait()`` block forever and hang the whole pytest
    run instead of failing, which is strictly worse than a red assertion.
    """
    assert worker.is_cancelled or worker.is_finished, "interrupt left the worker live"
    with contextlib.suppress(WorkerCancelled):
        await worker.wait()


def _search_node(app):
    return next((n for n in app.core.nodes if n.node_type == "search"), None)


async def _suspended_research_turn(app, pilot):
    """Submit a research turn and return its worker once the gate holds it open
    with the search node already in the graph."""
    await app.on_input_bar_submitted(InputBar.Submitted("SEARCH what is ctx0"))
    live = await wait_until(
        pilot, lambda: app.core.streaming and _search_node(app) is not None
    )
    assert live, "research turn never suspended with its search node appended"
    return app._stream_worker


async def test_ctrl_c_mid_research_turn_keeps_the_search_node_and_the_app(
    app_factory, search_enabled
):
    """D12: Ctrl+C mid-loop drops the in-flight round, never the completed nodes —
    and cancelling a live turn wins over the ladder's exit rung."""
    gate = asyncio.Event()
    app = app_factory(provider=GatedHarnessProvider(gate), search=HarnessSearch())
    async with app.run_test() as pilot:
        try:
            worker = await _suspended_research_turn(app, pilot)
            search_id = _search_node(app).id

            app.action_cancel_stream()  # what Ctrl+C is bound to
            await _settle_worker(worker)

            assert await wait_until(pilot, lambda: not app.core.streaming)
            assert any(n.id == search_id for n in app.core.nodes)
            assert app.is_running  # cancelled the turn, never quit the app
        finally:
            # Always release: a turn left suspended at teardown hangs the suite.
            gate.set()


async def test_new_mid_research_turn_clears_the_list_with_no_stuck_streaming(
    app_factory, search_enabled
):
    """/new abandons a suspended research turn cleanly: nothing left streaming and
    no row from the abandoned turn leaking into the fresh conversation."""
    gate = asyncio.Event()
    app = app_factory(provider=GatedHarnessProvider(gate), search=HarnessSearch())
    async with app.run_test() as pilot:
        try:
            worker = await _suspended_research_turn(app, pilot)
            search_id = _search_node(app).id

            await app._handle_new_command()
            await _settle_worker(worker)
            await pilot.pause()

            assert not app.core.streaming
            assert not app.core.nodes
            assert not app.query_one(MessageList).query(f"#msg-{search_id}")
        finally:
            gate.set()
