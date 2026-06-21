"""Intent-derived tests for the deterministic ``TestProvider`` double.

``TestProvider`` is a hand-rolled test double that streams a fixed list of
tokens regardless of the conversation/model it is asked to serve, and reports
a constant healthy connectivity result. These tests assert that contract from
intent only.

The real ``LiteLLMProvider`` performs network I/O and is out of scope here.

Providers are constructed exclusively through the ``test_provider`` conftest
fixture, a factory ``Callable[[list[str]], TestProvider]``.
"""


async def _collect(agen):
    return [t async for t in agen]


# C1: stream yields exactly the constructor tokens, in order (multi-token).
async def test_stream_yields_constructor_tokens_in_order(test_provider):
    tokens = ["The", " quick", " brown", " fox"]
    provider = test_provider(tokens)

    collected = await _collect(provider.stream(messages=[], model="gpt-4o"))

    assert collected == ["The", " quick", " brown", " fox"]


# C1: stream yields exactly the constructor tokens (single token).
async def test_stream_single_token(test_provider):
    provider = test_provider(["solitary"])

    collected = await _collect(provider.stream(messages=[], model="gpt-4o"))

    assert collected == ["solitary"]


# C1: stream preserves order and duplicates.
async def test_stream_preserves_order_and_duplicates(test_provider):
    tokens = ["echo", "echo", "fade", "echo"]
    provider = test_provider(tokens)

    collected = await _collect(provider.stream(messages=[], model="gpt-4o"))

    assert collected == ["echo", "echo", "fade", "echo"]


# C2: output is independent of messages/model.
async def test_stream_independent_of_messages_and_model(test_provider):
    tokens = ["alpha", " beta", " gamma"]
    provider = test_provider(tokens)

    first = await _collect(
        provider.stream(
            messages=[{"role": "user", "content": "What is the capital of France?"}],
            model="gpt-4o",
        )
    )
    second = await _collect(
        provider.stream(
            messages=[{"role": "user", "content": "Summarize this report."}],
            model="claude-3-5-sonnet",
        )
    )

    assert first == second
    assert first == ["alpha", " beta", " gamma"]


# C3: empty token list yields nothing.
async def test_stream_empty_yields_nothing(test_provider):
    provider = test_provider([])

    collected = await _collect(provider.stream(messages=[], model="gpt-4o"))

    assert collected == []


# C4: check_connectivity returns exactly (True, "ok").
async def test_check_connectivity_returns_ok(test_provider):
    provider = test_provider(["unused"])

    result = await provider.check_connectivity("gpt-4o")

    assert result == (True, "ok")


# C4: check_connectivity is independent of the model argument.
async def test_check_connectivity_independent_of_model(test_provider):
    provider = test_provider(["unused"])

    first = await provider.check_connectivity("gpt-4o")
    second = await provider.check_connectivity("claude-3-5-sonnet")

    assert first == (True, "ok")
    assert second == (True, "ok")
    assert first == second
