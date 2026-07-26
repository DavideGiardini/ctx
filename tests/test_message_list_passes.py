"""Behavioral tests for ctx.ui.widgets.message_list._pass_starts.

_pass_starts is a pure function (list[Node] -> list[bool]) that decides which
messages begin a new conversation "pass" and therefore get a top margin.

Key rule under test: context imports come from /include (a human action), so
they take the human side and detach from a preceding assistant message while
hugging the following human message. Only system nodes inherit positionally.
"""

from ctx.models.nodes import Node
from ctx.ui.widgets.message_list import _pass_starts


def nodes(*roles: str) -> list[Node]:
    """Nodes carrying only the roles under test. ``_pass_starts`` reads whole
    nodes (a model-fetched page's side depends on its ``meta``), but every case
    here turns on the role alone."""
    return [Node(role=role, node_type=role) for role in roles]


def test_reported_case_context_detaches_from_ai_hugs_next_human():
    # user -> assistant -> context(included) -> next query
    # context starts a new (human) pass; the following user does not.
    assert _pass_starts(nodes("user", "assistant", "context", "user")) == [
        False,
        True,
        True,
        False,
    ]


def test_leading_context_is_never_a_pass_start():
    # A context import as the very first node, then the human query.
    assert _pass_starts(nodes("context", "user")) == [False, False]


def test_multiple_consecutive_includes_coalesce_into_one_human_pass():
    # Only the first include flips the side away from the assistant.
    assert _pass_starts(nodes("user", "assistant", "context", "context", "user")) == [
        False,
        True,
        True,
        False,
        False,
    ]


def test_context_before_assistant_groups_with_the_human():
    assert _pass_starts(nodes("user", "context", "assistant")) == [False, False, True]


def test_compression_after_assistant_starts_a_new_pass():
    # A K folding a range that ended in an assistant reply lands on the same
    # (assistant) side it inherits, but must still detach from the reply above
    # it (task 40): it is its own block.
    assert _pass_starts(nodes("user", "assistant", "compression")) == [False, True, True]


def test_leading_compression_is_never_a_pass_start():
    # index 0 is never a start; the following human query legitimately begins its
    # own pass (K sits on the assistant side).
    assert _pass_starts(nodes("compression", "user")) == [False, True]


def test_single_node_is_never_a_pass_start():
    assert _pass_starts(nodes("user")) == [False]


def test_empty_list():
    assert _pass_starts([]) == []
