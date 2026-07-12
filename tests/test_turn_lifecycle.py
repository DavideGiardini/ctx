# Contract: tests/specs/conversation.md — "Turn lifecycle — end_turn single door (ctx0 Phase 1)"
"""Blind-authored tests for the turn lifecycle (C100–C112).

Every expected value traces to the adjudicated contract, never to the
implementation. Persistence is observed exclusively through ``repo.load``.
"""

import pytest
from conftest import ErroringProvider

from ctx.core.conversation import ConversationCore


def _by_id(nodes, node_id):
    return next(n for n in nodes if n.id == node_id)


async def _run_full_turn(core, text):
    """Submit, drain the stream to exhaustion, and end the turn cleanly."""
    user, assistant = core.submit(text)
    async for _ in core.stream(assistant):
        pass
    core.end_turn(assistant)
    return user, assistant


async def test_submit_raises_flag_and_end_turn_lowers_it(repo, workspace, test_provider):
    # C100
    core = ConversationCore(repo, test_provider(["Hi", " there"]), workspace)

    user, assistant = core.submit("Say hello to the team")

    assert user.role == "user"
    assert assistant.role == "assistant"
    assert core.streaming is True

    core.end_turn(assistant)
    assert core.streaming is False


async def test_second_submit_mid_turn_refused_side_effect_free(repo, workspace, test_provider):
    # C101
    core = ConversationCore(repo, test_provider(["Sure,", " here goes"]), workspace)
    _, assistant = core.submit("Explain WAL mode in SQLite")
    before_ids = [n.id for n in repo.load(core.conversation_id)]

    with pytest.raises(ValueError):
        core.submit("Actually, explain rollback journaling instead")

    assert core.streaming is True
    assert [n.id for n in repo.load(core.conversation_id)] == before_ids

    core.end_turn(assistant)
    assert core.streaming is False


async def test_clean_finish_persists_full_content_without_marks(repo, workspace, test_provider):
    # C102
    core = ConversationCore(repo, test_provider(["Hello", " world"]), workspace)
    _, assistant = core.submit("Greet the world")

    async for _ in core.stream(assistant):
        pass
    core.end_turn(assistant)

    assert core.streaming is False
    reloaded = _by_id(repo.load(core.conversation_id), assistant.id)
    assert reloaded.content == "Hello world"
    assert "interrupted" not in reloaded.meta
    assert "error" not in reloaded.meta


async def test_cancel_ending_persists_partial_content_with_interrupted_mark(
    repo, workspace, test_provider
):
    # C103
    core = ConversationCore(
        repo, test_provider(["The capital of France", " is Paris."]), workspace
    )
    _, assistant = core.submit("What is the capital of France?")

    agen = core.stream(assistant)
    first_token = await anext(agen)
    await agen.aclose()
    core.end_turn(assistant, cancelled=True)

    assert core.streaming is False
    reloaded = _by_id(repo.load(core.conversation_id), assistant.id)
    assert reloaded.meta["interrupted"] is True
    assert reloaded.content == first_token


async def test_error_ending_persists_error_mark(repo, workspace):
    # C104
    core = ConversationCore(repo, ErroringProvider(), workspace)
    _, assistant = core.submit("Fetch the latest deployment metrics")

    with pytest.raises(RuntimeError, match="boom"):
        async for _ in core.stream(assistant):
            pass
    core.end_turn(assistant, error="boom")

    assert core.streaming is False
    reloaded = _by_id(repo.load(core.conversation_id), assistant.id)
    assert reloaded.meta["error"] == "boom"


async def test_cancelled_and_error_together_rejected_without_side_effects(
    repo, workspace, test_provider
):
    # C105
    core = ConversationCore(repo, test_provider(["Disk usage is 42%."]), workspace)
    _, assistant = core.submit("Check disk usage on the build server")

    with pytest.raises(ValueError):
        core.end_turn(assistant, cancelled=True, error="boom")

    assert core.streaming is True
    for node in repo.load(core.conversation_id):
        assert "interrupted" not in node.meta
        assert "error" not in node.meta

    core.end_turn(assistant)
    assert core.streaming is False


async def test_stream_exhaustion_does_not_lower_flag(repo, workspace, test_provider):
    # C106
    core = ConversationCore(repo, test_provider(["All", " done."]), workspace)
    _, assistant = core.submit("Wrap up the report")

    async for _ in core.stream(assistant):
        pass

    assert core.streaming is True


async def test_stream_does_not_persist_assistant_node(repo, workspace, test_provider):
    # C107
    core = ConversationCore(repo, test_provider(["Reviewing", " now."]), workspace)
    user, assistant = core.submit("Review the open pull requests")

    async for _ in core.stream(assistant):
        pass

    stored = repo.load(core.conversation_id)
    stored_user = _by_id(stored, user.id)
    assert stored_user.content == "Review the open pull requests"
    assert all(n.id != assistant.id for n in stored)


async def test_end_turn_idempotent_after_clean_ending(repo, workspace, test_provider):
    # C108
    core = ConversationCore(repo, test_provider(["Consider it", " done."]), workspace)
    _, assistant = await _run_full_turn(core, "Archive last quarter's tickets")

    core.end_turn(assistant)  # second ending on a lowered flag: must not raise

    assert core.streaming is False


async def test_conversation_switch_mid_turn_resets_flag(repo, workspace, test_provider):
    # C109
    core = ConversationCore(repo, test_provider(["Noted."]), workspace)
    await _run_full_turn(core, "Log today's standup summary")
    existing_id = core.conversation_id

    core.new_conversation()
    core.submit("Plan the next sprint")
    assert core.streaming is True
    core.new_conversation()
    assert core.streaming is False

    core.submit("Draft the sprint goals")
    assert core.streaming is True
    core.resume_conversation(existing_id)
    assert core.streaming is False


async def test_stale_ending_after_new_conversation_is_noop(repo, workspace, test_provider):
    # C110
    core = ConversationCore(repo, test_provider(["Working on", " it..."]), workspace)
    _, old_assistant = core.submit("Summarize the meeting notes")
    a_id = core.conversation_id

    core.new_conversation()
    core.end_turn(old_assistant, cancelled=True)  # late ending: must not raise

    assert core.streaming is False
    for node in repo.load(a_id):
        assert "interrupted" not in node.meta


async def test_stale_ending_after_resume_leaves_both_conversations_unmarked(
    repo, workspace, test_provider
):
    # C111
    core = ConversationCore(repo, test_provider(["Done."]), workspace)
    await _run_full_turn(core, "Draft the release announcement")  # conversation B
    b_id = core.conversation_id

    core.new_conversation()
    _, old_assistant = core.submit("Start triaging the bug backlog")  # conversation A
    a_id = core.conversation_id

    core.resume_conversation(b_id)
    b_before = [(n.id, n.content, dict(n.meta)) for n in repo.load(b_id)]

    core.end_turn(old_assistant, error="provider timed out")  # late ending: must not raise

    b_after = [(n.id, n.content, dict(n.meta)) for n in repo.load(b_id)]
    assert b_after == b_before
    for node in repo.load(a_id):
        assert "error" not in node.meta


async def test_cancel_ending_releases_slot_for_next_submit(repo, workspace, test_provider):
    # C112
    core = ConversationCore(
        repo, test_provider(["Partial answer", " continues here"]), workspace
    )
    user1, assistant1 = core.submit("List the open action items")
    agen = core.stream(assistant1)
    await anext(agen)
    await agen.aclose()
    core.end_turn(assistant1, cancelled=True)

    user2, assistant2 = core.submit("List them again, sorted by owner")

    assert core.streaming is True
    assert user2.id not in {user1.id, assistant1.id}
    assert assistant2.id not in {user1.id, assistant1.id}
