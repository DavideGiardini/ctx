"""Behavioral tests for ctx.ui.widgets.message_list._pass_starts.

_pass_starts is a pure function (list[role] -> list[bool]) that decides which
messages begin a new conversation "pass" and therefore get a top margin.

Key rule under test: context imports come from /include (a human action), so
they take the human side and detach from a preceding assistant message while
hugging the following human message. Only system nodes inherit positionally.
"""

from ctx.ui.widgets.message_list import _pass_starts


def test_reported_case_context_detaches_from_ai_hugs_next_human():
    # user -> assistant -> context(included) -> next query
    roles = ["user", "assistant", "context", "user"]
    # context starts a new (human) pass; the following user does not.
    assert _pass_starts(roles) == [False, True, True, False]


def test_leading_context_is_never_a_pass_start():
    # A context import as the very first node, then the human query.
    roles = ["context", "user"]
    assert _pass_starts(roles) == [False, False]


def test_multiple_consecutive_includes_coalesce_into_one_human_pass():
    # Only the first include flips the side away from the assistant.
    roles = ["user", "assistant", "context", "context", "user"]
    assert _pass_starts(roles) == [False, True, True, False, False]


def test_context_before_assistant_groups_with_the_human():
    roles = ["user", "context", "assistant"]
    assert _pass_starts(roles) == [False, False, True]


def test_single_node_is_never_a_pass_start():
    assert _pass_starts(["user"]) == [False]


def test_empty_list():
    assert _pass_starts([]) == []
