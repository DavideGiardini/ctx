from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from litellm import acompletion

from ctx.core.log import logger

DEFAULT_CONTEXT_WINDOW = 128_000
"""Fallback context-window size (tokens) when a model's limit is unknown."""


@dataclass
class StreamChunk:
    """A single piece of the LLM stream."""

    token: str
    """The text delta for this chunk."""
    usage: dict | None = None
    """Usage metadata (e.g. ``{"completion_tokens": 42}``).

    Usually only present on the final chunk.
    """


class Provider(Protocol):
    """Seam for LLM streaming."""

    def stream(self, messages: list[dict], model: str) -> AsyncIterator[StreamChunk]: ...
    async def check_connectivity(self, model: str) -> tuple[bool, str]: ...
    def context_window_limit(self, model: str) -> int: ...


class LiteLLMProvider:
    """Concrete adapter using litellm."""

    async def stream(self, messages: list[dict], model: str) -> AsyncIterator[StreamChunk]:
        logger.info("stream started | model=%s | messages=%d", model, len(messages))
        response = await acompletion(
            model=model,
            messages=messages,
            stream=True,
        )
        async for chunk in response:
            delta = chunk.choices[0].delta.content
            usage = getattr(chunk, "usage", None)
            if delta or usage:
                yield StreamChunk(token=delta or "", usage=usage)
        logger.info("stream done")

    async def check_connectivity(self, model: str) -> tuple[bool, str]:
        try:
            await acompletion(
                model=model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                stream=False,
            )
            return True, f"Connected to {model}"
        except Exception as exc:
            logger.warning("connectivity check failed | model=%s | error=%s", model, exc)
            return False, str(exc)

    def context_window_limit(self, model: str) -> int:
        """Return the model's input context-window size in tokens."""
        try:
            import litellm

            info = litellm.get_model_info(model)
            return info.get("max_input_tokens") or info.get("max_tokens") or DEFAULT_CONTEXT_WINDOW
        except Exception:
            return DEFAULT_CONTEXT_WINDOW


class TestProvider:
    """Test adapter that yields tokens from a list."""

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    async def stream(self, messages: list[dict], model: str) -> AsyncIterator[StreamChunk]:
        for token in self._tokens:
            yield StreamChunk(token=token)

    async def check_connectivity(self, model: str) -> tuple[bool, str]:
        return True, "ok"

    def context_window_limit(self, model: str) -> int:
        return DEFAULT_CONTEXT_WINDOW
