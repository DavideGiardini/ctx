"""Tool calls crossing the provider seam.

Contract: tests/specs/provider-tools.md (items T1-T6).

Never touches the network: the litellm adapter is isolated by monkeypatching
``ctx.core.provider.acompletion`` with an async callable returning an async
iterator of fake chunk objects.
"""

from types import SimpleNamespace

from ctx.core.provider import (
    LiteLLMProvider,
    ScriptedRound,
    ToolCall,
    Usage,
)
from ctx.core.provider import (
    TestProvider as CannedProvider,
)

MODEL = "openrouter/anthropic/claude-sonnet-4"

# --- local helpers -------------------------------------------------------


def _search_tool() -> dict:
    """An OpenAI-format tool definition, fresh per call (no shared state)."""
    return {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search the web for pages relevant to a query.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }


def _chunk(
    content: str | None = None,
    tool_calls: list | None = None,
) -> SimpleNamespace:
    """A normal streaming chunk: one choice, a delta, no usage."""
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)


def _usage_chunk(prompt: int, completion: int, total: int) -> SimpleNamespace:
    """The documented final chunk: empty ``choices``, usage only."""
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
        ),
    )


def _fragment(
    index: int,
    *,
    call_id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
) -> SimpleNamespace:
    """One partial tool-call fragment as litellm emits them."""
    return SimpleNamespace(
        index=index,
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _frag_chunk(*fragments: SimpleNamespace) -> SimpleNamespace:
    return _chunk(tool_calls=list(fragments))


def _fake_acompletion(chunks: list, seen_kwargs: list[dict]):
    """An async callable standing in for ``acompletion``."""

    async def fake(*_args, **kwargs):
        seen_kwargs.append(kwargs)

        async def chunk_stream():
            for chunk in chunks:
                yield chunk

        return chunk_stream()

    return fake


# --- TestProvider: the scripted seam ------------------------------------


# T1: a scripted tool round yields only str tokens and reports its calls once.
async def test_scripted_tool_round_reports_calls_once_out_of_band():
    call = ToolCall(
        id="call_9f2c",
        name="search",
        arguments='{"query": "append-only conversation graph"}',
    )
    provider = CannedProvider(
        rounds=[ScriptedRound(tokens=["Let me ", "look that up."], tool_calls=[call])]
    )
    reported: list[list[ToolCall]] = []
    reports_seen_per_token: list[int] = []

    tokens = []
    async for token in provider.stream(
        [{"role": "user", "content": "How does ctx store history?"}],
        MODEL,
        tools=[_search_tool()],
        on_tool_calls=reported.append,
    ):
        reports_seen_per_token.append(len(reported))
        tokens.append(token)

    assert tokens == ["Let me ", "look that up."]
    assert all(isinstance(token, str) for token in tokens)
    # Out-of-band: nothing about the call leaked into the token sequence, and
    # the batch was not announced before the response ended.
    assert reports_seen_per_token[0] == 0
    assert reported == [[call]]


# T2: a turn that settles in text never fires on_tool_calls -- not even with [].
async def test_plain_text_turn_never_reports_tool_calls():
    reported: list[list[ToolCall]] = []
    messages = [{"role": "user", "content": "Summarise the last three commits."}]

    plain = CannedProvider(tokens=["The graph ", "stayed append-only."])
    plain_tokens = [
        token
        async for token in plain.stream(
            messages,
            MODEL,
            tools=[_search_tool()],
            on_tool_calls=reported.append,
        )
    ]

    scripted = CannedProvider(rounds=[ScriptedRound(tokens=["Nothing to search here."])])
    scripted_tokens = [
        token
        async for token in scripted.stream(
            messages,
            MODEL,
            on_tool_calls=reported.append,
        )
    ]

    assert plain_tokens == ["The graph ", "stayed append-only."]
    assert scripted_tokens == ["Nothing to search here."]
    assert reported == []


# T3: the new parameters are inert when omitted -- old call sites unaffected.
async def test_new_parameters_are_inert_when_omitted(monkeypatch):
    messages = [{"role": "user", "content": "What changed in the provider seam?"}]

    # A script that ends in a tool call, streamed with no on_tool_calls: no raise.
    fetch_call = ToolCall(
        id="call_1a",
        name="fetch",
        arguments='{"url": "https://example.com/adr-0002"}',
    )
    scripted = CannedProvider(
        rounds=[
            ScriptedRound(tokens=["Checking the docs."], tool_calls=[fetch_call]),
        ]
    )
    scripted_tokens = [token async for token in scripted.stream(messages, MODEL)]
    assert scripted_tokens == ["Checking the docs."]

    # The real adapter must offer no tools at all -- not an empty list.
    seen_kwargs: list[dict] = []
    monkeypatch.setattr(
        "ctx.core.provider.acompletion",
        _fake_acompletion(
            [
                _chunk(),
                _chunk("The seam now "),
                _chunk("carries tool calls."),
                _usage_chunk(311, 24, 335),
            ],
            seen_kwargs,
        ),
    )

    adapter_tokens = [token async for token in LiteLLMProvider().stream(messages, MODEL)]

    assert adapter_tokens == ["The seam now ", "carries tool calls."]
    assert len(seen_kwargs) == 1
    assert seen_kwargs[0].get("tools") is None


# --- LiteLLMProvider: reassembling backend fragments --------------------


# T4: fragments are reassembled into one ToolCall per index; the usage-only
# chunk with empty choices does not crash the loop.
async def test_adapter_reassembles_fragments_into_domain_tool_calls(monkeypatch):
    chunks = [
        _chunk(),  # role-only chunk: no text, no tool calls
        _chunk("Searching for that."),
        # Call 0 opens WITHOUT id/name -- they arrive on a later fragment.
        _frag_chunk(_fragment(0, arguments='{"qu')),
        _frag_chunk(
            _fragment(
                0,
                call_id="call_search_1",
                name="search",
                arguments='ery": "ctx0 ',
            )
        ),
        _frag_chunk(
            _fragment(
                1,
                call_id="call_fetch_2",
                name="fetch",
                arguments='{"url": ',
            )
        ),
        _frag_chunk(_fragment(0, arguments='roadmap"}')),  # interleaved with call 1
        _frag_chunk(_fragment(1, arguments='"https://example.com/ctx0"}')),
        _chunk(),  # finish chunk
        _usage_chunk(1_204, 63, 1_267),
    ]
    seen_kwargs: list[dict] = []
    monkeypatch.setattr("ctx.core.provider.acompletion", _fake_acompletion(chunks, seen_kwargs))

    reported: list[list[ToolCall]] = []
    usages: list[Usage] = []

    tokens = [
        token
        async for token in LiteLLMProvider().stream(
            [{"role": "user", "content": "What is on the ctx0 roadmap?"}],
            MODEL,
            on_usage=usages.append,
            tools=[_search_tool()],
            on_tool_calls=reported.append,
        )
    ]

    assert tokens == ["Searching for that."]
    assert reported == [
        [
            ToolCall(
                id="call_search_1",
                name="search",
                arguments='{"query": "ctx0 roadmap"}',
            ),
            ToolCall(
                id="call_fetch_2",
                name="fetch",
                arguments='{"url": "https://example.com/ctx0"}',
            ),
        ]
    ]
    assert usages == [Usage(prompt_tokens=1_204, completion_tokens=63, total_tokens=1_267)]


# T5: a text-only response through the adapter never fires on_tool_calls.
async def test_adapter_does_not_report_tool_calls_for_text_only_response(monkeypatch):
    chunks = [
        _chunk(),
        _chunk("Compression "),
        _chunk("is non-destructive."),
        _chunk(),
        _usage_chunk(508, 12, 520),
    ]
    seen_kwargs: list[dict] = []
    monkeypatch.setattr("ctx.core.provider.acompletion", _fake_acompletion(chunks, seen_kwargs))

    reported: list[list[ToolCall]] = []

    tokens = [
        token
        async for token in LiteLLMProvider().stream(
            [{"role": "user", "content": "Does compression delete nodes?"}],
            MODEL,
            tools=[_search_tool()],
            on_tool_calls=reported.append,
        )
    ]

    assert tokens == ["Compression ", "is non-destructive."]
    assert reported == []


# T6: consecutive streams replay consecutive rounds, the last round repeats,
# and tools_seen records what was offered on each round.
async def test_scripted_rounds_replay_in_order_and_last_round_repeats():
    search_call = ToolCall(
        id="call_7b31",
        name="search",
        arguments='{"query": "ctx0 roadmap milestones"}',
    )
    provider = CannedProvider(
        rounds=[
            ScriptedRound(tokens=["I will search for that."], tool_calls=[search_call]),
            ScriptedRound(tokens=["ctx0 ships ", "the node graph first."]),
        ]
    )
    messages = [{"role": "user", "content": "What ships first in ctx0?"}]
    reported: list[list[ToolCall]] = []
    offered = _search_tool()

    async def drain(tools):
        return [
            token
            async for token in provider.stream(
                messages,
                MODEL,
                tools=tools,
                on_tool_calls=reported.append,
            )
        ]

    first = await drain([offered])
    assert first == ["I will search for that."]
    assert reported == [[search_call]]

    second = await drain(None)  # tools withheld on the final round
    assert second == ["ctx0 ships ", "the node graph first."]
    assert reported == [[search_call]]

    third = await drain(None)  # past the end of the script: last round repeats
    assert third == ["ctx0 ships ", "the node graph first."]
    assert reported == [[search_call]]

    assert provider.tools_seen == [[offered], None, None]
