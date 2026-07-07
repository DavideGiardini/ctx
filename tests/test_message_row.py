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
from textual.css.query import NoMatches
from textual.widgets import Markdown, Static

from ctx.core.config import get_config
from ctx.models.nodes import Node
from ctx.ui.widgets.message_row import MessageRow
from tools.agent.snapshot import render

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


@pytest.mark.parametrize("role", ["assistant", "system"])
async def test_colored_bar_lives_on_inner_body_not_outer_row(role):
    # Task 49: the role-colored left bar is on the inner `.row-body` wrapper, not
    # the outer row — so a selection's grey bridge padding (carried by the outer
    # row) has no colored bar bleeding through it. Covers a tall-role turn and a
    # solid-border system row.
    app = _Host(_make_node(role))
    async with app.run_test(size=(80, 24)):
        row = app.query_one(MessageRow)
        body = row.query_one(".row-body")
        expected = Color.parse(get_config()["colors"][role])
        assert body.styles.border_left[1] == expected
        assert body.styles.border_left[0] in ("tall", "solid")
        # The outer row carries no left border of its own.
        assert not row.styles.border_left[0]


async def test_compression_row_carries_a_kind_glyph():
    # Task 39: the K bar shares the context-import green, so a compression row
    # must carry a distinguishing glyph to stay apart from an imported file.
    app = _Host(_make_node("compression"))
    async with app.run_test(size=(80, 24)):
        row = app.query_one(MessageRow)
        glyph = row.query_one(".kind", Static)
        assert str(glyph.render()).strip() != ""


async def test_context_row_has_no_kind_glyph():
    # The glyph is what tells a summary apart from a same-colored file import, so
    # a context row must NOT carry it.
    app = _Host(_make_node("context"))
    async with app.run_test(size=(80, 24)):
        row = app.query_one(MessageRow)
        with pytest.raises(NoMatches):
            row.query_one(".kind", Static)


async def test_non_model_node_shows_no_weight_slot():
    # Task 43a: a system breadcrumb never reaches the model, so its weight slot
    # is blank rather than a misleading "--%" — both at first mount and after a
    # refresh pushes a (None) weight onto it.
    app = _Host(_make_node("system"))
    async with app.run_test(size=(80, 24)):
        row = app.query_one(MessageRow)
        weight = row.query_one(".weight", Static)
        assert str(weight.render()) == ""
        row.set_weight_pct(None)
        assert str(weight.render()) == ""


async def test_model_node_keeps_its_weight_slot():
    # The suppression is scoped to non-model nodes: a turn still shows its %.
    app = _Host(_make_node("assistant"))
    async with app.run_test(size=(80, 24)):
        row = app.query_one(MessageRow)
        row.set_weight_pct(12)
        assert str(row.query_one(".weight", Static).render()) == "12%"


def test_snapshot_colors_line_shows_compression_equals_context_green():
    # Task 39 floor: the ctx_snapshot `colors:` line reports the compression bar
    # color equal to the context green (#22c55e), not the old violet.
    colors = get_config()["colors"]
    assert colors["compression"] == colors["context"] == "#22c55e"
    out = render({"mode": "edit", "model": "gpt-4o", "streaming": False, "colors": colors})
    line = next(ln for ln in out.splitlines() if ln.startswith("colors:"))
    assert "compression=#22c55e" in line and "context=#22c55e" in line
