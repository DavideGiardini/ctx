"""Behavioral tests for ctx.core.storage.ConversationRepository.

Each test cites its adjudicated contract item (# C<n>). Expected values trace to
the contract (the oracle), never to the implementation. The repository is exercised
purely through its public interface: init/save/load/list/get_last.

Three tests (C18 for nodes==[] and for all conversation_id=="", plus C24) previously
recorded confirmed bugs as strict-xfail; those bugs are now fixed and the markers
removed. See tests/specs/FOUND-BUGS.md.
"""

from datetime import UTC, datetime


# C1
def test_c1_init_idempotent_and_non_destructive(repo, make_node):
    # C1: re-calling init() on a populated repo raises nothing and preserves data.
    nodes = [
        make_node(role="user", content="What is the plan?", conversation_id="conv-1"),
        make_node(role="assistant", content="Here is the plan.", conversation_id="conv-1"),
    ]
    repo.save("conv-1", "Planning session", nodes)

    repo.init()  # must not raise, must not destroy

    assert repo.load("conv-1") == nodes
    assert [d["id"] for d in repo.list()] == ["conv-1"]


# C2
def test_c2_save_then_load_returns_saved_nodes(repo, make_node):
    # C2: after init(), save() then load() returns the saved nodes.
    nodes = [make_node(role="user", content="First message", conversation_id="conv-1")]
    repo.save("conv-1", "A conversation", nodes)
    assert repo.load("conv-1") == nodes


# C3
def test_c3_saving_new_conversation_creates_it(repo, make_node):
    # C3: saving a new conversation creates it with the given nodes/title/recency.
    nodes = [
        make_node(role="user", content="Let's begin", conversation_id="conv-alpha"),
        make_node(role="assistant", content="Sure thing", conversation_id="conv-alpha"),
    ]
    repo.save("conv-alpha", "Project kickoff", nodes)

    assert repo.load("conv-alpha") == nodes
    listing = repo.list()
    assert len(listing) == 1
    assert listing[0]["id"] == "conv-alpha"
    assert listing[0]["title"] == "Project kickoff"
    assert repo.get_last() == "conv-alpha"


# C4
def test_c4_resaving_overwrites_title_no_duplicate(repo, make_node):
    # C4: re-saving the same id overwrites the title in place, no duplicate row.
    repo.save(
        "conv-alpha", "Draft", [make_node(content="draft body", conversation_id="conv-alpha")]
    )
    repo.save(
        "conv-alpha", "Final", [make_node(content="final body", conversation_id="conv-alpha")]
    )

    listing = repo.list()
    assert len(listing) == 1
    assert listing[0]["id"] == "conv-alpha"
    assert listing[0]["title"] == "Final"


# C5
def test_c5_resaving_advances_recency(repo, make_node):
    # C5: re-saving an existing conversation makes it most-recent again.
    repo.save("conv-a", "Alpha", [make_node(content="a body", conversation_id="conv-a")])
    repo.save("conv-b", "Beta", [make_node(content="b body", conversation_id="conv-b")])
    assert repo.get_last() == "conv-b"

    repo.save("conv-a", "Alpha", [make_node(content="a body 2", conversation_id="conv-a")])

    assert repo.get_last() == "conv-a"
    ids = [d["id"] for d in repo.list()]
    assert ids.index("conv-a") < ids.index("conv-b")


# C6
def test_c6_resaving_replaces_nodes(repo, make_node):
    # C6: re-saving replaces the node set entirely.
    first = [
        make_node(content="one", conversation_id="conv-alpha"),
        make_node(content="two", conversation_id="conv-alpha"),
        make_node(content="three", conversation_id="conv-alpha"),
    ]
    repo.save("conv-alpha", "T", first)

    second = [
        make_node(content="alpha", conversation_id="conv-alpha"),
        make_node(content="beta", conversation_id="conv-alpha"),
    ]
    repo.save("conv-alpha", "T", second)

    assert repo.load("conv-alpha") == second


# C7
def test_c7_resaving_with_empty_list_empties_nodes(repo, make_node):
    # C7: re-saving with [] clears the conversation's nodes.
    nodes = [
        make_node(content="keep me?", conversation_id="conv-alpha"),
        make_node(content="and me?", conversation_id="conv-alpha"),
    ]
    repo.save("conv-alpha", "T", nodes)
    repo.save("conv-alpha", "T", [])

    assert repo.load("conv-alpha") == []


# C8
def test_c8_empty_conversation_id_nodes_not_persisted(repo, make_node):
    # C8: nodes with conversation_id=="" are non-persistable system notices.
    nodes = [
        make_node(role="system", content="ephemeral notice 1", conversation_id=""),
        make_node(role="system", content="ephemeral notice 2", conversation_id=""),
    ]
    repo.save("conv-alpha", "T", nodes)
    assert repo.load("conv-alpha") == []


# C9
def test_c9_mixed_list_stores_only_persistable_in_order(repo, make_node):
    # C9: persistable nodes kept in relative order, empties dropped.
    p1 = make_node(content="persist one", conversation_id="conv-mix")
    empty1 = make_node(role="system", content="notice", conversation_id="")
    p2 = make_node(content="persist two", conversation_id="conv-mix")
    empty2 = make_node(role="system", content="notice2", conversation_id="")

    repo.save("conv-mix", "T", [p1, empty1, p2, empty2])

    loaded = repo.load("conv-mix")
    assert loaded == [p1, p2]
    assert len(loaded) == 2
    assert all(n.conversation_id != "" for n in loaded)


# C10
def test_c10_round_trip_preserves_all_fields(repo):
    # C10: every Node field survives a save/load round-trip exactly.
    from ctx.models.nodes import Node

    node = Node(
        id="deadbeefcafe0001",
        conversation_id="conv-fields",
        role="assistant",
        content="Here is a detailed answer with multiple sentences.",
        node_type="tool_call",
        meta={"tool": "search", "args": {"query": "weather"}},
    )
    repo.save("conv-fields", "Field check", [node])

    loaded = repo.load("conv-fields")
    assert loaded == [node]


# C11
def test_c11_meta_survives_nested_serialization(repo):
    # C11: nested meta structures round-trip with type fidelity.
    from ctx.models.nodes import Node

    meta = {"tokens": 42, "tags": ["a", "b"], "nested": {"ok": True, "ratio": 0.5, "x": None}}
    node = Node(
        id="abc123def4560002",
        conversation_id="conv-meta",
        role="assistant",
        content="response with rich metadata",
        node_type="message",
        meta=meta,
    )
    repo.save("conv-meta", "Meta check", [node])

    loaded = repo.load("conv-meta")
    assert loaded[0].meta == meta


# C12
def test_c12_load_returns_insertion_order(repo, make_node):
    # C12: load() preserves the order in which nodes were saved.
    nodes = [
        make_node(content="c1", conversation_id="conv-order"),
        make_node(content="c2", conversation_id="conv-order"),
        make_node(content="c3", conversation_id="conv-order"),
        make_node(content="c4", conversation_id="conv-order"),
    ]
    repo.save("conv-order", "Ordering", nodes)

    loaded = repo.load("conv-order")
    assert [n.content for n in loaded] == ["c1", "c2", "c3", "c4"]
    assert loaded == nodes


# C13
def test_c13_load_unknown_conversation_returns_empty(repo):
    # C13: loading an unknown conversation returns [] (not None, no error).
    result = repo.load("does-not-exist")
    assert result == []


# C14
def test_c14_load_isolated_per_conversation(repo, make_node):
    # C14: each conversation's nodes are isolated.
    nodes_a = [
        make_node(content="a-one", conversation_id="conv-a"),
        make_node(content="a-two", conversation_id="conv-a"),
    ]
    nodes_b = [make_node(content="b-one", conversation_id="conv-b")]
    repo.save("conv-a", "A", nodes_a)
    repo.save("conv-b", "B", nodes_b)

    assert repo.load("conv-a") == nodes_a
    assert repo.load("conv-b") == nodes_b


# C15
def test_c15_list_shape(repo, make_node):
    # C15: list() returns one dict per conversation with exact keys.
    repo.save("conv-a", "First title", [make_node(content="x", conversation_id="conv-a")])
    repo.save("conv-b", "Second title", [make_node(content="y", conversation_id="conv-b")])

    listing = repo.list()
    assert len(listing) == 2
    for d in listing:
        assert set(d.keys()) == {"id", "title", "updated_at"}

    by_id = {d["id"]: d for d in listing}
    assert set(by_id.keys()) == {"conv-a", "conv-b"}
    assert by_id["conv-a"]["title"] == "First title"
    assert by_id["conv-b"]["title"] == "Second title"


# C16
def test_c16_list_ordered_most_recent_first(repo, make_node):
    # C16: list() is ordered most-recent-first.
    repo.save("first", "First", [make_node(content="1", conversation_id="first")])
    repo.save("second", "Second", [make_node(content="2", conversation_id="second")])
    repo.save("third", "Third", [make_node(content="3", conversation_id="third")])

    assert [d["id"] for d in repo.list()] == ["third", "second", "first"]


# C17
def test_c17_list_reorders_after_update(repo, make_node):
    # C17: updating a conversation moves it to the front of list().
    repo.save("a", "A", [make_node(content="a", conversation_id="a")])
    repo.save("b", "B", [make_node(content="b", conversation_id="b")])
    repo.save("c", "C", [make_node(content="c", conversation_id="c")])
    repo.save("a", "A", [make_node(content="a2", conversation_id="a")])

    assert [d["id"] for d in repo.list()] == ["a", "c", "b"]


# C18
def test_c18_zero_persisted_empty_list_not_listed(repo):
    # C18: a save yielding zero persisted nodes (nodes==[]) must not appear anywhere.
    repo.save("conv-empty", "Empty", [])

    assert "conv-empty" not in [d["id"] for d in repo.list()]
    assert repo.get_last() is None
    assert repo.load("conv-empty") == []


# C18
def test_c18_zero_persisted_all_filtered_not_listed(repo, make_node):
    # C18: a save where all nodes have conversation_id=="" yields zero persisted nodes.
    nodes = [
        make_node(role="system", content="notice a", conversation_id=""),
        make_node(role="system", content="notice b", conversation_id=""),
    ]
    repo.save("conv-filtered", "Filtered", nodes)

    assert "conv-filtered" not in [d["id"] for d in repo.list()]
    assert repo.get_last() is None
    assert repo.load("conv-filtered") == []


# C19
def test_c19_list_empty_repo(repo):
    # C19: list() on an empty repo is [].
    assert repo.list() == []


# C20
def test_c20_get_last_most_recent_id(repo, make_node):
    # C20: get_last() returns the id of the most recently saved conversation.
    repo.save("old", "Old", [make_node(content="old", conversation_id="old")])
    repo.save("new", "New", [make_node(content="new", conversation_id="new")])

    assert repo.get_last() == "new"


# C21
def test_c21_get_last_follows_recency_not_creation(repo, make_node):
    # C21: get_last() tracks recency of update, not creation.
    repo.save("a", "A", [make_node(content="a", conversation_id="a")])
    repo.save("b", "B", [make_node(content="b", conversation_id="b")])
    repo.save("a", "A", [make_node(content="a2", conversation_id="a")])

    assert repo.get_last() == "a"


# C22
def test_c22_get_last_empty_repo(repo):
    # C22: get_last() on an empty repo is None.
    assert repo.get_last() is None


# C23
def test_c23_get_last_equals_first_listed(repo, make_node):
    # C23: get_last() equals list()[0]["id"] for a non-empty repo.
    repo.save("a", "A", [make_node(content="a", conversation_id="a")])
    repo.save("b", "B", [make_node(content="b", conversation_id="b")])
    repo.save("c", "C", [make_node(content="c", conversation_id="c")])

    assert repo.get_last() == repo.list()[0]["id"]


# C24
def test_c24_same_instant_saves_ordered_most_recent_first(repo, make_node, monkeypatch):
    # C24: with a frozen clock, two saves sharing a timestamp must still order b before a.
    fixed = datetime(2024, 1, 1, tzinfo=UTC)

    class FakeDateTime:
        @staticmethod
        def now(tz=None):
            return fixed

    monkeypatch.setattr("ctx.core.storage.datetime", FakeDateTime)

    repo.save("a", "A", [make_node(content="a", conversation_id="a")])
    repo.save("b", "B", [make_node(content="b", conversation_id="b")])

    assert repo.get_last() == "b"
    ids = [d["id"] for d in repo.list()]
    assert ids.index("b") < ids.index("a")


# C25. Re-saving one conversation does not disturb another's nodes.
def test_resave_does_not_disturb_other_conversation(repo, make_node):
    nodes_a = [
        make_node(role="user", content="conv-a first", conversation_id="conv-a"),
        make_node(role="assistant", content="conv-a second", conversation_id="conv-a"),
    ]
    nodes_b = [
        make_node(role="user", content="conv-b first", conversation_id="conv-b"),
        make_node(role="assistant", content="conv-b second", conversation_id="conv-b"),
    ]
    repo.save("conv-a", "Title A", nodes_a)
    repo.save("conv-b", "Title B", nodes_b)

    nodes_a2 = [
        make_node(role="user", content="conv-a rewritten one", conversation_id="conv-a"),
        make_node(role="assistant", content="conv-a rewritten two", conversation_id="conv-a"),
        make_node(role="user", content="conv-a rewritten three", conversation_id="conv-a"),
    ]
    repo.save("conv-a", "Title A", nodes_a2)

    assert repo.load("conv-b") == nodes_b
    assert repo.load("conv-a") == nodes_a2


# C26. A single re-save updates title, recency, and nodes together.
def test_resave_updates_title_recency_and_nodes(repo, make_node):
    nodes_n1 = [
        make_node(role="user", content="x version one alpha", conversation_id="conv-x"),
        make_node(role="assistant", content="x version one beta", conversation_id="conv-x"),
    ]
    repo.save("conv-x", "T1", nodes_n1)

    nodes_y = [
        make_node(role="user", content="y content", conversation_id="conv-y"),
    ]
    repo.save("conv-y", "Y title", nodes_y)

    nodes_n2 = [
        make_node(role="user", content="x version two gamma", conversation_id="conv-x"),
        make_node(role="assistant", content="x version two delta", conversation_id="conv-x"),
        make_node(role="user", content="x version two epsilon", conversation_id="conv-x"),
    ]
    repo.save("conv-x", "T2", nodes_n2)

    listing = repo.list()
    x_entries = [entry for entry in listing if entry["id"] == "conv-x"]
    assert len(x_entries) == 1
    assert x_entries[0]["title"] == "T2"

    assert repo.get_last() == "conv-x"
    assert listing[0]["id"] == "conv-x"

    assert repo.load("conv-x") == nodes_n2


# C27. An empty-string title is stored and returned verbatim.
def test_empty_title_stored_verbatim(repo, make_node):
    nodes = [
        make_node(role="user", content="empty title conversation", conversation_id="conv-empty"),
    ]
    repo.save("conv-empty", "", nodes)

    listing = repo.list()
    entries = [entry for entry in listing if entry["id"] == "conv-empty"]
    assert len(entries) == 1
    assert entries[0]["title"] == ""

    repo.save("conv-empty", "Now named", nodes)

    listing = repo.list()
    entries = [entry for entry in listing if entry["id"] == "conv-empty"]
    assert len(entries) == 1
    assert entries[0]["title"] == "Now named"
