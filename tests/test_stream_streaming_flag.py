"""Behavior-only test for the streaming-flag invariant of ConversationCore.stream().

Locks in an intent-derived contract (see tests/specs/conversation_streaming_flag.md):
`core.streaming` must return to False after stream() finishes for ANY reason,
including when the pre-stream context build raises before the provider is contacted.
A stuck flag would permanently block compression ops. All assertions are on the
public API (streaming property, propagated exception, commit_compression result).
"""

import pytest

from ctx.core.conversation import ConversationCore


class _RaisingLoader:
    """Minimal workspace/loader whose read_file always raises.

    Implements only the surface stream()'s context build and setup() touch:
    ensure() (no-op), list_files() -> [], read_file() -> raises.

    It raises a plain RuntimeError, NOT OSError/ValueError: build_context
    deliberately swallows those two (rendering an error placeholder), so to model
    a genuine pre-stream context-build failure reaching stream()'s pre-region we
    raise a type that propagates.
    """

    def ensure(self) -> None:
        return None

    def list_files(self) -> list:
        return []

    def read_file(self, path: str) -> str:
        raise RuntimeError(f"context build blew up on {path}")


async def _collect(gen):
    return [chunk async for chunk in gen]


# C1 + C2: a failed context build must not leave `streaming` stuck True, and a
# subsequent compression on a valid range must therefore succeed.
async def test_streaming_flag_cleared_when_context_build_raises(repo, test_provider):
    core = ConversationCore(repo, test_provider(["ignored-token"]), _RaisingLoader())
    core.setup()

    # One /include'd context node so the pre-stream build actually reads a file.
    core.include_files(["docs/architecture.md"])

    user_node, assistant_node = core.submit("Summarize the architecture doc, please.")

    # C1: the loader error propagates out of the async generator.
    with pytest.raises(RuntimeError):
        await _collect(core.stream(assistant_node))

    # C1: flag must have returned to False despite the mid-build failure.
    assert core.streaming is False

    # C2: with the flag cleared, compression on a valid 1-node range succeeds.
    view = core.current_view()
    assert view, "expected the submitted turn to be present in the current view"
    target_id = user_node.id
    assert any(n.id == target_id for n in view), "chosen id must be in current_view()"

    result = core.commit_compression(
        target_id,
        target_id,
        "Folded the architecture summary turn.",
    )
    assert result is not None
    assert result.id is not None
