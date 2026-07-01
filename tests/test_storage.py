"""Behavioral tests for ctx.core.storage.ConversationRepository.

Each test cites its adjudicated contract item (# C<n>). Expected values trace to
the contract (the oracle), never to the implementation. The repository is exercised
purely through its public interface: init/save/load/list/get_last.

Three tests (C18 for nodes==[] and for all conversation_id=="", plus C24) previously
recorded confirmed bugs as strict-xfail; those bugs are now fixed and the markers
removed. See tests/specs/FOUND-BUGS.md.
"""

import sqlite3
from datetime import UTC, datetime

from ctx.core.storage import ConversationRepository


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


# Migration: a pre-model conversations table (no `model` column) must gain the
# column on init() without losing existing rows, and behave like a default ""
# model thereafter. This complements tests/test_model_persistence.py, which
# covers the round-trip but cannot construct a legacy-schema DB through the
# public interface alone.
_PRE_MODEL_SCHEMA = """
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    node_type TEXT NOT NULL DEFAULT 'message',
    meta TEXT NOT NULL DEFAULT '{}'
);
"""


def _make_legacy_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(_PRE_MODEL_SCHEMA)
    conn.execute(
        "INSERT INTO conversations (id, title, created_at, updated_at) "
        "VALUES ('legacy', 'Legacy chat', '2020-01-01', '2020-01-01')"
    )
    conn.execute(
        "INSERT INTO nodes (id, conversation_id, role, content) "
        "VALUES ('n1', 'legacy', 'user', 'old message')"
    )
    conn.commit()
    conn.close()


def test_init_migrates_pre_model_db_preserving_rows(tmp_path):
    db = str(tmp_path / "legacy.db")
    _make_legacy_db(db)

    repo = ConversationRepository(db)
    repo.init()  # must add the model column, not raise, not drop rows

    # Existing data survives the migration.
    assert [d["id"] for d in repo.list()] == ["legacy"]
    assert [n.content for n in repo.load("legacy")] == ["old message"]
    # The migrated row reports an empty (default) model.
    assert repo.get_model("legacy") == ""


def test_migrated_db_persists_model_on_subsequent_save(tmp_path, make_node):
    db = str(tmp_path / "legacy.db")
    _make_legacy_db(db)
    repo = ConversationRepository(db)
    repo.init()

    repo.save(
        "legacy",
        "Legacy chat",
        [make_node(content="new turn", conversation_id="legacy")],
        model="some/model",
    )

    assert repo.get_model("legacy") == "some/model"


def test_init_is_idempotent_after_migration(tmp_path):
    db = str(tmp_path / "legacy.db")
    _make_legacy_db(db)
    repo = ConversationRepository(db)
    repo.init()
    repo.init()  # second migration pass must be a no-op, not a duplicate-column error

    assert repo.get_model("legacy") == ""


# --------------------------------------------------------------------------
# Append-only conversation graph (ADR-0016). See storage.md C28-C44: save
# persists prev_id/compressed_into + active_leaf_id; get_active_leaf reads the
# tip; init() migrates a pre-graph flat DB (chained by rowid, tip = last node),
# idempotently and exactly once.
# --------------------------------------------------------------------------

# A pre-GRAPH legacy DB: it already has the `model` column (post pre-model
# migration) but LACKS the graph columns (nodes.prev_id / nodes.compressed_into
# and conversations.active_leaf_id), so init() must add + backfill them. Distinct
# from _PRE_MODEL_SCHEMA / _make_legacy_db above.
_PRE_GRAPH_SCHEMA = """
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    node_type TEXT NOT NULL DEFAULT 'message',
    meta TEXT NOT NULL DEFAULT '{}'
);
"""


def _make_pre_graph_db(path, conversation_id, node_rows, *, title="Legacy chat", model=""):
    """Create a legacy (pre-graph) SQLite DB directly.

    node_rows: iterable of dicts with keys id, role, content, node_type, meta.
    Rows are inserted in the given order, so sqlite assigns rowid in that order
    (i.e. this defines the insertion/creation order the migration must preserve).
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_PRE_GRAPH_SCHEMA)
        conn.execute(
            "INSERT INTO conversations (id, title, model, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (conversation_id, title, model, "2024-01-01T00:00:00", "2024-01-01T00:00:00"),
        )
        for row in node_rows:
            conn.execute(
                "INSERT INTO nodes (id, conversation_id, role, content, node_type, meta) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row["id"],
                    conversation_id,
                    row["role"],
                    row.get("content", ""),
                    row.get("node_type", "message"),
                    row.get("meta", "{}"),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _make_pre_graph_conv_only(path, conversation_id, *, title="Empty legacy", model=""):
    """Create a legacy DB with a conversation row but NO node rows."""
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_PRE_GRAPH_SCHEMA)
        conn.execute(
            "INSERT INTO conversations (id, title, model, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (conversation_id, title, model, "2024-01-01T00:00:00", "2024-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


# C28
def test_c28_prev_id_round_trips(repo, make_node):
    cid = "conv-1"
    n1 = make_node(role="user", content="First message in the chain", conversation_id=cid)
    n2 = make_node(role="assistant", content="Reply that follows the first", conversation_id=cid)
    n2.prev_id = n1.id

    repo.save(cid, "Chain title", [n1, n2])
    loaded = repo.load(cid)

    by_id = {node.id: node for node in loaded}
    assert by_id[n1.id].prev_id is None
    assert by_id[n2.id].prev_id == n1.id
    # full dataclass equality against the saved objects
    assert by_id[n1.id] == n1
    assert by_id[n2.id] == n2


# C29
def test_c29_compressed_into_round_trips(repo, make_node):
    cid = "conv-1"
    summary = make_node(
        role="assistant",
        content="Summary of the earlier discussion",
        node_type="summary",
        conversation_id=cid,
    )
    child = make_node(
        role="user",
        content="Original message that got folded into the summary",
        conversation_id=cid,
    )
    child.compressed_into = summary.id

    repo.save(cid, "Compression title", [summary, child])
    loaded = repo.load(cid)

    by_id = {node.id: node for node in loaded}
    assert by_id[child.id].compressed_into == summary.id
    assert by_id[summary.id].compressed_into is None
    assert by_id[summary.id] == summary
    assert by_id[child.id] == child


# C30
def test_c30_abandoned_sibling_not_dropped(repo, make_node):
    cid = "conv-1"
    n1 = make_node(role="user", content="Root of the tree", conversation_id=cid)
    n2 = make_node(role="assistant", content="Chosen branch reply", conversation_id=cid)
    n2.prev_id = n1.id
    n3 = make_node(role="assistant", content="Abandoned sibling reply", conversation_id=cid)
    n3.prev_id = n1.id

    repo.save(cid, "Tree title", [n1, n2, n3], active_leaf_id=n2.id)
    loaded = repo.load(cid)

    by_id = {node.id: node for node in loaded}
    assert set(by_id) == {n1.id, n2.id, n3.id}
    assert by_id[n3.id].prev_id == n1.id


# C31
def test_c31_active_leaf_persisted(repo, make_node):
    cid = "conv-1"
    n1 = make_node(role="user", content="Question about storage", conversation_id=cid)
    n2 = make_node(role="assistant", content="Answer about storage", conversation_id=cid)
    n2.prev_id = n1.id

    repo.save(cid, "Leaf title", [n1, n2], active_leaf_id=n2.id)

    assert repo.get_active_leaf(cid) == n2.id


# C32
def test_c32_middle_active_leaf(repo, make_node):
    cid = "conv-1"
    n1 = make_node(role="user", content="First turn", conversation_id=cid)
    n2 = make_node(role="assistant", content="Second turn", conversation_id=cid)
    n2.prev_id = n1.id
    n3 = make_node(role="user", content="Third turn", conversation_id=cid)
    n3.prev_id = n2.id

    repo.save(cid, "Middle leaf title", [n1, n2, n3], active_leaf_id=n2.id)

    assert repo.get_active_leaf(cid) == n2.id
    assert repo.get_active_leaf(cid) != n3.id
    loaded = repo.load(cid)
    assert [node.id for node in loaded] == [n1.id, n2.id, n3.id]


# C33
def test_c33_no_active_leaf_kwarg_is_none(repo, make_node):
    cid = "conv-1"
    n1 = make_node(role="user", content="A message without an explicit leaf", conversation_id=cid)
    n2 = make_node(role="assistant", content="Its reply", conversation_id=cid)
    n2.prev_id = n1.id

    repo.save(cid, "No leaf title", [n1, n2])

    assert repo.get_active_leaf(cid) is None


# C34
def test_c34_active_leaf_unknown_conversation_is_none(repo):
    assert repo.get_active_leaf("does-not-exist") is None


# C35
def test_c35_active_leaf_latest_save_wins(repo, make_node):
    cid = "conv-1"
    n1 = make_node(role="user", content="Root question", conversation_id=cid)
    n2 = make_node(role="assistant", content="First candidate reply", conversation_id=cid)
    n2.prev_id = n1.id
    n3 = make_node(role="assistant", content="Second candidate reply", conversation_id=cid)
    n3.prev_id = n1.id

    repo.save(cid, "Save one", [n1, n2, n3], active_leaf_id=n2.id)
    repo.save(cid, "Save two", [n1, n2, n3], active_leaf_id=n3.id)

    assert repo.get_active_leaf(cid) == n3.id


# C36
def test_c36_active_leaf_cleared_on_none(repo, make_node):
    cid = "conv-1"
    n1 = make_node(role="user", content="Root question", conversation_id=cid)
    n2 = make_node(role="assistant", content="A reply", conversation_id=cid)
    n2.prev_id = n1.id

    repo.save(cid, "Set leaf", [n1, n2], active_leaf_id=n2.id)
    repo.save(cid, "Clear leaf", [n1, n2], active_leaf_id=None)

    assert repo.get_active_leaf(cid) is None
    # nodes still present after the clearing save
    assert {node.id for node in repo.load(cid)} == {n1.id, n2.id}


# C37
def test_c37_legacy_migration_chains_prev_ids(repo, tmp_path):
    cid = "legacy-1"
    db_path = tmp_path / "legacy_chain.db"
    rows = [
        {"id": "a", "role": "user", "content": "alpha content"},
        {"id": "b", "role": "assistant", "content": "beta content"},
        {"id": "c", "role": "user", "content": "gamma content"},
    ]
    _make_pre_graph_db(db_path, cid, rows)

    migrated = ConversationRepository(str(db_path))
    migrated.init()

    loaded = migrated.load(cid)
    assert [node.id for node in loaded] == ["a", "b", "c"]
    by_id = {node.id: node for node in loaded}
    assert by_id["a"].prev_id is None
    assert by_id["b"].prev_id == "a"
    assert by_id["c"].prev_id == "b"
    assert by_id["a"].content == "alpha content"
    assert by_id["b"].content == "beta content"
    assert by_id["c"].content == "gamma content"


# C38
def test_c38_legacy_migration_active_leaf_is_last(repo, tmp_path):
    cid = "legacy-1"
    db_path = tmp_path / "legacy_leaf.db"
    rows = [
        {"id": "a", "role": "user", "content": "alpha content"},
        {"id": "b", "role": "assistant", "content": "beta content"},
        {"id": "c", "role": "user", "content": "gamma content"},
    ]
    _make_pre_graph_db(db_path, cid, rows)

    migrated = ConversationRepository(str(db_path))
    migrated.init()

    assert migrated.get_active_leaf(cid) == "c"


# C39
def test_c39_legacy_migration_preserves_all_fields(repo, tmp_path):
    cid = "legacy-1"
    db_path = tmp_path / "legacy_fields.db"
    rows = [
        {"id": "n-a", "role": "user", "content": "What is the plan?",
         "node_type": "message", "meta": '{"k": 1}'},
        {"id": "n-b", "role": "assistant", "content": "Here is the plan.",
         "node_type": "message", "meta": '{"k": 2}'},
        {"id": "n-c", "role": "system", "content": "Context injected.",
         "node_type": "summary", "meta": '{"k": 3}'},
        {"id": "n-d", "role": "assistant", "content": "Following up.",
         "node_type": "message", "meta": "{}"},
    ]
    _make_pre_graph_db(db_path, cid, rows)

    migrated = ConversationRepository(str(db_path))
    migrated.init()

    loaded = migrated.load(cid)
    assert len(loaded) == len(rows)
    assert [node.id for node in loaded] == ["n-a", "n-b", "n-c", "n-d"]
    for node, row in zip(loaded, rows, strict=True):
        assert node.id == row["id"]
        assert node.role == row["role"]
        assert node.content == row["content"]
        assert node.node_type == row["node_type"]
        assert node.compressed_into is None


# C40
def test_c40_legacy_single_node_migration(repo, tmp_path):
    cid = "legacy-1"
    db_path = tmp_path / "legacy_single.db"
    rows = [
        {"id": "x", "role": "user", "content": "the only message"},
    ]
    _make_pre_graph_db(db_path, cid, rows)

    migrated = ConversationRepository(str(db_path))
    migrated.init()

    loaded = migrated.load(cid)
    assert [node.id for node in loaded] == ["x"]
    assert loaded[0].prev_id is None
    assert migrated.get_active_leaf(cid) == "x"


# C41
def test_c41_legacy_conversation_with_no_nodes(repo, tmp_path):
    cid = "legacy-empty"
    db_path = tmp_path / "legacy_empty.db"
    _make_pre_graph_conv_only(db_path, cid, title="Empty legacy conversation")

    migrated = ConversationRepository(str(db_path))
    migrated.init()  # must not raise

    assert migrated.load(cid) == []
    assert migrated.get_active_leaf(cid) is None
    assert any(row["id"] == cid for row in migrated.list())


# C42
def test_c42_repeated_init_is_idempotent(repo, tmp_path):
    cid = "legacy-1"
    db_path = tmp_path / "legacy_idempotent.db"
    rows = [
        {"id": "a", "role": "user", "content": "alpha content"},
        {"id": "b", "role": "assistant", "content": "beta content"},
        {"id": "c", "role": "user", "content": "gamma content"},
    ]
    _make_pre_graph_db(db_path, cid, rows)

    migrated = ConversationRepository(str(db_path))
    migrated.init()
    baseline_ids = [node.id for node in migrated.load(cid)]
    baseline_prev = {node.id: node.prev_id for node in migrated.load(cid)}
    baseline_leaf = migrated.get_active_leaf(cid)

    migrated.init()  # second time
    migrated.init()  # third time

    loaded = migrated.load(cid)
    assert [node.id for node in loaded] == baseline_ids
    assert {node.id: node.prev_id for node in loaded} == baseline_prev
    assert migrated.get_active_leaf(cid) == baseline_leaf


# C43
def test_c43_backfill_runs_only_once(repo, tmp_path, make_node):
    # Start from a genuinely migrated legacy DB.
    legacy_cid = "legacy-1"
    db_path = tmp_path / "legacy_then_new.db"
    legacy_rows = [
        {"id": "L-a", "role": "user", "content": "legacy alpha"},
        {"id": "L-b", "role": "assistant", "content": "legacy beta"},
    ]
    _make_pre_graph_db(db_path, legacy_cid, legacy_rows)

    graph_repo = ConversationRepository(str(db_path))
    graph_repo.init()  # migration + backfill runs here

    # Save a NEW conversation with a sibling topology and active_leaf_id=None.
    new_cid = "conv-new"
    n1 = make_node(role="user", content="new root", conversation_id=new_cid)
    n2 = make_node(role="assistant", content="new chained reply", conversation_id=new_cid)
    n2.prev_id = n1.id
    n3 = make_node(role="assistant", content="new sibling reply", conversation_id=new_cid)
    n3.prev_id = n1.id  # sibling of n2, NOT chained after n2

    graph_repo.save(new_cid, "New graph conversation", [n1, n2, n3], active_leaf_id=None)

    # Call init() AGAIN — backfill must not re-run over the already-migrated DB.
    graph_repo.init()

    loaded = graph_repo.load(new_cid)
    by_id = {node.id: node for node in loaded}
    assert by_id[n3.id].prev_id == n1.id  # NOT rewritten to n2.id
    assert graph_repo.get_active_leaf(new_cid) is None  # NOT backfilled to last node


# C44
def test_c44_save_new_node_onto_migrated_conversation(repo, tmp_path, make_node):
    cid = "legacy-1"
    db_path = tmp_path / "legacy_extend.db"
    legacy_rows = [
        {"id": "a", "role": "user", "content": "alpha content"},
        {"id": "b", "role": "assistant", "content": "beta content"},
        {"id": "c", "role": "user", "content": "gamma content"},
    ]
    _make_pre_graph_db(db_path, cid, legacy_rows)

    graph_repo = ConversationRepository(str(db_path))
    graph_repo.init()

    # To EXTEND a migrated conversation: load the migrated nodes, append the new
    # one, and re-save the WHOLE list (save REPLACES the prior node set).
    loaded = graph_repo.load(cid)
    new_tip = make_node(role="assistant", content="new reply after migration", conversation_id=cid)
    new_tip.prev_id = "c"

    graph_repo.save(cid, "Extended", loaded + [new_tip], active_leaf_id=new_tip.id)

    result = graph_repo.load(cid)
    by_id = {node.id: node for node in result}
    assert set(by_id) == {"a", "b", "c", new_tip.id}
    # migration chain intact
    assert by_id["a"].prev_id is None
    assert by_id["b"].prev_id == "a"
    assert by_id["c"].prev_id == "b"
    # new node's explicit prev_id preserved
    assert by_id[new_tip.id].prev_id == "c"
    assert graph_repo.get_active_leaf(cid) == new_tip.id
