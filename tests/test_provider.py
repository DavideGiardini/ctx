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

from ctx.core.provider import LiteLLMProvider, Usage
from ctx.core.provider import TestProvider as CannedProvider


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


# --- New helpers for the usage seam ---


def _usage_chunk(prompt, completion, total):
    """A final upstream chunk: EMPTY choices list + a usage object."""
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
        ),
    )


def _make_usage_stream_fake(contents, usage_chunk, captured):
    """Fake async acompletion yielding content chunks then a final usage chunk.

    Mirrors _make_stream_fake but appends a final empty-choices usage chunk.
    `usage_chunk` may be None to model 'no usage chunk ever sent'.
    """

    async def fake_acompletion(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

        async def gen():
            for c in contents:
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content=c))],
                    usage=None,
                )
            if usage_chunk is not None:
                yield usage_chunk

        return gen()

    return fake_acompletion


async def _drain(stream):
    """Consume an async token stream into a list of yielded tokens, in order."""
    out = []
    async for tok in stream:
        out.append(tok)
    return out


# --- TestProvider (CannedProvider) cases ---


# C10: canned usage -> on_usage fires exactly once with that exact Usage
async def test_canned_usage_fires_once_with_exact_counts():
    usage = Usage(prompt_tokens=128, completion_tokens=42, total_tokens=170)
    provider = CannedProvider(["The", " quick", " brown", " fox"], usage=usage)
    seen = []

    await _drain(
        provider.stream(
            [{"role": "user", "content": "hi"}], "gpt-4o", on_usage=seen.append
        )
    )

    assert len(seen) == 1
    got = seen[0]
    assert got.prompt_tokens == 128
    assert got.completion_tokens == 42
    assert got.total_tokens == 170


# C11: canned usage -> all tokens still stream in order, none dropped
async def test_canned_usage_does_not_disturb_token_stream():
    tokens = ["Hello", ", ", "world", "!"]
    provider = CannedProvider(tokens, usage=Usage(10, 4, 14))

    streamed = await _drain(
        provider.stream(
            [{"role": "user", "content": "greet"}], "gpt-4o", on_usage=lambda u: None
        )
    )

    assert streamed == tokens


# C12: callback fires AFTER all tokens (reports completed completion)
async def test_canned_usage_callback_fires_after_tokens():
    tokens = ["alpha", "beta", "gamma"]
    provider = CannedProvider(tokens, usage=Usage(5, 3, 8))
    streamed = []
    tokens_seen_at_callback = []

    def on_usage(_usage):
        tokens_seen_at_callback.append(len(streamed))

    async for tok in provider.stream(
        [{"role": "user", "content": "x"}], "gpt-4o", on_usage=on_usage
    ):
        streamed.append(tok)

    assert tokens_seen_at_callback == [len(tokens)]


# C13: usage=None -> callback never fires even when supplied
async def test_no_canned_usage_never_calls_callback():
    tokens = ["one", "two", "three"]
    provider = CannedProvider(tokens)  # default usage=None
    seen = []

    streamed = await _drain(
        provider.stream(
            [{"role": "user", "content": "count"}], "gpt-4o", on_usage=seen.append
        )
    )

    assert seen == []
    assert streamed == tokens


# C14: on_usage omitted / None behaves exactly like before
async def test_on_usage_optional_behaves_as_before():
    tokens = ["foo", "bar", "baz"]

    # explicit None
    p1 = CannedProvider(tokens, usage=Usage(1, 1, 2))
    streamed_none = await _drain(
        p1.stream([{"role": "user", "content": "q"}], "gpt-4o", on_usage=None)
    )
    assert streamed_none == tokens

    # omitted entirely
    p2 = CannedProvider(tokens, usage=Usage(1, 1, 2))
    streamed_omitted = await _drain(
        p2.stream([{"role": "user", "content": "q"}], "gpt-4o")
    )
    assert streamed_omitted == tokens


# --- LiteLLMProvider cases ---


# C15: final empty-choices usage chunk does NOT crash; tokens still stream in order
async def test_litellm_empty_choices_usage_chunk_does_not_crash(monkeypatch):
    contents = ["Once", " upon", " a", " time"]
    captured = {}
    fake = _make_usage_stream_fake(contents, _usage_chunk(50, 12, 62), captured)
    monkeypatch.setattr("ctx.core.provider.acompletion", fake)

    streamed = await _drain(
        LiteLLMProvider().stream([{"role": "user", "content": "story"}], "gpt-4o")
    )

    assert streamed == contents


# C16: usage chunk drives on_usage exactly once with mapped prompt/completion/total
async def test_litellm_usage_chunk_invokes_callback_once_with_mapped_fields(monkeypatch):
    contents = ["Result", ": ", "ok"]
    captured = {}
    fake = _make_usage_stream_fake(contents, _usage_chunk(200, 35, 235), captured)
    monkeypatch.setattr("ctx.core.provider.acompletion", fake)
    seen = []

    await _drain(
        LiteLLMProvider().stream(
            [{"role": "user", "content": "go"}], "gpt-4o", on_usage=seen.append
        )
    )

    assert len(seen) == 1
    got = seen[0]
    assert got.prompt_tokens == 200
    assert got.completion_tokens == 35
    assert got.total_tokens == 235


# C17: no usage chunk ever sent -> callback never fires; tokens still stream
async def test_litellm_no_usage_chunk_never_calls_callback(monkeypatch):
    contents = ["just", " content", " tokens"]
    captured = {}
    fake = _make_usage_stream_fake(contents, None, captured)
    monkeypatch.setattr("ctx.core.provider.acompletion", fake)
    seen = []

    streamed = await _drain(
        LiteLLMProvider().stream(
            [{"role": "user", "content": "no usage"}], "gpt-4o", on_usage=seen.append
        )
    )

    assert seen == []
    assert streamed == contents
