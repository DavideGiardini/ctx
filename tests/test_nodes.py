"""Tests for the Node factory classmethods.

Contract: tests/specs/nodes.md. Each test cites its contract item (e.g. # N1).
These are pure construction tests; no fixtures needed.
"""

from ctx.models.nodes import Node


# N1 -- user message turn: exact field combination
def test_user_field_combination():
    node = Node.user(
        content="Summarize the failing test output",
        conversation_id="conv-42",
    )
    assert node.role == "user"
    assert node.node_type == "message"
    assert node.content == "Summarize the failing test output"
    assert node.conversation_id == "conv-42"
    assert node.meta == {}


# N2 -- assistant defaults content to the empty pre-stream state
def test_assistant_default_content_is_empty():
    node = Node.assistant(conversation_id="conv-42")
    assert node.role == "assistant"
    assert node.node_type == "message"
    assert node.content == ""
    assert node.conversation_id == "conv-42"
    assert node.meta == {}


# N3 -- assistant accepts explicit content
def test_assistant_explicit_content():
    node = Node.assistant(
        conversation_id="conv-42",
        content="Here are three approaches:",
    )
    assert node.role == "assistant"
    assert node.node_type == "message"
    assert node.content == "Here are three approaches:"
    assert node.conversation_id == "conv-42"
    assert node.meta == {}


# N4 -- system breadcrumb: system role AND node_type, empty conversation_id (load-bearing)
def test_system_field_combination_and_no_conversation_id():
    node = Node.system(content="Model set to: claude-opus-4")
    assert node.role == "system"
    assert node.node_type == "system"
    assert node.content == "Model set to: claude-opus-4"
    # Load-bearing: empty conversation_id is what keeps the breadcrumb non-persistent.
    assert node.conversation_id == ""
    assert node.meta == {}


# N5 -- context reference: exact field combination
def test_context_field_combination():
    node = Node.context(
        source_path="docs/architecture/adr-0014.md",
        conversation_id="conv-42",
    )
    assert node.role == "context"
    assert node.node_type == "context"
    assert node.content == "Included: docs/architecture/adr-0014.md"
    assert node.conversation_id == "conv-42"
    assert node.meta == {"source_path": "docs/architecture/adr-0014.md"}


# N6 -- context content is the literal "Included: " + source_path, path unmangled
def test_context_content_is_literal_prefix_of_full_path():
    node = Node.context(
        source_path="src/ctx/models/nodes.py",
        conversation_id="c1",
    )
    # Exact prefix; full path preserved (not basenamed/normalized).
    assert node.content == "Included: src/ctx/models/nodes.py"


# N7 -- context stores the verbatim path under meta["source_path"]
def test_context_meta_stores_verbatim_source_path():
    node = Node.context(source_path="a/b/c.txt", conversation_id="c1")
    assert node.meta == {"source_path": "a/b/c.txt"}


# N8 -- each call gets a fresh unique, non-empty id
def test_factories_produce_unique_ids():
    a = Node.user(content="first question", conversation_id="conv-1")
    b = Node.user(content="second question", conversation_id="conv-1")
    assert a.id and b.id
    assert a.id != b.id


# N9 -- distinct calls do not share the same meta dict (no mutable-default aliasing)
def test_meta_not_aliased_across_calls():
    a = Node.user(content="first", conversation_id="conv-1")
    b = Node.user(content="second", conversation_id="conv-1")
    assert a.meta is not b.meta
    a.meta["leaked"] = True
    assert "leaked" not in b.meta


# N10 -- context meta is independent per call
def test_context_meta_independent_per_call():
    a = Node.context(source_path="alpha.md", conversation_id="c1")
    b = Node.context(source_path="beta.md", conversation_id="c1")
    assert a.meta is not b.meta
    assert a.meta == {"source_path": "alpha.md"}
    assert b.meta == {"source_path": "beta.md"}
