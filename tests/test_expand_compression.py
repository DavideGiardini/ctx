"""Behavioral tests for ConversationCore.expand_compression and Node.expand.

Contract: tests/specs/expand_compression.md (clauses C104-C116).

expand_compression is the non-destructive inverse of commit_compression
(ADR-0016: append-only graph, K kept as off-line orphan, undo recorded as an
expand *event* node E). Assertions are on observable API only.
"""

import asyncio

import pytest
from conftest import BlockingProvider

from ctx.core.conversation import ConversationCore
from ctx.models.nodes import Node


def _make_core(repo, test_provider, workspace, tokens=None):
    core = ConversationCore(repo, test_provider(tokens or ["ok"]), workspace)
    core.setup()
    return core


async def _build_line(core):
    """Drive core to the active line [u1, a1, u2, a2]; return the four nodes."""
    u1, a1 = core.submit("What is the capital of France?")
    async for _ in core.stream(a1):
        pass
    u2, a2 = core.submit("And what is its population?")
    async for _ in core.stream(a2):
        pass
    return u1, a1, u2, a2


def _view_ids(core):
    return [n.id for n in core.current_view()]


def _has_compression(core):
    return any(n.node_type == "compression" for n in core.current_view())


# ---------------------------------------------------------------------------
# expand_compression — happy path & persistence
# ---------------------------------------------------------------------------

# C104
async def test_expand_restores_children_in_place(repo, test_provider, workspace):
    core = _make_core(repo, test_provider, workspace)
    u1, a1, u2, a2 = await _build_line(core)
    k = core.commit_compression(u2.id, a2.id, "Population summary")
    assert _view_ids(core) == [u1.id, a1.id, k.id]  # precondition: folded

    core.expand_compression(k.id)

    assert _view_ids(core) == [u1.id, a1.id, u2.id, a2.id]
    assert not _has_compression(core)


# C105
async def test_expand_clears_compressed_into_on_children(repo, test_provider, workspace):
    core = _make_core(repo, test_provider, workspace)
    u1, a1, u2, a2 = await _build_line(core)
    k = core.commit_compression(u2.id, a2.id, "Population summary")

    core.expand_compression(k.id)

    view = core.current_view()
    restored = {n.id: n for n in view}
    # children reappear individually, no compression node stands in their place
    assert u2.id in restored and a2.id in restored
    assert all(n.node_type != "compression" for n in view)
    # and their fold marker is cleared
    assert restored[u2.id].compressed_into is None
    assert restored[a2.id].compressed_into is None


# C106
async def test_expand_effect_persists_across_reload(repo, test_provider, workspace):
    core = _make_core(repo, test_provider, workspace)
    u1, a1, u2, a2 = await _build_line(core)
    k = core.commit_compression(u2.id, a2.id, "Population summary")
    core.expand_compression(k.id)

    core2 = _make_core(repo, test_provider, workspace)
    core2.resume_conversation(core.conversation_id)

    assert _view_ids(core2) == [u1.id, a1.id, u2.id, a2.id]
    assert not _has_compression(core2)


# C107
async def test_k_survives_expand_recompression_works(repo, test_provider, workspace):
    core = _make_core(repo, test_provider, workspace)
    u1, a1, u2, a2 = await _build_line(core)
    k = core.commit_compression(u2.id, a2.id, "First summary")
    core.expand_compression(k.id)

    k2 = core.commit_compression(u2.id, a2.id, "Second summary")

    assert k2.node_type == "compression"
    assert _view_ids(core) == [u1.id, a1.id, k2.id]


# C108
async def test_recompression_yields_fresh_distinct_k(repo, test_provider, workspace):
    core = _make_core(repo, test_provider, workspace)
    u1, a1, u2, a2 = await _build_line(core)
    k = core.commit_compression(u2.id, a2.id, "First summary")
    core.expand_compression(k.id)

    k2 = core.commit_compression(u2.id, a2.id, "Second summary")

    assert k2.id != k.id
    assert k2.content == "Second summary"
    assert k2.meta["range"] == [u2.id, a2.id]
    assert _view_ids(core) == [u1.id, a1.id, k2.id]


# ---------------------------------------------------------------------------
# expand_compression — rejection paths (all no-ops on the view)
# ---------------------------------------------------------------------------

# C109
async def test_expand_already_expanded_raises_and_no_mutation(repo, test_provider, workspace):
    core = _make_core(repo, test_provider, workspace)
    u1, a1, u2, a2 = await _build_line(core)
    k = core.commit_compression(u2.id, a2.id, "Population summary")
    core.expand_compression(k.id)  # first expand succeeds
    view_before = _view_ids(core)

    with pytest.raises(ValueError):
        core.expand_compression(k.id)  # already inactive

    assert _view_ids(core) == view_before == [u1.id, a1.id, u2.id, a2.id]


# C110
async def test_expand_unknown_id_raises_and_stays_folded(repo, test_provider, workspace):
    core = _make_core(repo, test_provider, workspace)
    u1, a1, u2, a2 = await _build_line(core)
    k = core.commit_compression(u2.id, a2.id, "Population summary")

    with pytest.raises(ValueError):
        core.expand_compression("does-not-exist-0000")

    assert _view_ids(core) == [u1.id, a1.id, k.id]  # still folded


# C111
async def test_expand_non_compression_node_raises_and_stays_folded(repo, test_provider, workspace):
    core = _make_core(repo, test_provider, workspace)
    u1, a1, u2, a2 = await _build_line(core)
    k = core.commit_compression(u2.id, a2.id, "Population summary")

    with pytest.raises(ValueError):
        core.expand_compression(a1.id)  # a plain assistant node, not a compression

    assert _view_ids(core) == [u1.id, a1.id, k.id]  # still folded


# C112
async def test_expand_rejected_while_streaming(repo, test_provider, workspace):
    core = _make_core(repo, test_provider, workspace)
    u1, a1, u2, a2 = await _build_line(core)
    k = core.commit_compression(u2.id, a2.id, "Population summary")
    assert _view_ids(core) == [u1.id, a1.id, k.id]

    # Swap in a provider that blocks mid-stream so the turn stays live. Building
    # the history above with a BlockingProvider would deadlock — _build_line
    # fully drains two streams and the gate is never set (see PROGRESS.md).
    gate = asyncio.Event()
    core._provider = BlockingProvider(["tok"], gate)

    # kick off a new turn and pull one token so the stream is live
    u3, a3 = core.submit("A follow-up question")
    agen = core.stream(a3)
    assert await agen.__anext__() == "tok"
    assert core.streaming is True
    try:
        with pytest.raises(ValueError):
            core.expand_compression(k.id)
    finally:
        await agen.aclose()

    # expand did not happen: K still folded (its children stay out of the view).
    # The live turn's u3/a3 are appended by submit() and are incidental here.
    view = _view_ids(core)
    assert k.id in view
    assert u2.id not in view and a2.id not in view


# C113
async def test_expand_does_not_touch_streaming_flag(repo, test_provider, workspace):
    core = _make_core(repo, test_provider, workspace)
    u1, a1, u2, a2 = await _build_line(core)
    k = core.commit_compression(u2.id, a2.id, "Population summary")
    assert core.streaming is False

    result = core.expand_compression(k.id)

    assert result is None
    assert core.streaming is False


# ---------------------------------------------------------------------------
# Node.expand factory
# ---------------------------------------------------------------------------

# C114
def test_node_expand_is_well_formed_event_node():
    e = Node.expand(target_id="k-123", anchor_id="leaf-9", conversation_id="conv-1")

    assert e.role == "expand"
    assert e.node_type == "expand"
    assert e.content == ""
    assert e.prev_id is None
    assert e.compressed_into is None
    assert e.conversation_id == "conv-1"
    assert e.meta["target"] == "k-123"
    assert e.meta["anchor"] == "leaf-9"
    assert e.goes_to_model() is False
    assert isinstance(e.id, str) and e.id != ""


# C115
def test_node_expand_tolerates_none_anchor():
    e = Node.expand(target_id="k-123", anchor_id=None, conversation_id="conv-1")

    assert e.meta["anchor"] is None
    assert e.meta["target"] == "k-123"
    assert e.node_type == "expand"
    assert e.goes_to_model() is False


# C116
def test_node_expand_distinct_ids():
    e1 = Node.expand(target_id="k-1", anchor_id="a-1", conversation_id="conv-1")
    e2 = Node.expand(target_id="k-1", anchor_id="a-1", conversation_id="conv-1")

    assert e1.id != e2.id
