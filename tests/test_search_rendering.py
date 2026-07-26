"""Rendering the web-tool nodes: search rows, model-fetched pages, inspector shape.

Contract: tests/specs/search-rendering.md
"""

from pilot_helpers import inspector_settled, turn

from ctx.models.nodes import Node
from ctx.ui.widgets.detail_inspector import DetailInspector
from ctx.ui.widgets.message_list import _pass_starts
from ctx.ui.widgets.message_row import truncation_key
from tools.agent.harness import HARNESS_HITS, HarnessProvider, HarnessSearch

CONV = "conv-search-rendering"

HITS = [
    {
        "title": "ctx0 — a conversation IDE",
        "url": "https://example.invalid/ctx0",
        "snippet": "ctx0 is the first shippable slice of ctx, a terminal chat app.",
    },
    {
        "title": "Append-only conversation graphs",
        "url": "https://example.invalid/graphs",
        "snippet": "Rewind and compression never delete a node; they append.",
        "date": "2026-03-11",
    },
]


def test_search_has_its_own_truncation_key() -> None:
    """C1 — a search row reads the "search" line budget, not the catch-all "system" one."""
    assert truncation_key("search") == "search"


def test_tool_nodes_stay_inside_the_assistant_pass() -> None:
    """C2 — model-invoked nodes sit flush; a user-included file still opens a pass."""
    nodes = [
        Node.context("Sprint notes for ctx0.", "notes.md", CONV),
        Node.user("what is ctx0", CONV),
        Node.assistant(CONV, "Let me look that up."),
        Node.search("what is ctx0", HITS, CONV),
        Node.context(
            "ctx0 is the first shippable slice of ctx.",
            "https://example.invalid/ctx0",
            CONV,
            origin="model",
        ),
        Node.assistant(CONV, "ctx0 is the first shippable slice of ctx."),
        Node.context("Team handbook, chapter 3.", "handbook.md", CONV),
        Node.user("how does compression fit in", CONV),
    ]

    assert _pass_starts(nodes) == [
        False,  # first node is never a pass start
        False,  # the query joins the file it was /include'd with
        True,  # the assistant's lead-in opens the assistant pass
        False,  # the search the model ran belongs to that pass
        False,  # so does the page the model fetched (origin == "model")
        False,  # and the answer it wrote after the tools
        True,  # a file the *user* included is a human action: it detaches
        False,  # the follow-up query joins that new human pass
    ]


async def test_inspector_shape_for_search_and_assistant_rows(app_factory, search_enabled) -> None:
    """C3, C4 — a selected search node is 3-split (prompt+content); an assistant stays flat."""
    app = app_factory(provider=HarnessProvider(), search=HarnessSearch())
    submitted = "SEARCH what is ctx0"
    async with app.run_test() as pilot:
        await turn(app, submitted)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("home")
        await pilot.pause()
        # user(0) -> assistant(1) -> search(2)
        await pilot.press("down")
        await pilot.pause()
        await pilot.press("down")
        await inspector_settled(pilot)

        state = app.describe_state()
        assert state["selected_index"] == 2
        assert state["nodes"][2]["role"] == "search"
        assert state["nodes"][2]["node_type"] == "search"

        detail = state["detail"]
        assert detail["node_index"] == 2
        assert detail["node_role"] == "search"
        assert detail["view"] == "context"
        assert detail["splits_visible"] == ["prompt", "content"]

        # Which split holds what — the one thing splits_visible cannot catch is
        # the query and the hit list landing in each other's split.
        view = app.query_one(DetailInspector).node_state
        assert view is not None
        assert view.prompt == submitted
        assert HARNESS_HITS[0].url in view.content

        # C4: the trailing assistant answer keeps the plain Markdown view.
        await pilot.press("down")
        await inspector_settled(pilot)

        detail = app.describe_state()["detail"]
        assert detail["node_role"] == "assistant"
        assert detail["view"] == "standard"
        assert detail["splits_visible"] == []
