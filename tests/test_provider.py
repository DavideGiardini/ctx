"""Intent-derived tests for the deterministic ``TestProvider`` double.

``TestProvider`` is a hand-rolled test double that streams a fixed list of
tokens regardless of the conversation/model it is asked to serve, and reports
a constant healthy connectivity result. These tests assert that contract from
intent only.

The real ``LiteLLMProvider`` performs network I/O and is out of scope here.

Providers are constructed exclusively through the ``test_provider`` conftest
fixture, a factory ``Callable[[list[str]], TestProvider]``.
"""

from types import SimpleNamespace

from ctx.core.provider import LiteLLMProvider


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


def _chunk(content):
    """Build a fake litellm streaming chunk: chunk.choices[0].delta.content."""
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
    )


def _make_stream_fake(contents, captured):
    """Return a fake async `acompletion` that records kwargs and, when awaited,
    yields an async iterator of chunks built from `contents`."""

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)

        async def _aiter():
            for c in contents:
                yield _chunk(c)

        return _aiter()

    return fake_acompletion


# C5 — stream surfaces upstream content deltas as plain strings, in order.
async def test_stream_yields_content_deltas_in_order(monkeypatch):
    captured = {}
    fake = _make_stream_fake(["Hello", " world"], captured)
    monkeypatch.setattr("ctx.core.provider.acompletion", fake)

    provider = LiteLLMProvider()
    messages = [{"role": "user", "content": "Greet me politely."}]
    tokens = [t async for t in provider.stream(messages, "gpt-4o-mini")]

    assert tokens == ["Hello", " world"]


# C6 — stream drops empty/None content deltas.
async def test_stream_skips_none_and_empty_deltas(monkeypatch):
    captured = {}
    fake = _make_stream_fake(["a", None, "", "b"], captured)
    monkeypatch.setattr("ctx.core.provider.acompletion", fake)

    provider = LiteLLMProvider()
    messages = [{"role": "user", "content": "Say a then b."}]
    tokens = [t async for t in provider.stream(messages, "claude-3-5-sonnet")]

    assert tokens == ["a", "b"]


# C7 — stream requests a streamed completion for the caller's model and messages.
async def test_stream_forwards_model_messages_and_stream_flag(monkeypatch):
    captured = {}
    fake = _make_stream_fake(["ok"], captured)
    monkeypatch.setattr("ctx.core.provider.acompletion", fake)

    provider = LiteLLMProvider()
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the capital of France?"},
    ]
    model = "gpt-4o-mini"

    _ = [t async for t in provider.stream(messages, model)]

    assert captured.get("stream") is True
    assert captured.get("model") == model
    assert captured.get("messages") == messages


# C8 — check_connectivity returns an affirmative verdict when the probe succeeds.
async def test_check_connectivity_success(monkeypatch):
    async def fake_acompletion(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="pong"))]
        )

    monkeypatch.setattr("ctx.core.provider.acompletion", fake_acompletion)

    provider = LiteLLMProvider()
    model = "gpt-4o-mini"
    ok, msg = await provider.check_connectivity(model)

    assert ok is True
    assert isinstance(msg, str)
    assert msg != ""
    assert model in msg


# C9 — check_connectivity converts an upstream failure into a negative verdict, never raises.
async def test_check_connectivity_failure_does_not_raise(monkeypatch):
    async def fake_acompletion(**kwargs):
        raise Exception("boom-net-1234")

    monkeypatch.setattr("ctx.core.provider.acompletion", fake_acompletion)

    provider = LiteLLMProvider()
    # No pytest.raises: the exception must be swallowed and converted to a verdict.
    ok, msg = await provider.check_connectivity("claude-3-5-sonnet")

    assert ok is False
    assert isinstance(msg, str)
    assert "boom-net-1234" in msg
