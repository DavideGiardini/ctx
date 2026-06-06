from collections.abc import Callable

from litellm import acompletion

from ctx.core.log import logger


async def check_connectivity(model: str) -> tuple[bool, str]:
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


async def stream_response(
    messages: list[dict],
    model: str,
    on_token: Callable[[str], None],
    on_done: Callable[[str], None],
    on_error: Callable[[Exception], None],
) -> None:
    full_text = ""
    try:
        logger.info("stream started | model=%s | messages=%d", model, len(messages))
        response = await acompletion(
            model=model,
            messages=messages,
            stream=True,
        )
        async for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                full_text += delta
                on_token(delta)
        logger.info("stream done | length=%d", len(full_text))
        on_done(full_text)
    except Exception as exc:
        logger.error("stream error: %s", exc)
        on_error(exc)