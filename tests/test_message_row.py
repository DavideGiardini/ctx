"""Acceptance floor for the shared compact-row renderer (task 36).

``MessageRow`` is the single surface behind every compact node row (the list,
the diff panes, the inspector splits). These tests exercise it directly — once
per role — asserting the two invariants tasks 37/38 depend on: the left-bar
color comes from the palette for that role, and the row is the standard
two-line layout (a drift+weight meta slot above the content). A regression that
mis-mapped the bar color or dropped a slot would slip past the list-only tests.
"""

import pytest
from textual.app import App, ComposeResult
from textual.color import Color
from textual.widgets import Markdown, Static

from ctx.core.config import get_config
from ctx.models.nodes import Node
from ctx.ui.widgets.message_row import MessageRow

_ROLES = ["user", "assistant", "context", "system", "compression"]


def _make_node(role: str) -> Node:
    factory = {
        "user": lambda: Node.user("hello", "c1"),
        "assistant": lambda: Node.assistant("c1", "hi there"),
        "context": lambda: Node.context("file.txt", "c1"),
        "system": lambda: Node.system("a notice", "c1"),
        "compression": lambda: Node.compression("a summary", "c1", ["x"]),
    }[role]
    return factory()


class _Host(App):
    def __init__(self, node: Node) -> None:
        super().__init__()
        self._node = node

    def compose(self) -> ComposeResult:
        yield MessageRow(self._node)


@pytest.mark.parametrize("role", _ROLES)
async def test_bar_color_matches_palette(role):
    app = _Host(_make_node(role))
    async with app.run_test(size=(80, 24)):
        row = app.query_one(MessageRow)
        expected = get_config()["colors"][role]
        assert row._border_color == Color.parse(expected)


@pytest.mark.parametrize("role", _ROLES)
async def test_two_line_layout(role):
    app = _Host(_make_node(role))
    async with app.run_test(size=(80, 24)):
        row = app.query_one(MessageRow)
        # Meta slot: a drift cell and a weight cell.
        assert row.query_one(".drift", Static) is not None
        assert row.query_one(".weight", Static) is not None
        # Content: plain Static for system/context, Markdown for turn roles.
        content = row.query_one(".content")
        if role in ("system", "context"):
            assert isinstance(content, Static) and not isinstance(content, Markdown)
        else:
            assert isinstance(content, Markdown)
