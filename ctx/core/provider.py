from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Protocol

from litellm import acompletion

from ctx.core.log import logger

# Upper bound (seconds) on a single backend request, so a hung connection
# cannot keep a stream open indefinitely.
STREAM_TIMEOUT = 60.0


@dataclass(frozen=True)
class Usage:
    """Exact token accounting for one completion, as reported by the provider.

    The provider-authoritative counts that sharpen the UI's local estimate:
    ``prompt_tokens`` (input the model actually billed), ``completion_tokens``
    (output it produced), ``total_tokens`` (their sum, as the provider reports
    it). Delivered out-of-band via the ``on_usage`` callback rather than the
    token stream, so ``stream`` keeps yielding plain ``str`` (ADR 0015).
    """

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ProviderError(Exception):
    """Raised when the LLM backend fails during a streamed completion.

    Wraps the backend-specific exception (e.g. a litellm error) so callers can
    handle provider failures without importing or catching litellm types — the
    backend never leaks through the ``Provider`` seam. The original exception is
    chained via ``__cause__`` (``raise ProviderError(...) from exc``).
    """


class Provider(Protocol):
    """Seam for LLM streaming."""

    def stream(
        self,
        messages: list[dict],
        model: str,
        on_usage: Callable[[Usage], None] | None = None,
    ) -> AsyncIterator[str]:
        """Stream the assistant reply token-by-token.

        When ``on_usage`` is supplied and the provider reports exact token
        counts for the completion, it is invoked **exactly once** with the
        ``Usage``. Providers with no usage to report simply never call it, so
        passing ``on_usage`` is always safe and never required.
        """
        ...

    async def check_connectivity(self, model: str) -> tuple[bool, str]: ...


class LiteLLMProvider:
    """Concrete adapter using litellm."""

    async def stream(
        self,
        messages: list[dict],
        model: str,
        on_usage: Callable[[Usage], None] | None = None,
    ) -> AsyncIterator[str]:
        logger.info("stream started | model=%s | messages=%d", model, len(messages))
        try:
            response = await acompletion(
                model=model,
                messages=messages,
                stream=True,
                stream_options={"include_usage": True},
                timeout=STREAM_TIMEOUT,
            )
            async for chunk in response:
                # The final usage chunk carries no choices, so index only when
                # a choice is present (include_usage emits an empty-choices chunk).
                if chunk.choices:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
                usage = getattr(chunk, "usage", None)
                if usage is not None and on_usage is not None:
                    on_usage(
                        Usage(
                            prompt_tokens=usage.prompt_tokens,
                            completion_tokens=usage.completion_tokens,
                            total_tokens=usage.total_tokens,
                        )
                    )
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

    def __init__(self, tokens: list[str], usage: Usage | None = None) -> None:
        self._tokens = tokens
        self._usage = usage

    async def stream(
        self,
        messages: list[dict],
        model: str,
        on_usage: Callable[[Usage], None] | None = None,
    ) -> AsyncIterator[str]:
        for token in self._tokens:
            yield token
        if self._usage is not None and on_usage is not None:
            on_usage(self._usage)

    async def check_connectivity(self, model: str) -> tuple[bool, str]:
        return True, "ok"
