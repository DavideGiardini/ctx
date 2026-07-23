"""Tests for NEW build_context behavior: visible context-load failures and empty-node skipping.

These tests encode product intent only (code-blind):

  1. A context node whose file fails to load (OSError or ValueError) must be
     surfaced as a VISIBLE error import marker in the built messages, never
     silently dropped and never raising out of build_context. The marker is
     user-role, references the failed source_path, carries an error indication,
     is still marked as an import, and must NOT contain a real file body.

  2. Plain user/assistant message nodes with content == "" produce no message
     dict at all (some provider APIs reject empty-content messages).

Assertions check observable substrings and dict shapes (role / content) only,
never exact marker formatting or log text.
"""

from ctx.core.context import build_context

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_text(messages):
    """Concatenate the content of every user-role message dict."""
    return "\n".join(m["content"] for m in messages if m.get("role") == "user")


def _all_text(messages):
    return "\n".join(m.get("content", "") for m in messages)


def _raising_loader(exc):
    """Return a load_file callable that always raises the given exception."""
    def load_file(path):
        raise exc
    return load_file


# ---------------------------------------------------------------------------
# Guarantee 1 — failed context load is surfaced visibly, not dropped
# ---------------------------------------------------------------------------

# C1: OSError (FileNotFoundError) during context load -> visible error marker
def test_oserror_context_load_emits_visible_error_marker(make_node, stub_loader):
    # stub_loader knows nothing about "missing.txt" -> raises FileNotFoundError (OSError).
    loader = stub_loader({"other.txt": "unrelated body"})
    ctx_node = make_node(
        role="context",
        node_type="context",
        content="Included: missing.txt",
        meta={"source_path": "missing.txt"},
    )

    messages = build_context([ctx_node], loader)

    # Must not be dropped: there is at least one message produced.
    assert messages, "failed context load must not be silently dropped"

    # The marker lands in user-role material.
    user_msgs = [m for m in messages if m.get("role") == "user"]
    assert user_msgs, "failed-load marker must be user-role"
    assert not any(m.get("role") == "assistant" for m in messages), (
        "a failed context load must never become assistant content"
    )

    text = _user_text(messages)
    # References the failed path.
    assert "missing.txt" in text
    # Carries an error indication.
    assert "could not read" in text
    # Still marked as an import.
    assert "context_import" in text


# C1b: build_context must not raise when OSError occurs during load.
def test_oserror_context_load_does_not_raise(make_node, stub_loader):
    loader = stub_loader({})  # every lookup raises FileNotFoundError
    ctx_node = make_node(
        role="context",
        node_type="context",
        content="Included: report.pdf",
        meta={"source_path": "report.pdf"},
    )

    # Should simply return messages, not propagate the OSError.
    messages = build_context([ctx_node], loader)
    assert isinstance(messages, list)
    assert "report.pdf" in _all_text(messages)


# C2: ValueError (e.g. sandbox-escape rejection) during context load -> visible marker
def test_valueerror_context_load_emits_visible_error_marker(make_node):
    loader = _raising_loader(ValueError("path escapes sandbox root"))
    ctx_node = make_node(
        role="context",
        node_type="context",
        content="Included: ../../etc/passwd",
        meta={"source_path": "../../etc/passwd"},
    )

    messages = build_context([ctx_node], loader)

    assert messages, "ValueError context load must not be silently dropped"

    user_msgs = [m for m in messages if m.get("role") == "user"]
    assert user_msgs, "failed-load marker must be user-role"
    assert not any(m.get("role") == "assistant" for m in messages)

    text = _user_text(messages)
    assert "../../etc/passwd" in text
    assert "could not read" in text
    assert "context_import" in text


# C2b: ValueError must not propagate out of build_context.
def test_valueerror_context_load_does_not_raise(make_node):
    loader = _raising_loader(ValueError("rejected"))
    ctx_node = make_node(
        role="context",
        node_type="context",
        content="Included: secret.txt",
        meta={"source_path": "secret.txt"},
    )

    messages = build_context([ctx_node], loader)
    assert isinstance(messages, list)
    assert "secret.txt" in _all_text(messages)


# C3: a failed-load marker must NOT contain a real loaded file body.
def test_failed_marker_contains_no_file_body(make_node, stub_loader):
    # The loader has a body for a DIFFERENT path; the requested one fails.
    secret_body = "TOP-SECRET-FILE-CONTENTS-SHOULD-NOT-APPEAR"
    loader = stub_loader({"known.txt": secret_body})
    ctx_node = make_node(
        role="context",
        node_type="context",
        content="Included: unknown.txt",
        meta={"source_path": "unknown.txt"},
    )

    messages = build_context([ctx_node], loader)

    text = _all_text(messages)
    assert "unknown.txt" in text
    # No successfully-loaded body exists for a failed import.
    assert secret_body not in text


# C4: a following user question still appears after a failed-load marker
#     (and per the existing merge rule may share the same user message).
def test_following_user_question_survives_failed_load(make_node, stub_loader):
    loader = stub_loader({})  # context load will fail
    ctx_node = make_node(
        role="context",
        node_type="context",
        content="Included: data.csv",
        meta={"source_path": "data.csv"},
    )
    question = make_node(role="user", content="What does the data show?")

    messages = build_context([ctx_node, question], loader)

    text = _user_text(messages)
    # Both the failed-import signal and the real question are present, user-role.
    assert "data.csv" in text
    assert "What does the data show?" in text
    # The question must never be assistant content.
    assert not any(
        m.get("role") == "assistant" and "What does the data show?" in m.get("content", "")
        for m in messages
    )


# ---------------------------------------------------------------------------
# Guarantee 2 — empty user/assistant nodes produce no message
# ---------------------------------------------------------------------------

# C5: an empty assistant node between two real turns yields no assistant dict
#     and no empty-content dict.
def test_empty_assistant_node_skipped(make_node, stub_loader):
    loader = stub_loader({})
    first = make_node(role="user", content="Please summarize the project.")
    empty_assistant = make_node(role="assistant", content="")
    second = make_node(role="user", content="Now list the open risks.")

    messages = build_context([first, empty_assistant, second], loader)

    # No dict carries empty content.
    assert all(m.get("content", "") != "" for m in messages), (
        "empty-content messages must never appear in output"
    )
    # No assistant dict was produced from the empty assistant node.
    assert not any(m.get("role") == "assistant" for m in messages), (
        "an empty assistant node must not yield an assistant message"
    )
    # Real user content is preserved.
    user_text = _user_text(messages)
    assert "Please summarize the project." in user_text
    assert "Now list the open risks." in user_text


# C5b: a real assistant turn is still emitted (control: empty-skip is targeted).
def test_real_assistant_node_still_emitted(make_node, stub_loader):
    loader = stub_loader({})
    user_turn = make_node(role="user", content="Hi there, can you help?")
    assistant_turn = make_node(role="assistant", content="Of course, I can help.")

    messages = build_context([user_turn, assistant_turn], loader)

    assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0]["content"] == "Of course, I can help."


# C6: an empty user node yields no user dict solely from it.
def test_empty_user_node_skipped(make_node, stub_loader):
    loader = stub_loader({})
    empty_user = make_node(role="user", content="")

    messages = build_context([empty_user], loader)

    # Nothing with empty content, and no message produced from the empty node alone.
    assert all(m.get("content", "") != "" for m in messages)
    assert messages == [] or all(m.get("role") != "user" for m in messages)


# C6b: an empty user node mixed with a real user node leaves only the real content.
def test_empty_user_node_does_not_contribute_content(make_node, stub_loader):
    loader = stub_loader({})
    empty_user = make_node(role="user", content="")
    real_user = make_node(role="user", content="This is a genuine question.")

    messages = build_context([empty_user, real_user], loader)

    assert all(m.get("content", "") != "" for m in messages)
    user_text = _user_text(messages)
    assert "This is a genuine question." in user_text
