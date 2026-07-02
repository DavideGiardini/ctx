"""Behavioral tests for ConversationCore.commit_compression + current_view folding.

Contract: tests/specs/commit_compression.md (C91–C103). Written code-blind from
intent; assertions trace to contract Expect clauses, never to assumed internals.
"""

import asyncio

import pytest

from ctx.core.conversation import ConversationCore

# --- helper provider for the streaming guard (C100) -------------------------

class BlockingProvider:
    """Yields `before` tokens, then blocks on an unset gate so the stream stays
    live (core.streaming True) while we probe commit_compression."""

    def __init__(self, before, gate):
        self._before = before
        self._gate = gate

    async def stream(self, messages, model, on_usage=None):
        for t in self._before:
            yield t
        await self._gate.wait()
        yield "AFTER"  # never reached

    async def check_connectivity(self, model):
        return (True, "ok")


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
    u2, a2 = core.submit("Now compare that with an open-addressing scheme.")
    async for _ in core.stream(a2):
        pass
    return u1, a1, u2, a2


def _make_core(repo, test_provider, workspace, tokens=None):
    core = ConversationCore(repo, test_provider(tokens or ["ok"]), workspace)
    core.setup()
    return core


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

async def test_tip_guard_rejects_mid_range(repo, test_provider, workspace):
    # C98
    core = _make_core(repo, test_provider, workspace)
    u1, a1, u2, a2 = await _build_line(core)
    before = _ids(core)

    with pytest.raises(ValueError):
        core.commit_compression(u1.id, a1.id, "Should not apply.")

    assert _ids(core) == before
    assert not _has_compression(core)


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
