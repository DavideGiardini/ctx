from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation the model asked for, as it crossed the seam.

    ``arguments`` is the raw JSON string exactly as the model emitted it —
    unparsed and unvalidated, because whether it is even valid JSON is the
    dispatcher's problem, not the provider's (D8). ``id`` is the provider's
    correlation id, echoed back on the ``role="tool"`` message that answers this
    call. Delivered out-of-band via ``on_tool_calls`` rather than the token
    stream, so ``stream`` keeps yielding plain ``str`` (ADR 0018 §1).
    """

    id: str
    name: str
    arguments: str


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
        tools: list[dict] | None = None,
        on_tool_calls: Callable[[list[ToolCall]], None] | None = None,
    ) -> AsyncIterator[str]:
        """Stream the assistant reply token-by-token.

        When ``on_usage`` is supplied and the provider reports exact token
        counts for the completion, it is invoked **exactly once** with the
        ``Usage``. Providers with no usage to report simply never call it, so
        passing ``on_usage`` is always safe and never required.

        ``tools`` are OpenAI-format tool definitions offered to the model for
        this request; omit them (or pass ``None``) and the request is an ordinary
        completion. When the response ends in tool calls and ``on_tool_calls`` is
        supplied, it is invoked **exactly once** with every call the model asked
        for, in the order the provider indexed them — and never invoked at all
        for a response that ends in plain text. Like ``on_usage`` it is
        out-of-band: the stream itself still yields only ``str`` (ADR 0018 §1).
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
        tools: list[dict] | None = None,
        on_tool_calls: Callable[[list[ToolCall]], None] | None = None,
    ) -> AsyncIterator[str]:
        logger.info(
            "stream started | model=%s | messages=%d | tools=%d",
            model,
            len(messages),
            len(tools or []),
        )
        # AIDEV-NOTE: tool calls arrive as *fragments* keyed by index — id and
        # name on whichever fragment opens the call, arguments split across
        # chunks — so they are accumulated here and reported once at the end
        # (ADR 0018 §1). No litellm object crosses the seam.
        pending: dict[int, dict[str, str]] = {}
        try:
            response = await acompletion(
                model=model,
                messages=messages,
                stream=True,
                stream_options={"include_usage": True},
                timeout=STREAM_TIMEOUT,
                tools=tools,
            )
            async for chunk in response:
                # The final usage chunk carries no choices, so index only when
                # a choice is present (include_usage emits an empty-choices chunk).
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield delta.content
                    for fragment in getattr(delta, "tool_calls", None) or []:
                        call = pending.setdefault(
                            fragment.index, {"id": "", "name": "", "arguments": ""}
                        )
                        if fragment.id:
                            call["id"] = fragment.id
                        function = getattr(fragment, "function", None)
                        if function is not None:
                            if function.name:
                                call["name"] = function.name
                            if function.arguments:
                                call["arguments"] += function.arguments
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
        # Reported outside the try: a callback failure is the caller's, not the
        # backend's, and a stream torn down early must dispatch nothing.
        if pending and on_tool_calls is not None:
            on_tool_calls(
                [
                    ToolCall(
                        id=call["id"], name=call["name"], arguments=call["arguments"]
                    )
                    for _index, call in sorted(pending.items())
                ]
            )
        logger.info("stream done | tool_calls=%d", len(pending))

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


@dataclass(frozen=True)
class ScriptedRound:
    """One scripted request/response round for ``TestProvider``.

    ``tokens`` is the text the round streams (possibly empty, for a round that
    is nothing but a tool call) and ``tool_calls`` the calls it ends in (empty
    for an ordinary text round).
    """

    tokens: list[str]
    tool_calls: list[ToolCall] = field(default_factory=list)


class TestProvider:
    """Test adapter that replays a scripted script, never touching the network.

    ``TestProvider(tokens)`` is the plain single-round form: every ``stream``
    call yields exactly those tokens. Pass ``rounds`` instead to script a
    multi-round tool turn — consecutive ``stream`` calls replay consecutive
    rounds, each yielding its text and then reporting its tool calls through
    ``on_tool_calls``. Once the script runs out its **last round repeats**, so a
    final round that asks for a tool again models a model that never stops
    searching, while a script ending in a text round simply settles.

    ``tools_seen`` records the ``tools`` argument of every ``stream`` call in
    order, so a caller's tool-offering decisions (offered / withheld on the final
    round) are observable without reaching into the provider. ``messages_seen``
    does the same for the ``messages`` argument, which is how a test can assert
    what the model was actually told — notably that a tool result carried an
    explanation rather than the content it stood in for.
    """

    def __init__(
        self,
        tokens: list[str] | None = None,
        usage: Usage | None = None,
        rounds: list[ScriptedRound] | None = None,
    ) -> None:
        self._rounds = rounds if rounds else [ScriptedRound(tokens or [])]
        self._usage = usage
        self._next_round = 0
        self.tools_seen: list[list[dict] | None] = []
        self.messages_seen: list[list[dict]] = []

    async def stream(
        self,
        messages: list[dict],
        model: str,
        on_usage: Callable[[Usage], None] | None = None,
        tools: list[dict] | None = None,
        on_tool_calls: Callable[[list[ToolCall]], None] | None = None,
    ) -> AsyncIterator[str]:
        self.tools_seen.append(tools)
        self.messages_seen.append(list(messages))
        scripted = self._rounds[min(self._next_round, len(self._rounds) - 1)]
        self._next_round += 1
        for token in scripted.tokens:
            yield token
        if scripted.tool_calls and on_tool_calls is not None:
            on_tool_calls(list(scripted.tool_calls))
        if self._usage is not None and on_usage is not None:
            on_usage(self._usage)

    async def check_connectivity(self, model: str) -> tuple[bool, str]:
        return True, "ok"
