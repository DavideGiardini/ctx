"""Role-alternation / user-run-merge invariant for build_context.

Scope: ONLY the invariant that no two adjacent message dicts share a role, plus
the user-run merge rule with an explicit "\\n\\n" separator. Broader build_context
behavior is covered elsewhere. Contract: tests/specs/context_role_alternation.md.
"""

from ctx.core.context import build_context


def _assert_alternating(messages):
    """The output invariant: no two adjacent dicts share a role."""
    for prev, nxt in zip(messages, messages[1:], strict=False):
        assert prev["role"] != nxt["role"], f"adjacent same-role dicts: {messages}"


# C1 — a dropped (system) node does not split a user run
def test_dropped_node_does_not_split_user_run(make_node, stub_loader):
    nodes = [
        make_node(
            role="context",
            content="Included: alpha.txt",
            node_type="context",
            meta={"source_path": "alpha.txt"},
        ),
        make_node(role="system", content="breadcrumb", node_type="system"),
        make_node(
            role="context",
            content="Included: beta.txt",
            node_type="context",
            meta={"source_path": "beta.txt"},
        ),
    ]
    load = stub_loader({"alpha.txt": "ALPHA-BODY", "beta.txt": "BETA-BODY"})

    out = build_context(nodes, load)

    _assert_alternating(out)
    assert len(out) == 1
    assert out[0]["role"] == "user"
    content = out[0]["content"]
    assert "ALPHA-BODY" in content
    assert "BETA-BODY" in content
    # the two bodies stayed in ONE dict, separated by a blank line
    assert "\n\n" in content
    assert content.index("ALPHA-BODY") < content.index("BETA-BODY")


# C2 — compression summary merges with the following user turn, with a separator
def test_compression_then_user_merges_with_separator(make_node):
    nodes = [
        make_node(
            role="user",
            content="Earlier we agreed on the caching strategy.",
            node_type="compression",
        ),
        make_node(role="user", content="What should we do about eviction?"),
    ]

    out = build_context(nodes, load_file=lambda path: "")

    _assert_alternating(out)
    assert len(out) == 1
    assert out[0]["role"] == "user"
    content = out[0]["content"]
    assert "</conversation_summary>" in content
    assert "What should we do about eviction?" in content
    # the closing tag must NOT run straight into the following user text
    idx = content.index("</conversation_summary>") + len("</conversation_summary>")
    tail = content[idx:]
    assert tail.startswith("\n\n") or "\n\n" in content[: content.index(
        "What should we do about eviction?"
    )]
    assert "</conversation_summary>What should" not in content


# C3 — two plain consecutive user nodes merge into one dict with a separator
def test_two_user_nodes_merge_with_separator(make_node):
    nodes = [
        make_node(role="user", content="First line of the request."),
        make_node(role="user", content="Second line of the request."),
    ]

    out = build_context(nodes, load_file=lambda path: "")

    _assert_alternating(out)
    assert len(out) == 1
    assert out[0]["role"] == "user"
    content = out[0]["content"]
    assert content == "First line of the request.\n\nSecond line of the request."


# C4 — an assistant node breaks the user run into two separate user dicts
def test_assistant_breaks_user_run(make_node):
    nodes = [
        make_node(role="user", content="Question before the answer."),
        make_node(role="assistant", content="Here is the answer."),
        make_node(role="user", content="Follow-up after the answer."),
    ]

    out = build_context(nodes, load_file=lambda path: "")

    _assert_alternating(out)
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert "Question before the answer." in out[0]["content"]
    assert "Here is the answer." in out[1]["content"]
    assert "Follow-up after the answer." in out[2]["content"]
    # material after the assistant started a fresh dict, not merged into out[0]
    assert "Follow-up after the answer." not in out[0]["content"]
