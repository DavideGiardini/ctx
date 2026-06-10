from collections.abc import AsyncIterator
from typing import Protocol

from litellm import acompletion

from ctx.core.log import logger


class Provider(Protocol):
    """Seam for LLM streaming."""

    def stream(self, messages: list[dict], model: str) -> AsyncIterator[str]: ...
    async def check_connectivity(self, model: str) -> tuple[bool, str]: ...


class LiteLLMProvider:
    """Concrete adapter using litellm."""

    async def stream(self, messages: list[dict], model: str) -> AsyncIterator[str]:
        logger.info("stream started | model=%s | messages=%d", model, len(messages))
        response = await acompletion(
            model=model,
            messages=messages,
            stream=True,
        )
        async for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
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
