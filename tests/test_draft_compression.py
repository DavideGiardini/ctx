"""Code-blind tests for ConversationCore.draft_compression.

Written without ever reading the implementation; every expected value traces to
tests/specs/draft_compression.md (contract clauses C121-C131), which derives purely
from ADR-0016 Amendment #6. Do NOT add assertions describing what the code happens to
do — only what the contract says it must do.
"""

import asyncio

import pytest

from ctx.core.context import CLOSE_COMPRESS_MARKER, OPEN_COMPRESS_MARKER
from ctx.core.conversation import DEFAULT_COMPRESSION_PROMPT, ConversationCore
from ctx.core.provider import Usage

# --- test doubles -----------------------------------------------------------

class RecordingProvider:
    """Captures the exact messages list it is handed and streams canned tokens."""

    def __init__(self, tokens):
        self._tokens = list(tokens)
        self.called = False
        self.captured = None  # the messages list, or None if never invoked

    async def stream(self, messages, *args, **kwargs):
        self.called = True
        self.captured = messages
        for tok in self._tokens:
            yield tok


class BlockingProvider:
    """Keeps core.streaming True until released (for the H2 guard test)."""

    def __init__(self):
        self._release = asyncio.Event()

    def release(self):
        self._release.set()

    async def stream(self, *args, **kwargs):
        yield "thinking"
        await self._release.wait()
        yield "done"


# --- helpers ----------------------------------------------------------------

def _core(repo, workspace, provider):
    core = ConversationCore(repo, provider, workspace)
    core.setup()
    return core


async def _build_line(core):
    """Build the canonical line [u1, a1, u2, a2] with tip = a2."""
    u1, a1 = core.submit("first user message")
    async for _ in core.stream(a1):
        pass
    u2, a2 = core.submit("second user message")
    async for _ in core.stream(a2):
        pass
    return u1, a1, u2, a2


def _role(msg):
    return msg["role"] if isinstance(msg, dict) else msg.role


def _content(msg):
    return msg["content"] if isinstance(msg, dict) else msg.content


async def _drain(agen):
    return [tok async for tok in agen]


# --- tests ------------------------------------------------------------------

async def test_two_messages_system_then_user_with_default_system(repo, workspace, test_provider):
    # C121 + C123: exactly [system, user], and a None / whitespace-only prompt
    # falls back to DEFAULT_COMPRESSION_PROMPT.
    core = _core(repo, workspace, test_provider(["ok"]))
    u1, a1, u2, a2 = await _build_line(core)

    for blank_prompt in (None, "   "):
        rec = RecordingProvider(["draft"])
        core._provider = rec
        await _drain(core.draft_compression(u2.id, u2.id, prompt=blank_prompt))

        assert rec.called is True
        assert len(rec.captured) == 2
        assert [_role(m) for m in rec.captured] == ["system", "user"]
        assert _content(rec.captured[0]) == DEFAULT_COMPRESSION_PROMPT


async def test_custom_prompt_becomes_system_message(repo, workspace, test_provider):
    # C122
    core = _core(repo, workspace, test_provider(["ok"]))
    u1, a1, u2, a2 = await _build_line(core)

    rec = RecordingProvider(["draft"])
    core._provider = rec
    custom = "Please summarize this range concisely."
    await _drain(core.draft_compression(u2.id, u2.id, prompt=custom))

    assert [_role(m) for m in rec.captured] == ["system", "user"]
    assert _content(rec.captured[0]) == custom


async def test_user_message_is_full_transcript_with_markers(repo, workspace, test_provider):
    # C124: whole active line rendered; middle range marked; before-context present.
    core = _core(repo, workspace, test_provider(["ok"]))
    u1, a1, u2, a2 = await _build_line(core)

    rec = RecordingProvider(["draft"])
    core._provider = rec
    # Middle range: just u2, so u1/a1 are before-context and a2 is after-context.
    await _drain(core.draft_compression(u2.id, u2.id))

    user_text = _content(rec.captured[1])
    assert OPEN_COMPRESS_MARKER in user_text
    assert CLOSE_COMPRESS_MARKER in user_text

    open_i = user_text.index(OPEN_COMPRESS_MARKER)
    close_i = user_text.index(CLOSE_COMPRESS_MARKER)
    marked = user_text[open_i:close_i]

    # The marked node's verbatim text lies between the markers.
    assert "second user message" in marked
    # An out-of-range (before-context) node's text also appears, before the open marker.
    assert "first user message" in user_text
    assert user_text.index("first user message") < open_i


async def test_empty_span_refused_before_provider_call(repo, workspace, test_provider):
    # C125: a fresh un-streamed assistant node (content "") is an empty span.
    core = _core(repo, workspace, test_provider(["ok"]))
    await _build_line(core)

    rec = RecordingProvider(["draft"])
    core._provider = rec
    u3, a3 = core.submit("third user message")  # a3 not streamed -> content ""
    assert core.current_view()[-1].id == a3.id

    with pytest.raises(ValueError):
        await _drain(core.draft_compression(a3.id, a3.id))
    assert rec.called is False


async def test_yields_provider_tokens_in_order(repo, workspace, test_provider):
    # C126
    core = _core(repo, workspace, test_provider(["ok"]))
    u1, a1, u2, a2 = await _build_line(core)

    core._provider = test_provider(["Sum", "mary", " text"])
    out = await _drain(core.draft_compression(u2.id, u2.id))
    assert out == ["Sum", "mary", " text"]


async def test_gauge_untouched_even_with_reported_usage(repo, workspace, test_provider):
    # C127
    core = _core(repo, workspace, test_provider(["ok"]))
    u1, a1, u2, a2 = await _build_line(core)

    before = (core.last_usage, core.calibration, core.usage_generation)
    core._provider = test_provider(
        ["draft"],
        usage=Usage(prompt_tokens=50, completion_tokens=10, total_tokens=60),
    )
    await _drain(core.draft_compression(u2.id, u2.id))

    assert (core.last_usage, core.calibration, core.usage_generation) == before


async def test_range_validation_before_provider_call(repo, workspace, test_provider):
    # C128: unknown start, unknown end, reversed range each fail fast, no provider call.
    core = _core(repo, workspace, test_provider(["ok"]))
    u1, a1, u2, a2 = await _build_line(core)

    bad_ranges = [
        ("unknown-start-id", a2.id),
        (u1.id, "unknown-end-id"),
        (a2.id, u1.id),  # reversed: start after end
    ]
    for start, end in bad_ranges:
        rec = RecordingProvider(["draft"])
        core._provider = rec
        with pytest.raises(ValueError):
            await _drain(core.draft_compression(start, end))
        assert rec.called is False


async def test_draft_during_live_stream_raises(repo, workspace, test_provider):
    # C129 (H2 guard)
    blocker = BlockingProvider()
    core = _core(repo, workspace, blocker)
    u1, a1 = core.submit("kick off the assistant")
    agen = core.stream(a1)
    await agen.__anext__()
    try:
        assert core.streaming is True
        with pytest.raises(ValueError):
            await _drain(core.draft_compression(u1.id, u1.id))
    finally:
        blocker.release()
        await agen.aclose()


async def test_completed_draft_mutates_no_state(repo, workspace, test_provider):
    # C130
    core = _core(repo, workspace, test_provider(["ok"]))
    u1, a1, u2, a2 = await _build_line(core)

    before_ids = [n.id for n in core.current_view()]
    core._provider = test_provider(["draft", " summary"])
    await _drain(core.draft_compression(u2.id, u2.id))
    after_ids = [n.id for n in core.current_view()]

    assert after_ids == before_ids


async def test_range_containing_compression_node_refused(repo, workspace, test_provider):
    # C131 (flat guard)
    core = _core(repo, workspace, test_provider(["ok"]))
    u1, a1, u2, a2 = await _build_line(core)

    k = core.commit_compression(u1.id, a1.id, "a concise summary")
    view_ids = [n.id for n in core.current_view()]
    assert k.id in view_ids

    rec = RecordingProvider(["draft"])
    core._provider = rec
    with pytest.raises(ValueError):
        await _drain(core.draft_compression(k.id, a2.id))
    assert rec.called is False
