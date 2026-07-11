"""Tests for the monotonic `created_seq` invariant.

Each test cites the contract item it checks (see tests/specs/created_seq.md).
Assertions trace to the stated intent, never to assumed internal counters:
we prefer relative orderings and, where the intent is explicit (1-based fresh /
migrated numbering), exact small values.
"""

import sqlite3

import pytest

from ctx.core.conversation import ConversationCore
from ctx.core.storage import ConversationRepository

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

# Pre-`created_seq` schema: identical to the current tables but WITHOUT the
# created_seq column on `nodes`. Used to construct legacy DBs for migration.
LEGACY_SCHEMA = """
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    active_leaf_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    node_type TEXT NOT NULL DEFAULT 'message',
    meta TEXT NOT NULL DEFAULT '{}',
    prev_id TEXT,
    compressed_into TEXT
);
"""


def build_legacy_db(path, conversations):
    """Create a raw pre-created_seq DB.

    conversations: list of (conv_id, [(node_id, role), ...]) with the node list
    already in intended creation order. Rows are inserted in that order so rowid
    order == creation order; a prev_id chain is wired up and the conversation's
    active_leaf_id points at the last node.
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(LEGACY_SCHEMA)
        for conv_id, node_specs in conversations:
            last_id = node_specs[-1][0]
            conn.execute(
                "INSERT INTO conversations "
                "(id, title, model, active_leaf_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (conv_id, "Legacy chat", "", last_id,
                 "2024-01-01T00:00:00", "2024-01-01T00:00:00"),
            )
            prev = None
            for node_id, role in node_specs:
                conn.execute(
                    "INSERT INTO nodes "
                    "(id, conversation_id, role, content, node_type, meta, "
                    "prev_id, compressed_into) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (node_id, conv_id, role, "some legacy content",
                     "message", "{}", prev, None),
                )
                prev = node_id
        conn.commit()
    finally:
        conn.close()


def build_core(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["Sure, here is an answer."]), workspace)
    core.setup()
    return core


async def drain(core, assistant_node):
    async for _ in core.stream(assistant_node):
        pass


# --------------------------------------------------------------------------- #
# C1 / C11 — migration backfill
# --------------------------------------------------------------------------- #

def test_migration_backfills_sequential_rowid_order(tmp_path):
    # C1
    path = tmp_path / "legacy.db"
    build_legacy_db(path, [
        ("conv-history", [
            ("n-one", "user"),
            ("n-two", "assistant"),
            ("n-three", "user"),
        ]),
    ])

    repo = ConversationRepository(str(path))
    repo.init()

    loaded = repo.load("conv-history")  # returned in rowid (insertion) order
    seqs = [n.created_seq for n in loaded]
    assert seqs == [1, 2, 3]


def test_migration_numbers_each_conversation_independently(tmp_path):
    # C11
    path = tmp_path / "legacy_multi.db"
    build_legacy_db(path, [
        ("conv-alpha", [
            ("a-1", "user"),
            ("a-2", "assistant"),
            ("a-3", "user"),
        ]),
        ("conv-beta", [
            ("b-1", "user"),
            ("b-2", "assistant"),
        ]),
    ])

    repo = ConversationRepository(str(path))
    repo.init()

    alpha = [n.created_seq for n in repo.load("conv-alpha")]
    beta = [n.created_seq for n in repo.load("conv-beta")]
    assert alpha == [1, 2, 3]
    assert beta == [1, 2]


def test_migration_runs_exactly_once(tmp_path):
    # C5
    path = tmp_path / "legacy_once.db"
    build_legacy_db(path, [
        ("conv-gate", [
            ("g-1", "user"),
            ("g-2", "assistant"),
            ("g-3", "user"),
        ]),
    ])

    repo = ConversationRepository(str(path))
    repo.init()  # first init performs the backfill

    # Perturb the backfilled seqs to sentinel values that no correct backfill
    # would ever produce.
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("UPDATE nodes SET created_seq = 777 WHERE id = 'g-1'")
        conn.execute("UPDATE nodes SET created_seq = 888 WHERE id = 'g-2'")
        conn.execute("UPDATE nodes SET created_seq = 999 WHERE id = 'g-3'")
        conn.commit()
    finally:
        conn.close()

    repo.init()  # second init must NOT re-run the backfill
    repo.init()  # third init likewise

    by_id = {n.id: n.created_seq for n in repo.load("conv-gate")}
    assert by_id["g-1"] == 777
    assert by_id["g-2"] == 888
    assert by_id["g-3"] == 999


# --------------------------------------------------------------------------- #
# C4 — persistence round-trip
# --------------------------------------------------------------------------- #

def test_save_load_preserves_created_seq_exactly(repo, make_node):
    # C4
    conv = "conv-roundtrip"
    n1 = make_node(role="user", content="first message", conversation_id=conv)
    n2 = make_node(role="assistant", content="a reply", conversation_id=conv)
    n3 = make_node(role="user", content="follow up", conversation_id=conv)
    # Non-contiguous, non-default seqs: exact preservation, not rowid re-sequencing.
    n1.created_seq = 3
    n2.created_seq = 7
    n3.created_seq = 11
    n2.prev_id = n1.id
    n3.prev_id = n2.id

    repo.save(conv, "Round trip", [n1, n2, n3], active_leaf_id=n3.id)
    loaded = repo.load(conv)

    by_id = {n.id: n.created_seq for n in loaded}
    assert by_id[n1.id] == 3
    assert by_id[n2.id] == 7
    assert by_id[n3.id] == 11


# --------------------------------------------------------------------------- #
# C6 / C7 / C8 — fresh conversation & monotonicity
# --------------------------------------------------------------------------- #

def test_fresh_conversation_first_node_is_seq_one(repo, test_provider, workspace):
    # C6  (assumes setup() does not pre-stamp a node — see spec ambiguity note)
    core = build_core(repo, test_provider, workspace)
    user_node, _assistant_node = core.submit("What is the capital of France?")
    assert user_node.created_seq == 1


def test_single_submit_yields_two_adjacent_increasing_seqs(repo, test_provider, workspace):
    # C7
    core = build_core(repo, test_provider, workspace)
    user_node, assistant_node = core.submit("Explain monotonic counters.")
    assert user_node.created_seq > 0
    assert assistant_node.created_seq == user_node.created_seq + 1


@pytest.mark.asyncio
async def test_seqs_strictly_increase_across_submits(repo, test_provider, workspace):
    # C8
    core = build_core(repo, test_provider, workspace)
    u1, a1 = core.submit("first question")
    await drain(core, a1)
    u2, a2 = core.submit("second question")
    await drain(core, a2)
    u3, a3 = core.submit("third question")
    await drain(core, a3)

    seqs = [u1.created_seq, a1.created_seq,
            u2.created_seq, a2.created_seq,
            u3.created_seq, a3.created_seq]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)  # all distinct, hence strictly increasing


# --------------------------------------------------------------------------- #
# C2 — rewind counts abandoned tail
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_new_node_after_rewind_exceeds_abandoned_tail(repo, test_provider, workspace):
    # C2
    core = build_core(repo, test_provider, workspace)
    u1, a1 = core.submit("first question")
    await drain(core, a1)
    u2, a2 = core.submit("second question")
    await drain(core, a2)
    u3, a3 = core.submit("third question")
    await drain(core, a3)

    abandoned_max = max(u2.created_seq, a2.created_seq,
                        u3.created_seq, a3.created_seq)

    core.rewind(a1.id)  # u2,a2,u3,a3 become an abandoned tail still in the graph

    u4, a4 = core.submit("a different second question")
    await drain(core, a4)

    # Must skip past the freed tail numbers, never reuse them.
    assert u4.created_seq > abandoned_max
    assert a4.created_seq > u4.created_seq


# --------------------------------------------------------------------------- #
# C3 — K and E get seqs
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_compression_and_expand_consume_seqs(repo, test_provider, workspace):
    # C3
    core = build_core(repo, test_provider, workspace)
    u1, a1 = core.submit("first question")
    await drain(core, a1)
    u2, a2 = core.submit("second question")
    await drain(core, a2)

    # Fold the whole line range, which currently ends at the active tip a2.
    k = core.commit_compression(u1.id, a2.id, "summary of the discussion")
    assert k.created_seq > 0
    assert k.created_seq > a2.created_seq  # K entered the graph after every line node

    core.expand_compression(k.id)  # appends event node E (consumes a seq)

    u3, a3 = core.submit("third question after expand")
    await drain(core, a3)

    # u3 must have advanced past K AND past E: E sits at k.created_seq + 1, so a
    # correctly-counted u3 is strictly greater than k.created_seq + 1.
    assert u3.created_seq > k.created_seq + 1


# --------------------------------------------------------------------------- #
# C9 — resume continues past loaded max
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_resume_continues_from_loaded_max(repo, test_provider, workspace):
    # C9
    core = build_core(repo, test_provider, workspace)
    u1, a1 = core.submit("first question")
    await drain(core, a1)
    u2, a2 = core.submit("second question")
    await drain(core, a2)

    conv_id = u1.conversation_id
    loaded_max = a2.created_seq

    core.new_conversation()  # persists the conversation, then resets to fresh

    core.resume_conversation(conv_id)  # rebuild graph from persisted seqs

    u3, a3 = core.submit("a question after resuming")
    await drain(core, a3)

    assert u3.created_seq == loaded_max + 1


# --------------------------------------------------------------------------- #
# C10 — new_conversation resets the counter
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_new_conversation_resets_to_seq_one(repo, test_provider, workspace):
    # C10  (same setup/system-node assumption as C6)
    core = build_core(repo, test_provider, workspace)
    u1, a1 = core.submit("first question in the old chat")
    await drain(core, a1)
    u2, a2 = core.submit("second question in the old chat")
    await drain(core, a2)
    assert a2.created_seq > 1  # counter genuinely advanced before the reset

    core.new_conversation()

    fresh_user, _fresh_assistant = core.submit("brand new topic entirely")
    assert fresh_user.created_seq == 1
