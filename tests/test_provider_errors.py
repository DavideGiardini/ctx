"""Behavioral tests for the ProviderError domain seam + stream timeout.

Contract: tests/specs/provider-errors.md (PE1..PE6).

These are code-blind tests: every expected value traces to a contract Expect,
not to any assumed implementation detail. We exercise LiteLLMProvider through
its established backend seam (the module-level ``acompletion`` name) and the
ConversationCore consumption path through the repo/workspace fixtures.
"""

import asyncio
import math
from types import SimpleNamespace

import pytest

from ctx.core.conversation import ConversationCore
from ctx.core.provider import STREAM_TIMEOUT, LiteLLMProvider, ProviderError

# --- helpers (repo conventions) -------------------------------------------------

def _chunk(content):
    """Build a litellm-shaped streaming chunk: chunk.choices[0].delta.content."""
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
    )


async def _collect(agen):
    return [t async for t in agen]


MESSAGES = [{"role": "user", "content": "Summarize the quarterly revenue report."}]
MODEL = "gpt-4o-mini"


# --- PE1: request-time backend error wraps as ProviderError ---------------------

async def test_request_time_backend_error_wraps_as_provider_error(monkeypatch):
    # PE1
    original = RuntimeError("connection refused by backend")

    async def fake(**kwargs):
        raise original

    monkeypatch.setattr("ctx.core.provider.acompletion", fake)
    provider = LiteLLMProvider()

    with pytest.raises(ProviderError) as ei:
        await _collect(provider.stream(MESSAGES, MODEL))

    # original backend exception must not leak; it is chained on __cause__.
    assert ei.value.__cause__ is original


# --- PE2: mid-stream backend error wraps; prior tokens observed -----------------

async def test_mid_stream_backend_error_wraps_and_preserves_prior_tokens(monkeypatch):
    # PE2
    original = ValueError("malformed chunk from backend")

    async def fake(**kwargs):
        async def _gen():
            yield _chunk("The revenue ")
            yield _chunk("rose by ")
            raise original

        return _gen()

    monkeypatch.setattr("ctx.core.provider.acompletion", fake)
    provider = LiteLLMProvider()

    collected = []
    with pytest.raises(ProviderError) as ei:
        async for tok in provider.stream(MESSAGES, MODEL):
            collected.append(tok)

    assert collected == ["The revenue ", "rose by "]
    assert ei.value.__cause__ is original


# --- PE3: STREAM_TIMEOUT is positive/finite and handed to the backend -----------

def test_stream_timeout_is_positive_finite_number():
    # PE3
    assert isinstance(STREAM_TIMEOUT, (int, float))
    assert STREAM_TIMEOUT > 0
    assert math.isfinite(STREAM_TIMEOUT)


async def test_stream_passes_timeout_kwarg_to_backend(monkeypatch):
    # PE3
    captured = {}

    async def fake(**kwargs):
        captured.update(kwargs)

        async def _gen():
            yield _chunk("ok")

        return _gen()

    monkeypatch.setattr("ctx.core.provider.acompletion", fake)
    provider = LiteLLMProvider()

    await _collect(provider.stream(MESSAGES, MODEL))

    assert "timeout" in captured
    assert captured["timeout"] == STREAM_TIMEOUT


# --- PE4: happy path yields ordered plain-string deltas, no wrapping -------------

async def test_happy_path_yields_ordered_string_deltas(monkeypatch):
    # PE4
    contents = ["Quarterly ", "revenue ", "increased ", "12%."]

    async def fake(**kwargs):
        async def _gen():
            for c in contents:
                yield _chunk(c)

        return _gen()

    monkeypatch.setattr("ctx.core.provider.acompletion", fake)
    provider = LiteLLMProvider()

    out = await _collect(provider.stream(MESSAGES, MODEL))

    assert out == contents
    assert all(isinstance(t, str) for t in out)


# --- PE5: cancellation signals are not wrapped ----------------------------------

async def test_cancelled_error_is_not_wrapped(monkeypatch):
    # PE5
    async def fake(**kwargs):
        async def _gen():
            yield _chunk("partial")
            raise asyncio.CancelledError()

        return _gen()

    monkeypatch.setattr("ctx.core.provider.acompletion", fake)
    provider = LiteLLMProvider()

    with pytest.raises(asyncio.CancelledError):
        await _collect(provider.stream(MESSAGES, MODEL))


# --- PE6: ProviderError flows through ConversationCore unchanged; partial saved --

class _FailingProvider:
    """Provider double: yields tokens, then raises a specific ProviderError."""

    def __init__(self, tokens, error):
        self._tokens = tokens
        self._error = error

    async def stream(self, messages, model, on_usage=None):
        for tok in self._tokens:
            yield tok
        raise self._error

    async def check_connectivity(self, model):
        return True, "ok"


async def test_provider_error_propagates_and_partial_is_persisted(repo, workspace):
    # PE6
    tokens = ["Analysis ", "of the ", "dataset "]
    sentinel = ProviderError("backend died mid-stream")
    provider = _FailingProvider(tokens, sentinel)

    core = ConversationCore(repo, provider, workspace)
    core.setup()
    _, assistant_node = core.submit("Analyze this dataset for anomalies.")

    with pytest.raises(ProviderError) as ei:
        await _collect(core.stream(assistant_node))

    # SAME object propagates, unchanged (identity, not just type).
    assert ei.value is sentinel

    # Partial assistant content was persisted: exactly the tokens before failure.
    # repo.load() returns a list[Node] directly (see ctx/core/storage.py).
    loaded = repo.load(core.conversation_id)
    assistant_contents = [n.content for n in loaded if n.role == "assistant"]
    assert "".join(tokens) in assistant_contents
