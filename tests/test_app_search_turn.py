"""Pins the node shape of a tool-calling turn driven through the app.

Contract: tests/specs/app-search-turn.md.
"""

from pilot_helpers import turn

from ctx.models.nodes import Node
from ctx.ui.app import ChatApp
from tools.agent.harness import (
    CANNED_RESPONSE,
    HARNESS_HITS,
    HarnessProvider,
    HarnessSearch,
)

CANNED_ANSWER = "".join(CANNED_RESPONSE)


def turn_slice(app: ChatApp, submitted: str) -> list[Node]:
    """The turn's own nodes: the user node carrying ``submitted``, and all after it."""
    starts = [
        i
        for i, node in enumerate(app.core.nodes)
        if node.role == "user" and submitted in node.content
    ]
    assert starts, f"no user node carrying {submitted!r} in {[n.content for n in app.core.nodes]}"
    return app.core.nodes[starts[-1] :]


async def test_search_turn_puts_the_search_node_between_the_two_answers(
    app_factory, search_enabled
):
    """C1 — a triggered turn appends lead-in, tool output, then answer, in that order."""
    app = app_factory(provider=HarnessProvider(), search=HarnessSearch())
    async with app.run_test():
        submitted = "SEARCH what changed in the ctx0 roadmap"
        await turn(app, submitted)

        assert app.core.streaming is False
        nodes = turn_slice(app, submitted)
        assert [n.node_type for n in nodes] == ["message", "message", "search", "message"]
        assert [n.role for n in (nodes[0], nodes[1], nodes[3])] == [
            "user",
            "assistant",
            "assistant",
        ]
        assert nodes[1].content.startswith("Let me look that up.")
        # Closes ambiguity 1 in the contract: without this a correctly-positioned
        # but *empty* search node would satisfy C1, and carrying the canned hits
        # into the graph is the whole job of the two doubles.
        assert HARNESS_HITS[0].url in nodes[2].content
        assert nodes[3].content == CANNED_ANSWER


async def test_message_without_a_trigger_word_is_still_a_two_node_turn(
    app_factory, search_enabled
):
    """C2 — no trigger word means the pre-change turn: one user node, one
    assistant node, no search node."""
    app = app_factory(provider=HarnessProvider(), search=HarnessSearch())
    async with app.run_test():
        submitted = "summarise the append-only graph in two sentences"
        await turn(app, submitted)

        assert app.core.streaming is False
        nodes = turn_slice(app, submitted)
        assert [(node.role, node.node_type) for node in nodes] == [
            ("user", "message"),
            ("assistant", "message"),
        ]
        assert nodes[1].content == CANNED_ANSWER
        assert [n for n in app.core.nodes if n.node_type == "search"] == []
