"""Mid-turn node mounting, stream retargeting and empty-row filtering.

Contract: tests/specs/app-mid-turn-nodes.md (C1-C4; C5 untested, see the spec).
"""

import asyncio

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


class GatedHarnessProvider(HarnessProvider):
    """A scripted harness turn that suspends before its answering round.

    ``HarnessProvider`` never awaits, so a whole multi-round turn runs inside a
    single event-loop step and ``pilot.pause()`` can only ever see the settled
    result — there is no window in which to observe a mid-turn mount. Blocking
    at the top of the round that *follows* a tool call holds the turn open at
    exactly the moment the search node has landed. Release with ``gate.set()``;
    see ``BlockingProvider``'s deadlock warning in ``conftest.py``.
    """

    def __init__(self, gate: asyncio.Event) -> None:
        self._gate = gate

    async def stream(self, messages, model, on_usage=None, tools=None, on_tool_calls=None):  # type: ignore[no-untyped-def]
        if any(message.get("role") == "tool" for message in messages):
            await self._gate.wait()
        async for token in super().stream(messages, model, on_usage, tools, on_tool_calls):
            yield token


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
