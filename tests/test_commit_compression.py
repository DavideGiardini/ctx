"""Behavioral tests for ConversationCore.commit_compression + current_view folding.

Contract: tests/specs/commit_compression.md (C91–C103). Written code-blind from
intent; assertions trace to contract Expect clauses, never to assumed internals.
"""

import asyncio

import pytest
from conftest import BlockingProvider

from ctx.core.conversation import ConversationCore

# --- helpers ----------------------------------------------------------------

def _ids(core):
    return [n.id for n in core.current_view()]


def _types(core):
    return [n.node_type for n in core.current_view()]


def _has_compression(core):
    return any(n.node_type == "compression" for n in core.current_view())


async def _build_line(core):
    """Build the canonical line [u1, a1, u2, a2] with tip = a2."""
    u1, a1 = core.submit("Explain how a hash map handles collisions.")
    async for _ in core.stream(a1):
        pass
    core.end_turn(a1)
    u2, a2 = core.submit("Now compare that with an open-addressing scheme.")
    async for _ in core.stream(a2):
        pass
    core.end_turn(a2)
    return u1, a1, u2, a2


def _make_core(repo, test_provider, workspace, tokens=None):
    core = ConversationCore(repo, test_provider(tokens or ["ok"]), workspace)
    core.setup()
    return core


# --- folded_children accessor (Task 10) -------------------------------------

async def test_folded_children_returns_range_in_recorded_order(
    repo, test_provider, workspace
):
    core = _make_core(repo, test_provider, workspace)
    u1, a1, u2, a2 = await _build_line(core)
    k = core.commit_compression(u1.id, a2.id, "Summary.")

    # The folded children are gone from the view but reachable via the accessor,
    # in the exact order K recorded (K.meta["range"]).
    assert [c.id for c in core.folded_children(k.id)] == [u1.id, a1.id, u2.id, a2.id]
    assert not any(n.id in {u1.id, a1.id, u2.id, a2.id} for n in core.current_view())


def test_folded_children_unknown_id_returns_empty(repo, test_provider, workspace):
    core = _make_core(repo, test_provider, workspace)
    assert core.folded_children("no-such-node") == []


async def test_folded_children_non_compression_node_returns_empty(
    repo, test_provider, workspace
):
    core = _make_core(repo, test_provider, workspace)
    _u1, a1, _u2, _a2 = await _build_line(core)
    # A real node that is not a compression K → not foldable → [].
    assert core.folded_children(a1.id) == []


# --- happy path -------------------------------------------------------------

async def test_tip_commit_folds_suffix(repo, test_provider, workspace):
    # C91
    core = _make_core(repo, test_provider, workspace)
    u1, a1, u2, a2 = await _build_line(core)

    k = core.commit_compression(u2.id, a2.id, "Summary of the collision discussion.")

    view = core.current_view()
    assert _ids(core) == [u1.id, a1.id, k.id]
    assert u2.id not in _ids(core)
    assert a2.id not in _ids(core)
    assert view[-1].id == k.id


async def test_k_fields_correct(repo, test_provider, workspace):
    # C92
    core = _make_core(repo, test_provider, workspace)
    u1, a1, u2, a2 = await _build_line(core)

    summary = "Collision handling: chaining vs open addressing."
    prompt = "Compress the last exchange tersely."
    k = core.commit_compression(u2.id, a2.id, summary, prompt=prompt)

    assert k.role == "compression"
    assert k.node_type == "compression"
    assert k.content == summary
    assert k.meta["prompt"] == prompt
    assert k.meta["range"] == [u2.id, a2.id]  # oldest-first, view order


async def test_prompt_defaults_to_empty(repo, test_provider, workspace):
    # C93
    core = _make_core(repo, test_provider, workspace)
    _u1, _a1, u2, a2 = await _build_line(core)

    k = core.commit_compression(u2.id, a2.id, "A concise summary.")

    assert k.meta["prompt"] == ""


async def test_single_node_fold(repo, test_provider, workspace):
    # C94
    core = _make_core(repo, test_provider, workspace)
    u1, a1, u2, a2 = await _build_line(core)

    k = core.commit_compression(a2.id, a2.id, "Just the final answer, condensed.")

    assert _ids(core) == [u1.id, a1.id, u2.id, k.id]
    assert k.meta["range"] == [a2.id]


async def test_prefix_unchanged(repo, test_provider, workspace):
    # C95
    core = _make_core(repo, test_provider, workspace)
    u1, a1, u2, a2 = await _build_line(core)

    before_prefix = [(n.id, n.role, n.content, n.node_type) for n in core.current_view()[:2]]
    core.commit_compression(u2.id, a2.id, "Summary text.")

    after_prefix = [(n.id, n.role, n.content, n.node_type) for n in core.current_view()[:-1]]
    assert after_prefix == before_prefix


# --- persistence ------------------------------------------------------------

async def test_reload_round_trip(repo, test_provider, workspace):
    # C96 / C97 — children preserved + view reproduced after resume
    core = _make_core(repo, test_provider, workspace)
    u1, a1, u2, a2 = await _build_line(core)

    summary = "Folded exchange about open addressing."
    prompt = "keep it short"
    core.commit_compression(u2.id, a2.id, summary, prompt=prompt)
    expected_ids = _ids(core)
    expected_types = _types(core)

    core2 = _make_core(repo, test_provider, workspace)
    core2.resume_conversation(core.conversation_id)

    assert _ids(core2) == expected_ids
    assert _types(core2) == expected_types
    reloaded_k = core2.current_view()[-1]
    assert reloaded_k.node_type == "compression"
    assert reloaded_k.content == summary
    assert reloaded_k.meta["prompt"] == prompt
    assert reloaded_k.meta["range"] == [u2.id, a2.id]


# --- rejections (all raise ValueError before mutating) ----------------------

async def test_middle_range_commits(repo, test_provider, workspace):
    # C98 — the 3a tip guard was deleted in task 22: a mid-line range (not ending
    # at the tip) now folds. View [u1, a1, u2, a2] → compress [u1, a1] → [K, u2, a2].
    core = _make_core(repo, test_provider, workspace)
    u1, a1, u2, a2 = await _build_line(core)

    k = core.commit_compression(u1.id, a1.id, "Head folded.")

    assert _ids(core) == [k.id, u2.id, a2.id]
    assert _types(core) == ["compression", "message", "message"]
    assert [n.role for n in core.current_view()] == ["compression", "user", "assistant"]
    assert k.meta["range"] == [u1.id, a1.id]


async def test_flat_guard_rejects_compression_in_range(repo, test_provider, workspace):
    # C99
    core = _make_core(repo, test_provider, workspace)
    u1, a1, u2, a2 = await _build_line(core)
    k = core.commit_compression(u2.id, a2.id, "First fold.")
    before = _ids(core)

    with pytest.raises(ValueError):
        core.commit_compression(u1.id, k.id, "Nested fold attempt.")

    assert _ids(core) == before
    # exactly one compression node remains (the original K), no second one added
    assert sum(1 for n in core.current_view() if n.node_type == "compression") == 1


async def test_streaming_guard_rejects_during_live_stream(repo, test_provider, workspace):
    # C100
    gate = asyncio.Event()
    core = ConversationCore(repo, BlockingProvider(["tok"], gate), workspace)
    core.setup()
    u1, a1 = core.submit("Kick off a streaming turn.")
    agen = core.stream(a1)
    assert await agen.__anext__() == "tok"  # stream is live now
    try:
        assert core.streaming is True
        with pytest.raises(ValueError):
            core.commit_compression(u1.id, a1.id, "Should be blocked mid-turn.")
    finally:
        await agen.aclose()

    assert not _has_compression(core)


async def test_events_rejected_in_submit_to_first_tick_window(
    repo, test_provider, workspace
):
    # Task 28 / ADR-0016 A#3 §2: the turn is in flight from submit(), before the
    # first stream tick builds its context. commit/expand/draft must all raise in
    # that window — else the event folds into what the model actually saw while
    # seq-based reconstruction says it didn't, poisoning the ctx_hash oracle.
    core = _make_core(repo, test_provider, workspace)
    u1, a1, u2, a2 = await _build_line(core)
    k = core.commit_compression(u1.id, a1.id, "First turn summary.")
    assert core.streaming is False  # drained turns + a pure commit: not in flight

    # Open the window: submit a new turn but never tick its stream.
    _u3, a3 = core.submit("A third question.")
    assert core.streaming is True

    view_before = _ids(core)
    with pytest.raises(ValueError):
        core.commit_compression(u2.id, a2.id, "Blocked in the window.")
    with pytest.raises(ValueError):
        core.expand_compression(k.id)  # K is active — only the window blocks it
    with pytest.raises(ValueError):
        [t async for t in core.draft_compression(u2.id, a2.id)]

    # Nothing mutated: same view, still exactly one K, no E appended.
    assert _ids(core) == view_before
    assert sum(1 for n in core.current_view() if n.node_type == "compression") == 1
    assert all(n.node_type != "expand" for n in core.all_nodes())

    # Draining the turn closes the window: the same commit now succeeds.
    async for _ in core.stream(a3):
        pass
    core.end_turn(a3)
    assert core.streaming is False
    core.commit_compression(u2.id, a2.id, "Now allowed.")
    assert sum(1 for n in core.current_view() if n.node_type == "compression") == 2


async def test_unknown_start_id_rejected(repo, test_provider, workspace):
    # C101
    core = _make_core(repo, test_provider, workspace)
    _u1, _a1, _u2, a2 = await _build_line(core)
    before = _ids(core)

    with pytest.raises(ValueError):
        core.commit_compression("no-such-node-id", a2.id, "Bad start.")

    assert _ids(core) == before
    assert not _has_compression(core)


async def test_unknown_end_id_rejected(repo, test_provider, workspace):
    # C102
    core = _make_core(repo, test_provider, workspace)
    _u1, _a1, u2, _a2 = await _build_line(core)
    before = _ids(core)

    with pytest.raises(ValueError):
        core.commit_compression(u2.id, "no-such-node-id", "Bad end.")

    assert _ids(core) == before
    assert not _has_compression(core)


async def test_reversed_order_rejected(repo, test_provider, workspace):
    # C103
    core = _make_core(repo, test_provider, workspace)
    _u1, _a1, u2, a2 = await _build_line(core)
    before = _ids(core)

    with pytest.raises(ValueError):
        core.commit_compression(a2.id, u2.id, "Backwards slice.")

    assert _ids(core) == before
    assert not _has_compression(core)
