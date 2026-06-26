from collections.abc import AsyncIterator
from typing import Protocol

from litellm import acompletion

from ctx.core.log import logger

# Upper bound (seconds) on a single backend request, so a hung connection
# cannot keep a stream open indefinitely.
STREAM_TIMEOUT = 60.0


class ProviderError(Exception):
    """Raised when the LLM backend fails during a streamed completion.

    Wraps the backend-specific exception (e.g. a litellm error) so callers can
    handle provider failures without importing or catching litellm types — the
    backend never leaks through the ``Provider`` seam. The original exception is
    chained via ``__cause__`` (``raise ProviderError(...) from exc``).
    """


class Provider(Protocol):
    """Seam for LLM streaming."""

    def stream(self, messages: list[dict], model: str) -> AsyncIterator[str]: ...
    async def check_connectivity(self, model: str) -> tuple[bool, str]: ...


class LiteLLMProvider:
    """Concrete adapter using litellm."""

    async def stream(self, messages: list[dict], model: str) -> AsyncIterator[str]:
        logger.info("stream started | model=%s | messages=%d", model, len(messages))
        try:
            response = await acompletion(
                model=model,
                messages=messages,
                stream=True,
                timeout=STREAM_TIMEOUT,
            )
            async for chunk in response:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as exc:
            # Map any backend failure (request-time or mid-stream) to the domain
            # error so litellm types never leak through the seam. CancelledError
            # and GeneratorExit are BaseException, so they pass through unwrapped.
            logger.warning("stream failed | model=%s | error=%s", model, exc)
            raise ProviderError(str(exc)) from exc
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


class TestProvider:
    """Test adapter that yields tokens from a list."""

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    async def stream(self, messages: list[dict], model: str) -> AsyncIterator[str]:
        for token in self._tokens:
            yield token

    async def check_connectivity(self, model: str) -> tuple[bool, str]:
        return True, "ok"
