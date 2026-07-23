"""Behavioral tests for the compression node factory and its rendering.

Contract: tests/specs/compression_node.md
Authored code-blind from stated intent; assertions trace to contract Expects.
"""

from ctx.core.context import build_context
from ctx.models.nodes import Node


def _users(messages):
    return [m for m in messages if m["role"] == "user"]


def _assistants(messages):
    return [m for m in messages if m["role"] == "assistant"]


# --- Factory --------------------------------------------------------------

# C1
def test_compression_canonical_fields():
    k = Node.compression("SUMMARY", "conv-1", ["a", "b"])
    assert k.role == "compression"
    assert k.node_type == "compression"
    assert k.content == "SUMMARY"
    assert k.conversation_id == "conv-1"
    assert k.meta == {"prompt": "", "range": ["a", "b"]}
    assert k.prev_id is None
    assert k.compressed_into is None


# C2
def test_compression_prompt_stored_and_defaults_empty():
    with_prompt = Node.compression(
        "s", "conv-1", ["a"], prompt="Summarize the debugging session"
    )
    assert with_prompt.meta["prompt"] == "Summarize the debugging session"

    default = Node.compression("s", "conv-1", ["a"])
    assert default.meta["prompt"] == ""


# C3
def test_compression_range_order_preserved():
    k = Node.compression("s", "conv-1", ["z", "a", "m"])
    assert k.meta["range"] == ["z", "a", "m"]


# C4
def test_compression_fresh_id_and_non_aliased_meta():
    k1 = Node.compression("first summary", "conv-1", ["a"])
    k2 = Node.compression("second summary", "conv-1", ["b"])

    assert k1.id != k2.id
    assert k1.meta is not k2.meta

    k1.meta["prompt"] = "mutated"
    assert k2.meta["prompt"] == ""


# --- goes_to_model --------------------------------------------------------

# C5
def test_compression_goes_to_model_true():
    k = Node.compression("s", "conv-1", ["a"])
    assert k.goes_to_model() is True


# C6
def test_goes_to_model_unchanged_for_existing_kinds():
    user = Node.user("What is the plan?", "conv-1")
    assistant = Node.assistant("conv-1", content="Here is the plan.")
    context = Node.context("spec body", "/docs/spec.md", "conv-1")
    system = Node.system("You are a helpful assistant.", conversation_id="conv-1")

    assert user.goes_to_model() is True
    assert assistant.goes_to_model() is True
    assert context.goes_to_model() is True
    assert system.goes_to_model() is False


# --- Rendering ------------------------------------------------------------

# C7
def test_lone_compression_renders_one_wrapped_user_dict(stub_loader):
    summary = "The team resolved the auth token race condition."
    k = Node.compression(summary, "conv-1", ["a", "b"])

    messages = build_context([k], stub_loader({}))

    assert len(messages) == 1
    msg = messages[0]
    assert msg["role"] == "user"
    assert msg["content"].startswith("<conversation_summary>")
    assert msg["content"].endswith("</conversation_summary>")
    assert summary in msg["content"]
    # no preamble/extra framing beyond the wrapper around the summary
    assert msg["content"].count("<conversation_summary>") == 1
    assert msg["content"].count("</conversation_summary>") == 1


# C8
def test_compression_then_user_coalesce_summary_first(stub_loader):
    summary = "Earlier we designed the caching layer."
    user_text = "Now add cache invalidation on write."
    k = Node.compression(summary, "conv-1", ["a"])
    u = Node.user(user_text, "conv-1")

    messages = build_context([k, u], stub_loader({}))

    users = _users(messages)
    assert len(users) == 1
    content = users[0]["content"]
    assert summary in content
    assert user_text in content
    assert content.index(summary) < content.index(user_text)
    assert "<conversation_summary>" in content


# C9
def test_user_then_compression_coalesce_user_first(stub_loader):
    user_text = "Please review the migration plan below."
    summary = "The migration plan splits the table in three phases."
    u = Node.user(user_text, "conv-1")
    k = Node.compression(summary, "conv-1", ["a"])

    messages = build_context([u, k], stub_loader({}))

    users = _users(messages)
    assert len(users) == 1
    content = users[0]["content"]
    assert user_text in content
    assert summary in content
    assert content.index(user_text) < content.index(summary)
    assert "<conversation_summary>" in content


# C10
def test_assistant_turn_splits_coalescing(stub_loader):
    summary_1 = "First we scoped the feature."
    summary_2 = "Then we broke it into tasks."
    k1 = Node.compression(summary_1, "conv-1", ["a"])
    a = Node.assistant("conv-1", content="Understood, proceeding.")
    k2 = Node.compression(summary_2, "conv-1", ["b"])

    messages = build_context([k1, a, k2], stub_loader({}))

    users = _users(messages)
    assert len(users) == 2
    assert summary_1 in users[0]["content"]
    assert summary_2 in users[1]["content"]
    assert summary_1 not in users[1]["content"]
    assert len(_assistants(messages)) == 1


# C11
def test_dropped_system_node_does_not_split_coalescing(stub_loader):
    # A dropped node (system) emits nothing and does NOT break the user run: two
    # summaries separated only by it merge into ONE user dict with a separator,
    # so no two adjacent same-role dicts ever reach a role-alternation provider
    # (task 34 corrected the task-15 coalescing-boundary rule).
    summary_1 = "Requirements were gathered from the client."
    summary_2 = "A prototype was demoed and approved."
    k1 = Node.compression(summary_1, "conv-1", ["a"])
    system = Node.system("You are a concise assistant.", conversation_id="conv-1")
    k2 = Node.compression(summary_2, "conv-1", ["b"])

    messages = build_context([k1, system, k2], stub_loader({}))

    # system never reaches the model
    assert all(m["role"] != "system" for m in messages)
    users = _users(messages)
    assert len(users) == 1
    content = users[0]["content"]
    assert summary_1 in content
    assert summary_2 in content
    assert content.index(summary_1) < content.index(summary_2)
    assert "\n\n" in content


# C12
def test_ordering_across_mixed_types_preserved(stub_loader):
    u1 = "u1 what should we build first"
    a1 = "a1 start with the parser"
    summary = "We agreed to prioritize the parser module."
    nodes = [
        Node.user(u1, "conv-1"),
        Node.assistant("conv-1", content=a1),
        Node.compression(summary, "conv-1", ["a", "b"]),
    ]

    messages = build_context(nodes, stub_loader({}))

    assert len(messages) == 3
    assert messages[0]["role"] == "user"
    assert u1 in messages[0]["content"]
    assert messages[1]["role"] == "assistant"
    assert a1 in messages[1]["content"]
    assert messages[2]["role"] == "user"
    assert summary in messages[2]["content"]
    assert "<conversation_summary>" in messages[2]["content"]


# C13
def test_folded_children_content_does_not_leak(stub_loader):
    child_a = Node.user("SECRET child body about the outage root cause", "conv-1")
    child_b = Node.assistant("conv-1", content="ANOTHER hidden child response")
    summary = "The outage was caused by a misconfigured load balancer."
    k = Node.compression(summary, "conv-1", [child_a.id, child_b.id])

    messages = build_context([k], stub_loader({}))

    rendered = "".join(m["content"] for m in messages)
    assert summary in rendered
    assert "SECRET child body about the outage root cause" not in rendered
    assert "ANOTHER hidden child response" not in rendered
