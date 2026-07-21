"""Deterministic DOM assertions for the conversation spacing rule (ctx0 rendering
redesign).

The ``MessageList`` is the single owner of inter-turn spacing: it places exactly
one ``Separator`` (a blank line) before each row that starts a new conversation
pass, none within a pass, and none before the first row. So the visible rule is
"one blank line between turns, none within a turn" — a context and the question
that uses it sit flush; the reply beneath them gets a blank. These assertions are
the regression net under the agent-judged visual look: they pin the exact DOM
structure the renderer produces, tying it to the pure ``_pass_starts`` boundary.
"""

import pytest
from textual.app import App, ComposeResult

from ctx.models.nodes import Node
from ctx.ui.widgets.message_list import (
    MessageList,
    MessageWidget,
    Separator,
    _pass_starts,
)

CID = "c1"

_FACTORY = {
    "user": lambda: Node.user("a question", CID),
    "assistant": lambda: Node.assistant(CID, "a reply"),
    "context": lambda: Node.context("notes.md", CID),
}


class _ListApp(App):
    def compose(self) -> ComposeResult:
        yield MessageList()


async def _layout(roles: list[str]) -> list[str]:
    """Reconcile nodes for *roles* into a MessageList and return its children in
    document order as a flat list of ``"sep"`` / role strings."""
    nodes = [_FACTORY[r]() for r in roles]
    app = _ListApp()
    async with app.run_test():
        message_list = app.query_one(MessageList)
        await message_list.reconcile(nodes)
        out: list[str] = []
        for child in message_list.children:
            if isinstance(child, Separator):
                out.append("sep")
            elif isinstance(child, MessageWidget):
                out.append(child._role)
        return out


async def test_context_then_question_sit_flush_and_reply_gets_a_blank():
    # The behaviour the redesign guarantees consistently: no blank between a
    # context and the question that uses it; one blank before the assistant reply.
    assert await _layout(["context", "user", "assistant"]) == [
        "context",
        "user",
        "sep",
        "assistant",
    ]


async def test_several_contexts_and_the_question_are_one_flush_block():
    assert await _layout(["context", "context", "user", "assistant"]) == [
        "context",
        "context",
        "user",
        "sep",
        "assistant",
    ]


async def test_each_turn_boundary_gets_exactly_one_blank():
    assert await _layout(["user", "assistant", "user", "assistant"]) == [
        "user",
        "sep",
        "assistant",
        "sep",
        "user",
        "sep",
        "assistant",
    ]


@pytest.mark.parametrize(
    "roles",
    [
        ["user"],
        ["context", "user", "assistant"],
        ["context", "context", "user", "assistant"],
        ["user", "assistant", "user", "assistant"],
        ["context", "user", "assistant", "context", "user", "assistant"],
    ],
)
async def test_separator_sits_before_exactly_each_pass_start(roles):
    # The single invariant: a Separator precedes a row iff _pass_starts says that
    # row begins a new pass. Never a leading blank (the first row is never a start).
    starts = _pass_starts(roles)
    expected: list[str] = []
    for role, is_start in zip(roles, starts, strict=True):
        if is_start:
            expected.append("sep")
        expected.append(role)
    assert await _layout(roles) == expected
    assert expected[0] != "sep"
