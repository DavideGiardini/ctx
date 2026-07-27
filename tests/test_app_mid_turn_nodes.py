"""Mid-turn node mounting, stream retargeting and empty-row filtering.

Contract: tests/specs/app-mid-turn-nodes.md (C1-C4; C5 untested, see the spec).
"""

import asyncio

from conftest import GatedHarnessProvider
from pilot_helpers import turn, wait_until

from ctx.ui.widgets.input_bar import InputBar
from ctx.ui.widgets.message_list import MessageList
from tools.agent.harness import (
    CANNED_RESPONSE,
    HARNESS_HITS,
    LEAD_IN,
    HarnessProvider,
    HarnessSearch,
)


class _GatedSearch(HarnessSearch):
    """Canned backend that blocks *inside* ``search()``.

    ``HarnessSearch`` returns instantly, so the window between "the model asked for
    a search" and "the results landed" — the one the empty caret row used to
    occupy — is unobservable. This holds the turn open in exactly that window:
    ``entered`` fires when the search starts, ``release`` lets it finish.
    """

    def __init__(self, entered: asyncio.Event, release: asyncio.Event) -> None:
        super().__init__()
        self._entered = entered
        self._release = release

    async def search(self, query: str):  # type: ignore[no-untyped-def]
        self._entered.set()
        await self._release.wait()
        return await super().search(query)


def _search_node(app):
    return next((n for n in app.core.nodes if n.node_type == "search"), None)


def _assistant_turns(app):
    return [n for n in app.core.nodes if n.role == "assistant" and n.node_type == "message"]


async def test_search_node_row_is_mounted_while_the_turn_is_still_streaming(
    app_factory, search_enabled
):
    """C1: a node appended mid-turn is mounted while the turn is still live."""
    gate = asyncio.Event()
    app = app_factory(provider=GatedHarnessProvider(gate), search=HarnessSearch())
    async with app.run_test() as pilot:
        await app.on_input_bar_submitted(
            InputBar.Submitted("SEARCH how do transformers handle long contexts")
        )

        def search_row_live():
            # streaming and mounted are checked in the same poll, so a turn that
            # only mounts on settle can never satisfy this.
            if not app.core.streaming:
                return False
            node = _search_node(app)
            if node is None:
                return False
            pane = app.query_one(MessageList)
            return len(pane.query(f"#msg-{node.id}")) == 1

        try:
            assert await wait_until(pilot, search_row_live)

            node = _search_node(app)
            row = app.query_one(MessageList).query_one(f"#msg-{node.id}")
            assert HARNESS_HITS[0].url in row._content
        finally:
            # Always release: a turn left suspended at teardown hangs the suite.
            gate.set()

        assert await wait_until(pilot, lambda: not app.core.streaming)


async def test_round_two_answer_lands_in_its_own_row(app_factory, search_enabled):
    """C2: round-2 text renders in a new row, never appended to round 1's row."""
    app = app_factory(provider=HarnessProvider(), search=HarnessSearch())
    answer = "".join(CANNED_RESPONSE)
    async with app.run_test() as pilot:
        await turn(app, "SEARCH what changed in retrieval augmented generation")
        await pilot.pause()

        first, second = _assistant_turns(app)
        pane = app.query_one(MessageList)
        lead_in_row = pane.query_one(f"#msg-{first.id}")
        answer_row = pane.query_one(f"#msg-{second.id}")

        assert LEAD_IN.strip() in lead_in_row._content
        assert answer not in lead_in_row._content
        assert answer in answer_row._content


async def test_empty_assistant_node_is_kept_in_the_graph_but_filtered_from_the_view(
    app_factory, search_enabled
):
    """C3 + C4: the view drops the silent round's empty row; weights stay aligned."""
    app = app_factory(provider=HarnessProvider(), search=HarnessSearch())
    async with app.run_test() as pilot:
        await turn(app, "FETCH the changelog for the retrieval service")
        await pilot.pause()

        empty = [n for n in _assistant_turns(app) if n.content == ""]
        assert empty, "append-only graph must keep the silent round's assistant node"

        visible = app.describe_state()["nodes"]
        assert not [d for d in visible if d["role"] == "assistant" and d["content"] == ""]
        assert [d for d in visible if d["node_type"] == "context"]
        assert [d for d in visible if d["role"] == "assistant" and d["content"]]

        assert len(visible) == len(app.core.nodes) - len(empty)
        assert [d["index"] for d in visible] == list(range(len(visible)))


async def test_silent_round_gives_up_its_caret_row_before_the_search_runs(
    app_factory, search_enabled
):
    """C6: a round that answers with a tool call loses its empty ▌ row *while the
    tool is still working*, not once the results land."""
    entered, release = asyncio.Event(), asyncio.Event()
    app = app_factory(
        provider=HarnessProvider(), search=_GatedSearch(entered, release)
    )
    async with app.run_test() as pilot:
        try:
            await app.on_input_bar_submitted(
                InputBar.Submitted("FETCH the changelog for the retrieval service")
            )
            assert await wait_until(pilot, entered.is_set)

            # The observation window: the turn is live, the search has not returned
            # (no node from it yet), and round 1 streamed nothing.
            assert app.core.streaming
            assert _search_node(app) is None
            silent = [n for n in _assistant_turns(app) if n.content == ""]
            assert silent, "the FETCH script's round 1 must produce no text"

            assert not app.query_one(MessageList).query(f"#msg-{silent[0].id}")
            visible = app.describe_state()["nodes"]
            assert not [
                d for d in visible if d["role"] == "assistant" and d["content"] == ""
            ]
        finally:
            # Always release: a turn left suspended at teardown hangs the suite.
            release.set()

        assert await wait_until(pilot, lambda: not app.core.streaming)
