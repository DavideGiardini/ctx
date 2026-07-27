"""Acceptance floor for the shared compact-row renderer (task 36).

``MessageRow`` is the single surface behind every compact node row (the list and
the inspector splits). These tests exercise it directly — once
per role — asserting the two invariants tasks 37/38 depend on: the left-bar
color comes from the palette for that role, and the row is the standard
two-line layout (a weight meta slot above the content). A regression that
mis-mapped the bar color or dropped a slot would slip past the list-only tests.
"""

import pytest
from textual.app import App, ComposeResult
from textual.color import Color
from textual.css.query import NoMatches
from textual.widgets import Markdown, Static

from ctx.core.config import get_config
from ctx.models.nodes import Node
from ctx.ui.widgets.message_row import CARET, MessageRow, truncation_key
from tools.agent.snapshot import render

_ROLES = ["user", "assistant", "context", "system", "compression", "search"]

# Roles whose compact row renders as plain text rather than Markdown: their
# content is data (a file snapshot, a ranked hit list, a breadcrumb), and a
# Markdown pass would reflow it.
_PLAIN_TEXT = ("system", "context", "search")


def _make_node(role: str) -> Node:
    factory = {
        "user": lambda: Node.user("hello", "c1"),
        "assistant": lambda: Node.assistant("c1", "hi there"),
        "context": lambda: Node.context("file body", "file.txt", "c1"),
        "system": lambda: Node.system("a notice", "c1"),
        "compression": lambda: Node.compression("a summary", "c1", ["x"]),
        "search": lambda: Node.search(
            "what is ctx0",
            [{"title": "ctx0", "url": "https://e.invalid", "snippet": "a hit"}],
            "c1",
        ),
    }[role]
    return factory()


class _Host(App):
    def __init__(self, node: Node, *, show_weight: bool = True) -> None:
        super().__init__()
        self._node = node
        self._show_weight = show_weight

    def compose(self) -> ComposeResult:
        yield MessageRow(self._node, show_weight=self._show_weight)


@pytest.mark.parametrize(
    "role,expected",
    [
        ("user", "human"),
        ("assistant", "assistant"),
        ("context", "context"),
        ("system", "system"),
        ("compression", "assistant"),  # a K truncates like an assistant reply
        ("mystery", "system"),  # unknown roles fall back to the system cap
    ],
)
def test_truncation_key_is_the_single_source_of_truth(role, expected):
    # describe_state and the row renderer both resolve a role's truncation cap
    # through this one function; if they diverged (as app.py once did, missing the
    # compression entry) the snapshot would report a different cap than the screen.
    assert truncation_key(role) == expected


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
        # Meta slot: a weight cell.
        assert row.query_one(".weight", Static) is not None
        # Content: plain Static for the data roles, Markdown for turn roles.
        content = row.query_one(".content")
        if role in _PLAIN_TEXT:
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


async def test_search_row_has_no_kind_glyph():
    # A search reads as ordinary injected context (green bar, no marker) — the
    # meta slot carries its weight % and nothing else.
    app = _Host(_make_node("search"))
    async with app.run_test(size=(80, 24)):
        row = app.query_one(MessageRow)
        with pytest.raises(NoMatches):
            row.query_one(".kind", Static)


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


async def test_show_weight_false_blanks_the_slot_for_a_model_node():
    # Rows shown outside the live conversation (a K's folded originals in the
    # inspector) carry no context weight: the slot stays blank even for a turn
    # role, and a pushed weight can't resurrect it.
    app = _Host(_make_node("assistant"), show_weight=False)
    async with app.run_test(size=(80, 24)):
        row = app.query_one(MessageRow)
        weight = row.query_one(".weight", Static)
        assert str(weight.render()) == ""
        row.set_weight_pct(12)
        assert str(weight.render()) == ""


def test_snapshot_colors_line_shows_compression_equals_context_green():
    # Task 39 floor: the ctx_snapshot `colors:` line reports the compression bar
    # color equal to the context green (#22c55e), not the old violet.
    colors = get_config()["colors"]
    assert colors["compression"] == colors["context"] == "#22c55e"
    out = render({"mode": "edit", "model": "gpt-4o", "streaming": False, "colors": colors})
    line = next(ln for ln in out.splitlines() if ln.startswith("colors:"))
    assert "compression=#22c55e" in line and "context=#22c55e" in line


async def test_empty_row_blinks_a_full_cell_caret_until_text_arrives():
    # The caret stands in for text on its way: a full cell (not the half-block it
    # used to be), blinking by hiding the cell rather than by rewriting it — so a
    # blinking row cannot reflow the pane. Real text stops the blink for good.
    app = _Host(Node.assistant("c1"))
    async with app.run_test(size=(80, 24)):
        row = app.query_one(MessageRow)
        content = row.query_one(".content")
        assert CARET == "█"
        assert str(row.query_one(".content", Markdown)._markdown) == CARET
        assert row._blink_timer is not None

        row._toggle_caret()
        assert content.has_class("caret-off")  # hidden half of the blink

        row.update_content("the answer")
        assert row._blink_timer is None
        assert not content.has_class("caret-off")
