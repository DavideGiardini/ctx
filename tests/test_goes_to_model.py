"""Tests for Node.goes_to_model() — derived from tests/specs/nodes-goes-to-model.md.

Code-blind contract tests: every expected value traces to a contract Expect,
never to the implementation.
"""

from ctx.models.nodes import Node


# G1 — a user node goes to the model
def test_user_node_goes_to_model():
    node = Node.user(
        content="What does the build_context router do?",
        conversation_id="conv-001",
    )
    assert node.goes_to_model() is True


# G2 — an assistant node goes to the model
def test_assistant_node_goes_to_model():
    node = Node.assistant(
        conversation_id="conv-001",
        content="It routes the inclusion decision through goes_to_model.",
    )
    assert node.goes_to_model() is True


# G3 — a context node goes to the model (role is "context", recognized via node_type)
def test_context_node_goes_to_model():
    node = Node.context(
        content="imported file body",
        source_path="docs/architecture/adr-0014.md",
        conversation_id="conv-001",
    )
    assert node.goes_to_model() is True


# G4 — a system breadcrumb does not go to the model
def test_system_node_does_not_go_to_model():
    node = Node.system(content="Conversation forked from conv-000.")
    assert node.goes_to_model() is False


# G5 — an unrecognized kind (neither chat role nor context type) does not go to model
def test_unrecognized_kind_does_not_go_to_model():
    node = Node(
        conversation_id="conv-001",
        role="tool",
        content="search results payload",
        node_type="message",
    )
    assert node.goes_to_model() is False


# G6 — context recognized by node_type even when role is not the context role
def test_context_node_type_alone_goes_to_model():
    node = Node(
        conversation_id="conv-001",
        role="",  # not "context", not a chat role
        content="imported file contents",
        node_type="context",
    )
    assert node.goes_to_model() is True


# G7 — chat role qualifies regardless of node_type (literal OR; see A1)
def test_chat_role_goes_to_model_regardless_of_node_type():
    node = Node(
        conversation_id="conv-001",
        role="user",
        content="A user turn with an unusual node_type.",
        node_type="system",
    )
    assert node.goes_to_model() is True


# G8 — a default/empty node does not go to the model
def test_default_empty_node_does_not_go_to_model():
    node = Node(conversation_id="conv-001")  # role="", node_type="message"
    assert node.goes_to_model() is False


# G9 — the predicate returns a genuine bool
def test_predicate_returns_real_bool():
    included = Node.user(content="hi there", conversation_id="conv-001").goes_to_model()
    excluded = Node.system(content="breadcrumb").goes_to_model()
    assert included is True
    assert excluded is False
