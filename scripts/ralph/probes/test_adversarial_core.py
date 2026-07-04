"""Adversarial review probes for the S3 compression core (throwaway)."""

import asyncio

import pytest

from ctx.core.context import build_context
from ctx.core.conversation import ConversationCore
from ctx.core.provider import TestProvider, Usage
from ctx.core.reconstruction import (
    context_at_generation,
    hash_context,
)
from ctx.core.storage import ConversationRepository
from ctx.core.workspace import Workspace


def _core(tmp_path, provider=None, name="a"):
    repo = ConversationRepository(str(tmp_path / f"db-{name}.sqlite"))
    repo.init()
    ws = Workspace(tmp_path / f"ws-{name}")
    ws.ensure()
    return ConversationCore(repo, provider or TestProvider(["ok"]), ws), repo


async def _turn(core, text):
    _u, a = core.submit(text)
    async for _ in core.stream(a):
        pass
    return a


def _oracle(core):
    """Assert the ctx_hash oracle holds for every assistant turn."""
    all_nodes = core.all_nodes()
    for n in all_nodes:
        if n.role == "assistant" and "ctx_hash" in n.meta:
            recon = context_at_generation(all_nodes, n.id)
            got = hash_context(build_context(recon, core.read_file))
            assert got == n.meta["ctx_hash"], f"oracle mismatch for {n.id}"


def test_oracle_compress_expand_recompress(tmp_path):
    async def scenario():
        core, _ = _core(tmp_path)
        a1 = await _turn(core, "one")
        a2 = await _turn(core, "two")
        view = core.current_view()
        # compress the first two turns (user1..assistant1)
        k = core.commit_compression(view[0].id, a1.id, "summary1")
        a3 = await _turn(core, "three")
        core.expand_compression(k.id)
        a4 = await _turn(core, "four")
        # re-compress an overlapping, larger range
        view = core.current_view()
        k2 = core.commit_compression(view[0].id, a2.id, "summary2")
        a5 = await _turn(core, "five")
        _oracle(core)
        # now-view checks: K expanded, K2 active
        ids = [n.id for n in core.current_view()]
        assert k.id not in ids
        assert k2.id in ids
        # a3 saw K, not K2
        recon3 = [n.id for n in context_at_generation(core.all_nodes(), a3.id)]
        assert k.id in recon3 and k2.id not in recon3
        # a4 saw neither (K expanded, K2 not yet)
        recon4 = [n.id for n in context_at_generation(core.all_nodes(), a4.id)]
        assert k.id not in recon4 and k2.id not in recon4
        # a5 saw K2
        recon5 = [n.id for n in context_at_generation(core.all_nodes(), a5.id)]
        assert k2.id in recon5 and k.id not in recon5

    asyncio.run(scenario())


def test_oracle_survives_persist_resume(tmp_path):
    async def scenario():
        core, repo = _core(tmp_path)
        a1 = await _turn(core, "one")
        view = core.current_view()
        core.commit_compression(view[0].id, a1.id, "s")
        await _turn(core, "two")
        conv = core.conversation_id
        # resume into a fresh core sharing the repo
        core2 = ConversationCore(repo, TestProvider(["ok"]), core._workspace)
        core2.resume_conversation(conv)
        _oracle(core2)
        # created_seq continues from loaded max, no collisions
        seqs = [n.created_seq for n in core2.all_nodes()]
        assert len(seqs) == len(set(seqs))
        u, a = core2.submit("three")
        assert u.created_seq == max(seqs) + 1
        assert a.created_seq == max(seqs) + 2

    asyncio.run(scenario())


def test_seq_counts_abandoned_tail(tmp_path):
    async def scenario():
        core, repo = _core(tmp_path)
        a1 = await _turn(core, "one")
        a2 = await _turn(core, "two")
        core.rewind(a1.id)
        # abandoned tail (user2, a2) still counted for next seq
        max_all = max(n.created_seq for n in core.all_nodes())
        u3, _ = core.submit("three")
        assert u3.created_seq == max_all + 1
        # and after resume too
        conv = core.conversation_id
        core.persist()
        core2 = ConversationCore(repo, TestProvider(["ok"]), core._workspace)
        core2.resume_conversation(conv)
        assert a2.id in {n.id for n in core2.all_nodes()}
        max_all2 = max(n.created_seq for n in core2.all_nodes())
        u4, _ = core2.submit("four")
        assert u4.created_seq == max_all2 + 1

    asyncio.run(scenario())


def test_partial_range_after_expand_and_rewind(tmp_path):
    async def scenario():
        core, _ = _core(tmp_path)
        a1 = await _turn(core, "one")
        _ = await _turn(core, "two")
        view = core.current_view()
        u1 = view[0]
        k = core.commit_compression(u1.id, a1.id, "s")
        a3 = await _turn(core, "three")
        core.expand_compression(k.id)
        # rewind INTO the old folded range (allowed: K inactive)
        core.rewind(u1.id)
        a4 = await _turn(core, "four")
        # K's range [u1, a1] is now only partially on the line ({u1}) -> never folds
        ids_now = [n.id for n in core.current_view()]
        assert k.id not in ids_now
        recon4 = [n.id for n in context_at_generation(core.all_nodes(), a4.id)]
        assert k.id not in recon4
        # old turn a3 (on the abandoned tail) still reconstructs WITH K
        recon3 = [n.id for n in context_at_generation(core.all_nodes(), a3.id)]
        assert k.id in recon3
        _oracle(core)

    asyncio.run(scenario())


def test_draft_blank_prompt_falls_back_and_usage_untouched(tmp_path):
    async def scenario():
        captured: list[list[dict]] = []

        class SpyProvider:
            async def stream(self, messages, model, on_usage=None):
                captured.append(messages)
                if on_usage is not None:
                    on_usage(Usage(prompt_tokens=5, completion_tokens=1, total_tokens=6))
                yield "draft"

            async def check_connectivity(self, model):
                return True, "ok"

        core, _ = _core(tmp_path, provider=SpyProvider())
        a1 = await _turn(core, "hello world message")
        gen_before = core.usage_generation
        usage_before = core.last_usage
        cal_before = core.calibration
        view = core.current_view()
        out = []
        async for tok in core.draft_compression(view[0].id, a1.id, prompt="   "):
            out.append(tok)
        assert out == ["draft"]
        # whitespace prompt -> default instruction appended
        from ctx.core.config import DEFAULT_COMPRESSION_PROMPT

        assert captured[-1][-1]["content"] == DEFAULT_COMPRESSION_PROMPT
        # no gauge poisoning
        assert core.usage_generation == gen_before
        assert core.last_usage is usage_before
        assert core.calibration == cal_before
        # nothing committed
        assert all(n.node_type != "compression" for n in core.all_nodes())

    asyncio.run(scenario())


def test_draft_cancellation_mutates_nothing(tmp_path):
    async def scenario():
        started = asyncio.Event()

        class BlockingProvider:
            async def stream(self, messages, model, on_usage=None):
                started.set()
                yield "x"
                await asyncio.Event().wait()  # block forever

            async def check_connectivity(self, model):
                return True, "ok"

        core, _ = _core(tmp_path, provider=BlockingProvider())
        # seed turns with a working provider path: swap provider temporarily
        core._provider = TestProvider(["ok"])
        a1 = await _turn(core, "one")
        core._provider = BlockingProvider()
        view = core.current_view()
        before_ids = {n.id for n in core.all_nodes()}

        async def consume():
            async for _ in core.draft_compression(view[0].id, a1.id):
                pass

        task = asyncio.create_task(consume())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert {n.id for n in core.all_nodes()} == before_ids
        assert not core.streaming

    asyncio.run(scenario())


def test_h2_guards_raise_while_streaming(tmp_path):
    async def scenario():
        gate = asyncio.Event()

        class GatedProvider:
            async def stream(self, messages, model, on_usage=None):
                yield "tok"
                await gate.wait()
                yield "end"

            async def check_connectivity(self, model):
                return True, "ok"

        core, _ = _core(tmp_path, provider=GatedProvider())
        core._provider = TestProvider(["ok"])
        a1 = await _turn(core, "one")
        core._provider = GatedProvider()
        u2, a2 = core.submit("two")

        agen = core.stream(a2)
        first = await agen.__anext__()
        assert first == "tok"
        assert core.streaming
        view_u1 = core.current_view()[0]
        with pytest.raises(ValueError):
            core.commit_compression(view_u1.id, a1.id, "s")
        with pytest.raises(ValueError):
            [x async for x in core.draft_compression(view_u1.id, a1.id)]
        gate.set()
        async for _ in agen:
            pass
        assert not core.streaming
        # after stream ends compression works again
        core.commit_compression(view_u1.id, a1.id, "s")

    asyncio.run(scenario())


def test_migration_backfill_per_conversation_rowid(tmp_path):
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(id),
            role TEXT NOT NULL, content TEXT NOT NULL DEFAULT '',
            node_type TEXT NOT NULL DEFAULT 'message',
            meta TEXT NOT NULL DEFAULT '{}'
        );
        """
    )
    conn.execute("INSERT INTO conversations VALUES ('c1','t','x','x')")
    conn.execute("INSERT INTO conversations VALUES ('c2','t','x','x')")
    # interleave rowids across conversations
    rows = [
        ("n1", "c1"), ("m1", "c2"), ("n2", "c1"), ("m2", "c2"), ("n3", "c1"),
    ]
    for nid, cid in rows:
        conn.execute(
            "INSERT INTO nodes (id, conversation_id, role) VALUES (?, ?, 'user')",
            (nid, cid),
        )
    conn.commit()
    conn.close()

    repo = ConversationRepository(str(db))
    repo.init()
    c1 = {n.id: n for n in repo.load("c1")}
    c2 = {n.id: n for n in repo.load("c2")}
    assert [c1["n1"].created_seq, c1["n2"].created_seq, c1["n3"].created_seq] == [1, 2, 3]
    assert [c2["m1"].created_seq, c2["m2"].created_seq] == [1, 2]
    # prev_id chain backfilled per conversation
    assert c1["n1"].prev_id is None and c1["n2"].prev_id == "n1"
    # idempotent: second init leaves values alone
    repo.init()
    c1b = {n.id: n for n in repo.load("c1")}
    assert c1b["n3"].created_seq == 3

    # resume must continue the counter, not restart it
    ws = Workspace(tmp_path / "wsm")
    ws.ensure()
    core = ConversationCore(repo, TestProvider(["ok"]), ws)
    core.resume_conversation("c1")
    u, _a = core.submit("new")
    assert u.created_seq == 4


def test_rewind_rejects_offline_and_folded(tmp_path):
    async def scenario():
        core, _ = _core(tmp_path)
        a1 = await _turn(core, "one")
        _ = await _turn(core, "two")
        view = core.current_view()
        k = core.commit_compression(view[0].id, a1.id, "s")
        with pytest.raises(ValueError):
            core.rewind(k.id)  # off-line K
        with pytest.raises(ValueError):
            core.rewind(a1.id)  # folded child
        _ = [n for n in core.all_nodes() if n.node_type == "expand"]
        core.expand_compression(k.id)
        e = [n for n in core.all_nodes() if n.node_type == "expand"][0]
        with pytest.raises(ValueError):
            core.rewind(e.id)  # off-line E
        core.rewind(a1.id)  # unfolded now: allowed
        assert core.current_view()[-1].id == a1.id

    asyncio.run(scenario())


def test_now_view_multiple_ks_and_maximal_runs(tmp_path):
    async def scenario():
        core, _ = _core(tmp_path)
        a1 = await _turn(core, "one")
        a2 = await _turn(core, "two")
        a3 = await _turn(core, "three")
        view = core.current_view()
        # K1 folds turn1 (u1,a1), K2 folds turn3 (u3,a3) -> [K1, u2, a2, K2]
        u1, u2, u3 = view[0], view[2], view[4]
        k1 = core.commit_compression(u1.id, a1.id, "s1")
        k2 = core.commit_compression(u3.id, a3.id, "s2")
        ids = [n.id for n in core.current_view()]
        assert ids == [k1.id, u2.id, a2.id, k2.id]
        # each K appears exactly once (maximal-run collapse)
        assert ids.count(k1.id) == 1 and ids.count(k2.id) == 1
        # expand K1 -> children back in place, K2 still folded
        core.expand_compression(k1.id)
        ids = [n.id for n in core.current_view()]
        assert ids == [u1.id, a1.id, u2.id, a2.id, k2.id]
        # re-expanding raises
        with pytest.raises(ValueError):
            core.expand_compression(k1.id)

    asyncio.run(scenario())


def test_e_never_renders_and_k_renders_wrapped(tmp_path):
    async def scenario():
        core, _ = _core(tmp_path)
        a1 = await _turn(core, "one")
        view = core.current_view()
        k = core.commit_compression(view[0].id, a1.id, "the summary")
        msgs = build_context(core.current_view(), core.read_file)
        joined = "\n".join(m["content"] for m in msgs)
        assert "<conversation_summary>\nthe summary\n</conversation_summary>" in joined
        core.expand_compression(k.id)
        _ = await _turn(core, "two")
        msgs = build_context(core.current_view(), core.read_file)
        assert "conversation_summary" not in "".join(m["content"] for m in msgs)

    asyncio.run(scenario())


def test_resume_prefers_stored_title(tmp_path):
    async def scenario():
        core, repo = _core(tmp_path)
        a1 = await _turn(core, "the original first message that titles it")
        conv = core.conversation_id
        title = core.conversation_title
        # fold EVERY user turn into a K, persist
        view = core.current_view()
        core.commit_compression(view[0].id, a1.id, "s")
        core2 = ConversationCore(repo, TestProvider(["ok"]), core._workspace)
        core2.resume_conversation(conv)
        assert core2.conversation_title == title

    asyncio.run(scenario())


def test_folded_tip_append_and_oracle(tmp_path):
    async def scenario():
        core, _ = _core(tmp_path)
        _ = await _turn(core, "one")
        a2 = await _turn(core, "two")
        view = core.current_view()
        u2 = view[2]
        k = core.commit_compression(u2.id, a2.id, "s")  # range ends at the tip
        assert [n.id for n in core.current_view()][-1] == k.id
        a3 = await _turn(core, "three")
        ids = [n.id for n in core.current_view()]
        assert k.id in ids and ids[-1] == a3.id
        # K appears once, folded children absent
        assert u2.id not in ids and a2.id not in ids
        _oracle(core)

    asyncio.run(scenario())


def test_dangling_active_leaf_fallback_can_put_k_on_tip(tmp_path):
    import sqlite3

    async def scenario():
        core, repo = _core(tmp_path)
        a1 = await _turn(core, "one")
        view = core.current_view()
        core.commit_compression(view[0].id, a1.id, "s")
        conv = core.conversation_id
        db = tmp_path / "db-a.sqlite"
        conn = sqlite3.connect(db)
        conn.execute(
            "UPDATE conversations SET active_leaf_id = 'nope' WHERE id = ?", (conv,)
        )
        conn.commit()
        conn.close()
        core2 = ConversationCore(repo, TestProvider(["ok"]), core._workspace)
        core2.resume_conversation(conv)
        tip = core2._active_leaf_id
        tip_node = core2._graph[tip]
        print("fallback tip node_type:", tip_node.node_type)
        assert tip_node.node_type == "compression"  # K became the tip

    asyncio.run(scenario())
