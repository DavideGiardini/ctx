"""Behavioral tests for ctx.core.context.build_context.

Each test cites the contract item it covers (# C<n>). Expected values trace
to the adjudicated contract, never to the implementation.
"""

from ctx.core.context import build_context


def test_c1_two_turn_conversation_verbatim_order(make_node):
    # C1
    nodes = [
        make_node(role="user", content="What is X?"),
        make_node(role="assistant", content="X is Y"),
    ]
    result = build_context(nodes, lambda path: "")
    assert result == [
        {"role": "user", "content": "What is X?"},
        {"role": "assistant", "content": "X is Y"},
    ]


def test_c2_single_user_message(make_node):
    # C2
    nodes = [make_node(role="user", content="hello")]
    result = build_context(nodes, lambda path: "")
    assert result == [{"role": "user", "content": "hello"}]


def test_c3_assistant_dict_shape(make_node):
    # C3
    nodes = [
        make_node(role="user", content="hi"),
        make_node(role="assistant", content="hey there"),
    ]
    result = build_context(nodes, lambda path: "")
    assert result[1] == {"role": "assistant", "content": "hey there"}


def test_c4_system_nodes_excluded(make_node):
    # C4
    nodes = [
        make_node(role="system", content="Model set to Opus", node_type="system"),
        make_node(role="user", content="hello"),
    ]
    result = build_context(nodes, lambda path: "")
    assert result == [{"role": "user", "content": "hello"}]
    assert all(d["role"] != "system" for d in result)
    assert all("Model set to" not in d["content"] for d in result)


def test_c5_context_node_loads_and_imports(make_node, stub_loader):
    # C5
    loader = stub_loader({"notes.txt": "the file body"})
    nodes = [
        make_node(
            role="context",
            content="Included: notes.txt",
            node_type="context",
            meta={"source_path": "notes.txt"},
        ),
    ]
    result = build_context(nodes, loader)
    assert len(result) == 1
    assert result[0]["role"] == "user"
    content = result[0]["content"]
    assert "the file body" in content
    assert "notes.txt" in content
    assert "context_import" in content


def test_c6_context_label_does_not_leak(make_node, stub_loader):
    # C6
    loader = stub_loader({"notes.txt": "the file body"})
    nodes = [
        make_node(
            role="context",
            content="Included: notes.txt",
            node_type="context",
            meta={"source_path": "notes.txt"},
        ),
    ]
    result = build_context(nodes, loader)
    content = result[0]["content"]
    assert "notes.txt" in content
    assert "the file body" in content
    assert "Included:" not in content


def test_c7_context_merges_into_following_user(make_node, stub_loader):
    # C7
    loader = stub_loader({"doc.md": "DOC BODY"})
    nodes = [
        make_node(
            role="context",
            content="Included: doc.md",
            node_type="context",
            meta={"source_path": "doc.md"},
        ),
        make_node(role="user", content="summarize this"),
    ]
    result = build_context(nodes, loader)
    user_dicts = [d for d in result if d["role"] == "user"]
    assert len(user_dicts) == 1
    assert len(result) == 1
    content = user_dicts[0]["content"]
    assert "DOC BODY" in content
    assert "summarize this" in content
    assert content.index("DOC BODY") < content.index("summarize this")


def test_c8_solo_context_node_becomes_user(make_node, stub_loader):
    # C8
    loader = stub_loader({"solo.txt": "SOLO BODY"})
    nodes = [
        make_node(
            role="context",
            content="Included: solo.txt",
            node_type="context",
            meta={"source_path": "solo.txt"},
        ),
    ]
    result = build_context(nodes, loader)
    user_dicts = [d for d in result if d["role"] == "user"]
    assert len(user_dicts) == 1
    content = user_dicts[0]["content"]
    assert "SOLO BODY" in content
    assert "solo.txt" in content


def test_c9_context_attaches_to_user_not_assistant(make_node, stub_loader):
    # C9
    loader = stub_loader({"a.txt": "A BODY"})
    nodes = [
        make_node(
            role="context",
            content="Included: a.txt",
            node_type="context",
            meta={"source_path": "a.txt"},
        ),
        make_node(role="assistant", content="prior answer"),
        make_node(role="user", content="now my question"),
    ]
    result = build_context(nodes, loader)
    assistant_dicts = [d for d in result if d["role"] == "assistant"]
    assert all("A BODY" not in d["content"] for d in assistant_dicts)
    user_dicts = [d for d in result if d["role"] == "user"]
    assert any("A BODY" in d["content"] for d in user_dicts)


def test_c10_consecutive_user_messages_merged(make_node):
    # C10
    nodes = [
        make_node(role="user", content="part one"),
        make_node(role="user", content="part two"),
    ]
    result = build_context(nodes, lambda path: "")
    user_dicts = [d for d in result if d["role"] == "user"]
    assert len(user_dicts) == 1
    content = user_dicts[0]["content"]
    assert "part one" in content
    assert "part two" in content
    assert content.index("part one") < content.index("part two")


def test_c11_user_turns_separated_by_assistant_not_merged(make_node):
    # C11
    nodes = [
        make_node(role="user", content="u1"),
        make_node(role="assistant", content="a1"),
        make_node(role="user", content="u2"),
    ]
    result = build_context(nodes, lambda path: "")
    assert result == [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
    ]


def test_c12_mixed_sequence_ordering(make_node, stub_loader):
    # C12
    loader = stub_loader({"c.txt": "C BODY"})
    nodes = [
        make_node(role="user", content="u1"),
        make_node(role="assistant", content="a1"),
        make_node(
            role="context",
            content="Included: c.txt",
            node_type="context",
            meta={"source_path": "c.txt"},
        ),
        make_node(role="user", content="u2"),
    ]
    result = build_context(nodes, loader)
    assert result[0]["role"] == "user"
    assert "u1" in result[0]["content"]
    assert result[1]["role"] == "assistant"
    assert "a1" in result[1]["content"]
    assert result[2]["role"] == "user"
    assert "C BODY" in result[2]["content"]
    assert "u2" in result[2]["content"]


def test_c13_empty_nodes(make_node):
    # C13
    result = build_context([], lambda path: "")
    assert result == []


def test_c14_failed_load_surfaces_visible_marker_keeps_following_user(make_node, stub_loader):
    # C14: a failed context load is now made VISIBLE (not silently dropped) — it
    # emits an error-marked import referencing the path; the following user survives.
    loader = stub_loader({"present.txt": "x"})
    nodes = [
        make_node(
            role="context",
            content="Included: missing.txt",
            node_type="context",
            meta={"source_path": "missing.txt"},
        ),
        make_node(role="user", content="still here"),
    ]
    result = build_context(nodes, loader)
    user_dicts = [d for d in result if d["role"] == "user"]
    user_text = "\n".join(d["content"] for d in user_dicts)
    assert "still here" in user_text
    assert "missing.txt" in user_text
    assert "error" in user_text.lower()
    assert "context_import" in user_text
    assert all(d["role"] != "assistant" for d in result)


def test_c15_failed_load_surfaces_marker_alongside_user(make_node, stub_loader):
    # C15: a failed context load no longer vanishes — its error marker merges into
    # the adjacent user turn (same coalescing rule as a successful import).
    loader = stub_loader({"present.txt": "x"})
    nodes = [
        make_node(
            role="context",
            content="Included: missing.txt",
            node_type="context",
            meta={"source_path": "missing.txt"},
        ),
        make_node(role="user", content="my question"),
    ]
    result = build_context(nodes, loader)
    user_dicts = [d for d in result if d["role"] == "user"]
    assert len(user_dicts) == 1
    content = user_dicts[0]["content"]
    assert "my question" in content
    assert "missing.txt" in content
    assert "error" in content.lower()
    assert "context_import" in content


def test_c16_context_without_source_path(make_node, stub_loader):
    # C16
    loader = stub_loader({})
    nodes = [
        make_node(
            role="context",
            content="Included: nothing",
            node_type="context",
            meta={},
        ),
        make_node(role="user", content="after"),
    ]
    result = build_context(nodes, loader)
    user_dicts = [d for d in result if d["role"] == "user"]
    assert any(d["content"] == "after" or "after" in d["content"] for d in user_dicts)
    assert all("context_import" not in d["content"] for d in result)


def test_c17_multiple_imports_load_own_path_and_stay_ordered(make_node, stub_loader):
    # C17: with no assistant turn to break the run, all adjacent user-side material
    # coalesces into ONE user message (per C10 + the provider no-consecutive-role
    # rule). Each import is loaded from its own path and stays adjacent to its own
    # question, in order: one.txt/ONE -> q1 -> two.txt/TWO -> q2.
    loader = stub_loader({"one.txt": "ONE", "two.txt": "TWO"})
    nodes = [
        make_node(
            role="context",
            content="Included: one.txt",
            node_type="context",
            meta={"source_path": "one.txt"},
        ),
        make_node(role="user", content="q1"),
        make_node(
            role="context",
            content="Included: two.txt",
            node_type="context",
            meta={"source_path": "two.txt"},
        ),
        make_node(role="user", content="q2"),
    ]
    result = build_context(nodes, loader)
    user_dicts = [d for d in result if d["role"] == "user"]
    assert len(user_dicts) == 1
    content = user_dicts[0]["content"]
    # each loaded body and its source path is present...
    for needle in ("ONE", "q1", "TWO", "q2", "one.txt", "two.txt"):
        assert needle in content
    # ...and they appear in conversation order, each import before its question,
    # with no bleed (q1's pair precedes q2's pair).
    assert content.index("ONE") < content.index("q1") < content.index("TWO") < content.index("q2")
    assert content.index("one.txt") < content.index("q1")
    assert content.index("two.txt") < content.index("q2")


def test_c18_purity_no_mutation_and_deterministic(make_node, stub_loader):
    # C18
    nodes = [
        make_node(
            role="context",
            content="Included: pure.txt",
            node_type="context",
            meta={"source_path": "pure.txt"},
        ),
        make_node(role="user", content="my question"),
        make_node(role="assistant", content="my answer"),
    ]
    before_len = len(nodes)
    before = [(n.role, n.content) for n in nodes]

    loader = stub_loader({"pure.txt": "PURE BODY"})
    first = build_context(nodes, loader)
    second = build_context(nodes, loader)

    assert first == second
    assert len(nodes) == before_len
    after = [(n.role, n.content) for n in nodes]
    assert after == before


def test_c19_empty_file_body_still_imports(make_node, stub_loader):
    # C19
    loader = stub_loader({"empty.txt": ""})
    nodes = [
        make_node(
            role="context",
            content="Included: empty.txt",
            node_type="context",
            meta={"source_path": "empty.txt"},
        ),
        make_node(role="user", content="go"),
    ]
    result = build_context(nodes, loader)
    user_dicts = [d for d in result if d["role"] == "user"]
    assert len(user_dicts) == 1
    content = user_dicts[0]["content"]
    assert "go" in content
    assert "empty.txt" in content
    assert "context_import" in content


# C20. A context node whose loader raises ValueError surfaces a visible error
# marker (not silently dropped); the rest survives.
def test_context_node_loader_valueerror_surfaces_marker(make_node):
    def loader(path):
        raise ValueError("escapes sandbox")

    nodes = [
        make_node(
            role="context",
            node_type="context",
            content="Included: ../escape.txt",
            meta={"source_path": "../escape.txt"},
        ),
        make_node(role="user", content="still here"),
    ]

    result = build_context(nodes, loader)

    # The rejected import is surfaced as a user-role error marker, never raising
    # and never becoming assistant content.
    user_text = "\n".join(m["content"] for m in result if m["role"] == "user")
    assert "../escape.txt" in user_text
    assert "error" in user_text.lower()
    assert "context_import" in user_text
    # The surviving user message must still be present.
    assert "still here" in user_text
    assert all(m["role"] != "assistant" for m in result)


# C21. A context node is imported as USER material regardless of its own declared role.
def test_context_node_imported_as_user_regardless_of_role(make_node, stub_loader):
    loader = stub_loader({"a.txt": "A BODY"})

    nodes = [
        make_node(
            role="assistant",
            node_type="context",
            meta={"source_path": "a.txt"},
        ),
        make_node(role="user", content="q"),
    ]

    result = build_context(nodes, loader)

    # The imported file body must never land in an assistant message.
    assert not any(
        msg["role"] == "assistant" and "A BODY" in msg["content"] for msg in result
    )
    # The imported file body must appear in a user message.
    assert any(
        msg["role"] == "user" and "A BODY" in msg["content"] for msg in result
    )


# C22. A context node whose source_path is the empty string is skipped.
def test_context_node_empty_source_path_is_skipped(make_node, stub_loader):
    # A loader that would raise FileNotFoundError if invoked on "".
    loader = stub_loader({})

    nodes = [
        make_node(
            role="context",
            node_type="context",
            meta={"source_path": ""},
        ),
        make_node(role="user", content="after"),
    ]

    result = build_context(nodes, loader)

    # Must not raise (asserted implicitly by reaching here) and must not import.
    assert all("context_import" not in msg["content"] for msg in result)
    # The trailing user message must survive.
    assert any(
        msg["role"] == "user" and "after" in msg["content"] for msg in result
    )
