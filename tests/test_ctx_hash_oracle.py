"""The ctx_hash reconstruction oracle (ADR-0016 A#3 §4, PRD Sprint 3 task 17).

This is a *differential* oracle, deliberately authored against the public
core API (not the blind test-spec flow): it cross-checks two independent
derivations of a turn's context, so it cannot mirror the implementation of
either.

For every assistant turn ``T`` produced while driving a real
``ConversationCore`` through compress / expand / re-compress sequences, the
invariant is:

    hash_context(build_context(context_at_generation(all, T.id), read_file))
        == T.meta["ctx_hash"]

i.e. the context reconstructed *as of* T's generation moment must hash to the
value ``stream`` stamped on T at that moment. A turn with no
compression/expand events between it and now trivially matches (both sides are
the plain prefix). The stamp is written once in ``stream`` and is immutable
after (append-only graph).
"""

from ctx.core.context import build_context
from ctx.core.conversation import ConversationCore
from ctx.core.reconstruction import context_at_generation, has_drift, hash_context


def _make_core(repo, test_provider, workspace, tokens=None):
    core = ConversationCore(repo, test_provider(tokens or ["ok"]), workspace)
    core.setup()
    return core


async def _core_turn(core, prompt):
    """Drive one full user->assistant turn; return the assistant node."""
    _user, assistant = core.submit(prompt)
    async for _ in core.stream(assistant):
        pass
    return assistant


def _assistant_turns(core):
    return [n for n in core._all_nodes() if n.role == "assistant"]


def _check_oracle(core):
    """Assert the ctx_hash invariant holds for every assistant turn."""
    all_nodes = core._all_nodes()
    read_file = core.read_file
    turns = _assistant_turns(core)
    assert turns, "expected at least one assistant turn"
    for t in turns:
        assert "ctx_hash" in t.meta, f"turn {t.id} has no ctx_hash stamp"
        recon = context_at_generation(all_nodes, t.id)
        expected = hash_context(build_context(recon, read_file))
        assert t.meta["ctx_hash"] == expected, (
            f"ctx_hash mismatch for turn {t.id}: "
            f"stamped {t.meta['ctx_hash']!r} != reconstructed {expected!r}"
        )


# ---------------------------------------------------------------------------
# Baseline: no compression events at all
# ---------------------------------------------------------------------------

async def test_oracle_holds_for_plain_turns(repo, test_provider, workspace):
    core = _make_core(repo, test_provider, workspace)
    await _core_turn(core, "one")
    await _core_turn(core, "two")
    await _core_turn(core, "three")
    _check_oracle(core)


# ---------------------------------------------------------------------------
# A single stamp is immutable: it does not change under later events
# ---------------------------------------------------------------------------

async def test_stamp_is_immutable_across_later_compression(
    repo, test_provider, workspace
):
    core = _make_core(repo, test_provider, workspace)
    a1 = await _core_turn(core, "one")
    before = a1.meta["ctx_hash"]
    a2 = await _core_turn(core, "two")
    core.commit_compression(a1.prev_id, a2.id, "summary")
    # a1's stamp was written at its own generation moment and never rewritten.
    assert a1.meta["ctx_hash"] == before
    _check_oracle(core)


# ---------------------------------------------------------------------------
# Full scripted sequence: turns -> tip compress -> turns -> expand -> turns
#                         -> re-compress. Oracle must hold at every stage.
# ---------------------------------------------------------------------------

async def test_oracle_holds_through_compress_expand_recompress(
    repo, test_provider, workspace
):
    core = _make_core(repo, test_provider, workspace)

    # 1. a few plain turns
    a1 = await _core_turn(core, "capital of France?")
    a2 = await _core_turn(core, "its population?")
    _check_oracle(core)

    # 2. compress the tip range [u2, a2] into K
    k = core.commit_compression(a2.prev_id, a2.id, "France facts")
    assert any(n.node_type == "compression" for n in core.current_view())
    _check_oracle(core)

    # 3. more turns generated on top of the folded view (they saw K)
    a3 = await _core_turn(core, "capital of Spain?")
    _check_oracle(core)

    # 4. expand K (non-destructive undo via an E event)
    core.expand_compression(k.id)
    assert not any(n.node_type == "compression" for n in core.current_view())
    _check_oracle(core)

    # 5. more turns after expand (they see the originals verbatim again)
    a4 = await _core_turn(core, "its population?")
    _check_oracle(core)

    # 6. re-compress a fresh range into K'
    core.commit_compression(a4.prev_id, a4.id, "Spain facts")
    _check_oracle(core)

    # sanity: we really exercised several distinct turns
    assert len({a1.id, a2.id, a3.id, a4.id}) == 4


# ---------------------------------------------------------------------------
# Turns generated AFTER a compression must reconstruct to the folded prefix,
# and turns generated BEFORE it must still reconstruct to the verbatim prefix.
# ---------------------------------------------------------------------------

async def test_pre_and_post_compression_turns_both_verify(
    repo, test_provider, workspace
):
    core = _make_core(repo, test_provider, workspace)
    a1 = await _core_turn(core, "one")
    a2 = await _core_turn(core, "two")
    core.commit_compression(a2.prev_id, a2.id, "one+two")
    a3 = await _core_turn(core, "three")  # this turn saw K in its context

    all_nodes = core._all_nodes()
    read_file = core.read_file

    # a1 (pre-compression) reconstructs to a verbatim prefix (no K folded in).
    recon1 = context_at_generation(all_nodes, a1.id)
    assert not any(n.node_type == "compression" for n in recon1)
    assert hash_context(build_context(recon1, read_file)) == a1.meta["ctx_hash"]

    # a3 (post-compression) reconstructs with K present.
    recon3 = context_at_generation(all_nodes, a3.id)
    assert any(n.node_type == "compression" for n in recon3)
    assert hash_context(build_context(recon3, read_file)) == a3.meta["ctx_hash"]


# ---------------------------------------------------------------------------
# Middle compression (task 22 enabled it; task 29 extends the oracle to it).
#
# The tip-compression cases above are *non-discriminating* against a bug where
# ``context_at_generation`` returns the now-prefix: for every checked turn there,
# its gen-view already equals its now-view (a tip K folds only material at or
# after the pre-K turns, never inside an earlier checked turn's strict-ancestor
# prefix). A MIDDLE compression is the discriminating case: K folds a range that
# lies strictly inside a *later already-generated* turn's ancestor prefix, so
# that turn's gen-view (verbatim, K did not exist yet) differs from its now-view
# (folded). Only a correct as-of reconstruction hashes back to the stamp.
# ---------------------------------------------------------------------------

async def test_oracle_holds_for_middle_compression(repo, test_provider, workspace):
    core = _make_core(repo, test_provider, workspace)
    a1 = await _core_turn(core, "one")
    a2 = await _core_turn(core, "two")
    # Compress the MIDDLE range [u1, a1] — not the tip a2 — into K.
    core.commit_compression(a1.prev_id, a1.id, "one summary")
    await _core_turn(core, "three")  # generated on top of the folded view
    _check_oracle(core)

    # a2 is the discriminating turn: it was generated verbatim ([u1,a1,u2]) before
    # K existed, yet its now-view folds [u1,a1] into K ([K,u2]). gen-view != now.
    all_nodes = core._all_nodes()
    assert has_drift(all_nodes, a2.id)
    recon2 = context_at_generation(all_nodes, a2.id)
    assert not any(n.node_type == "compression" for n in recon2)


async def test_oracle_holds_through_middle_expand_recompress(
    repo, test_provider, workspace
):
    core = _make_core(repo, test_provider, workspace)
    a1 = await _core_turn(core, "one")
    a2 = await _core_turn(core, "two")

    # 1. compress the middle range [u1, a1] into K
    k = core.commit_compression(a1.prev_id, a1.id, "one summary")
    assert any(n.node_type == "compression" for n in core.current_view())
    _check_oracle(core)

    # 2. expand K (non-destructive undo via an E event) — view is verbatim again
    core.expand_compression(k.id)
    assert not any(n.node_type == "compression" for n in core.current_view())
    _check_oracle(core)

    # 3. re-compress the same middle range into a fresh K'
    core.commit_compression(a1.prev_id, a1.id, "one summary v2")
    a3 = await _core_turn(core, "three")
    _check_oracle(core)

    # a2 still discriminates after the expand->re-compress churn: gen-view verbatim,
    # now-view folded under K' (K is expanded, K' applies).
    all_nodes = core._all_nodes()
    assert has_drift(all_nodes, a2.id)
    assert len({a1.id, a2.id, a3.id}) == 3
