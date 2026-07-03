"""Behavioral tests for ConversationCore.draft_compression (contract C121-C133).

Code-blind: assertions trace to tests/specs/draft_compression.md, not to any
implementation. asyncio_mode=auto -> async def test_* needs no decorator.

Assumption (flagged in the spec): the recording/blocking providers assume the core
invokes a streaming method (aliased to several likely names) handed a list[dict] of
{"role", "content"} messages. C121/C122 avoid this by using the real test_provider.
"""

import asyncio

import pytest

from ctx.core.conversation import DEFAULT_COMPRESSION_PROMPT, ConversationCore
from ctx.core.provider import Usage


async def _build_line(core):
    """Build canonical view [u1, a1, u2, a2] with tip = a2."""
    u1, a1 = core.submit("first user message")
    async for _ in core.stream(a1):
        pass
    u2, a2 = core.submit("second user message")
    async for _ in core.stream(a2):
        pass
    return u1, a1, u2, a2


def _view_ids(core):
    return [n.id for n in core.current_view()]


class RecordingProvider:
    """Captures the messages it is handed and streams canned tokens.

    Aliases several plausible streaming-method names to one implementation so the
    test is robust to the exact Protocol method name (see spec ambiguity note).
    """

    def __init__(self, tokens):
        self._tokens = list(tokens)
        self.called = False
        self.captured = None  # the messages list, or None if never invoked

    async def _emit(self, *args, **kwargs):
        self.called = True
        msgs = kwargs.get("messages")
        if msgs is None:
            for a in args:
                if isinstance(a, list) and a and isinstance(a[0], dict):
                    msgs = a
                    break
        self.captured = msgs
        for tok in self._tokens:
            yield tok

    stream = generate = complete = astream = _emit


class BlockingProvider:
    """Yields one token then blocks until released; keeps core.streaming True."""

    def __init__(self):
        self._release = asyncio.Event()

    def release(self):
        self._release.set()

    async def _emit(self, *args, **kwargs):
        yield "thinking"
        await self._release.wait()
        yield "done"

    stream = generate = complete = astream = _emit


# C121 - yields exactly the provider's tokens, in order
async def test_yields_provider_tokens_in_order(repo, workspace, test_provider):
    core = ConversationCore(repo, test_provider(["ok"]), workspace)
    core.setup()
    _, _, u2, a2 = await _build_line(core)

    tokens = ["Here ", "is ", "the ", "summary."]
    core._provider = test_provider(tokens)
    out = [t async for t in core.draft_compression(u2.id, a2.id)]
    assert out == tokens


# C122 - gauge is never touched, even when the provider reports Usage
async def test_gauge_untouched_even_with_usage(repo, workspace, test_provider):
    core = ConversationCore(repo, test_provider(["ok"]), workspace)
    core.setup()
    _, _, u2, a2 = await _build_line(core)

    before_gen = core.usage_generation
    before_cal = core.calibration
    before_last = core.last_usage

    core._provider = test_provider(
        ["draft ", "text"],
        usage=Usage(prompt_tokens=50, completion_tokens=10, total_tokens=60),
    )
    async for _ in core.draft_compression(u2.id, a2.id):
        pass

    assert core.usage_generation == before_gen
    assert core.calibration == before_cal
    assert core.last_usage == before_last


# C123 - a custom prompt reaches the provider's final user message
async def test_custom_prompt_reaches_provider(repo, workspace, test_provider):
    core = ConversationCore(repo, test_provider(["ok"]), workspace)
    core.setup()
    _, _, u2, a2 = await _build_line(core)

    custom = "Summarize focusing on the migration timeline and blockers."
    rec = RecordingProvider(["s1", "s2"])
    core._provider = rec
    async for _ in core.draft_compression(u2.id, a2.id, prompt=custom):
        pass

    assert rec.captured is not None
    assert any(
        m.get("role") == "user" and custom in m.get("content", "")
        for m in rec.captured
    )


# C124 - omitted prompt falls back to DEFAULT_COMPRESSION_PROMPT
async def test_default_prompt_when_none(repo, workspace, test_provider):
    core = ConversationCore(repo, test_provider(["ok"]), workspace)
    core.setup()
    _, _, u2, a2 = await _build_line(core)

    rec = RecordingProvider(["s1"])
    core._provider = rec
    async for _ in core.draft_compression(u2.id, a2.id):
        pass

    assert rec.captured is not None
    assert any(
        m.get("role") == "user" and DEFAULT_COMPRESSION_PROMPT in m.get("content", "")
        for m in rec.captured
    )


# C124b (13i) - a blank/whitespace-only prompt also falls back to the default.
# Documented addition (not code-blind): an empty user message is not a real
# instruction and several APIs reject it, so the UI's verbatim editor.prompt must
# not reach the provider blank.
async def test_blank_prompt_falls_back_to_default(repo, workspace, test_provider):
    core = ConversationCore(repo, test_provider(["ok"]), workspace)
    core.setup()
    _, _, u2, a2 = await _build_line(core)

    rec = RecordingProvider(["s1"])
    core._provider = rec
    async for _ in core.draft_compression(u2.id, a2.id, prompt="   "):
        pass

    assert rec.captured is not None
    # The whitespace prompt never reaches the provider as the final user message;
    # the default instruction does.
    assert any(
        m.get("role") == "user" and DEFAULT_COMPRESSION_PROMPT in m.get("content", "")
        for m in rec.captured
    )
    assert not any(
        m.get("role") == "user" and m.get("content", "") == "   " for m in rec.captured
    )


# C125 - the range is rendered (model-facing content reaches the provider)
async def test_range_content_rendered_to_provider(repo, workspace, test_provider):
    core = ConversationCore(repo, test_provider(["ok"]), workspace)
    core.setup()
    _, _, u2, a2 = await _build_line(core)

    rec = RecordingProvider(["s1"])
    core._provider = rec
    async for _ in core.draft_compression(u2.id, a2.id):
        pass

    assert rec.captured is not None
    joined = " ".join(
        m.get("content", "") for m in rec.captured if isinstance(m.get("content"), str)
    )
    # the verbatim conversation text of the in-range node must be fed to the model
    assert "second user message" in joined


# C126 - unknown start_id raises before any provider call
async def test_unknown_start_raises_before_provider(repo, workspace, test_provider):
    core = ConversationCore(repo, test_provider(["ok"]), workspace)
    core.setup()
    _, _, _, a2 = await _build_line(core)

    rec = RecordingProvider(["s1"])
    core._provider = rec
    with pytest.raises(ValueError):
        async for _ in core.draft_compression("nonexistent-start", a2.id):
            pass
    assert rec.called is False
    assert rec.captured is None


# C127 - unknown end_id raises before any provider call
async def test_unknown_end_raises_before_provider(repo, workspace, test_provider):
    core = ConversationCore(repo, test_provider(["ok"]), workspace)
    core.setup()
    _, _, u2, _ = await _build_line(core)

    rec = RecordingProvider(["s1"])
    core._provider = rec
    with pytest.raises(ValueError):
        async for _ in core.draft_compression(u2.id, "nonexistent-end"):
            pass
    assert rec.called is False
    assert rec.captured is None


# C128 - reversed range (start after end) raises before any provider call
async def test_reversed_range_raises_before_provider(repo, workspace, test_provider):
    core = ConversationCore(repo, test_provider(["ok"]), workspace)
    core.setup()
    _, _, u2, a2 = await _build_line(core)

    rec = RecordingProvider(["s1"])
    core._provider = rec
    with pytest.raises(ValueError):
        async for _ in core.draft_compression(a2.id, u2.id):
            pass
    assert rec.called is False
    assert rec.captured is None


# C129 - a middle (non-tip) range now drafts (the 3a tip guard was deleted in
# task 22): the provider is called with the rendered range and its tokens stream.
async def test_middle_range_drafts_and_calls_provider(repo, workspace, test_provider):
    core = ConversationCore(repo, test_provider(["ok"]), workspace)
    core.setup()
    u1, a1, _, _ = await _build_line(core)

    rec = RecordingProvider(["s1"])
    core._provider = rec
    tokens = [t async for t in core.draft_compression(u1.id, a1.id)]

    assert tokens == ["s1"]
    assert rec.called is True
    assert rec.captured is not None
    # The final message carries the instruction (default, no prompt passed).
    assert rec.captured[-1]["content"] == DEFAULT_COMPRESSION_PROMPT


# C130 - streaming/H2 guard: drafting during a live turn raises
async def test_streaming_guard_rejects_during_live_stream(repo, workspace):
    blocker = BlockingProvider()
    core = ConversationCore(repo, blocker, workspace)
    core.setup()
    u1, a1 = core.submit("kick off a live turn")

    agen = core.stream(a1)
    await agen.__anext__()  # advance one token; turn is now live
    try:
        assert core.streaming is True
        with pytest.raises(ValueError):
            async for _ in core.draft_compression(u1.id, a1.id):
                pass
    finally:
        blocker.release()
        await agen.aclose()


# C131 - a full draft mutates no conversation state
async def test_full_draft_mutates_no_state(repo, workspace, test_provider):
    core = ConversationCore(repo, test_provider(["ok"]), workspace)
    core.setup()
    _, _, u2, a2 = await _build_line(core)

    before = _view_ids(core)
    core._provider = test_provider(["draft ", "text"])
    async for _ in core.draft_compression(u2.id, a2.id):
        pass

    assert _view_ids(core) == before  # same ids, order and length -> no node added


# C132 - a cancelled draft leaves the graph exactly as it was
async def test_cancelled_draft_leaves_graph_unchanged(repo, workspace, test_provider):
    core = ConversationCore(repo, test_provider(["ok"]), workspace)
    core.setup()
    _, _, u2, a2 = await _build_line(core)

    before = _view_ids(core)
    core._provider = test_provider(["one", "two", "three"])
    agen = core.draft_compression(u2.id, a2.id)
    await agen.__anext__()  # start it, consume one token
    await agen.aclose()  # cancel mid-stream

    assert _view_ids(core) == before
