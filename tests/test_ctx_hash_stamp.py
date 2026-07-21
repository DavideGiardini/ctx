"""Regression guard: every committed assistant turn carries a ``ctx_hash`` stamp.

Under ctx0 (ADR-0017) the per-turn ``meta["ctx_hash"]`` stamp is write-only — the
reading surfaces that re-derived and compared it were subtracted, and the oracle
test that exercised the stamp went with them. The stamp itself is an explicit
keeper (the per-turn verification anchor, ADR-0016 A#3 §4), so this asserts the
observable black-box property directly: after a real driven turn, the committed
assistant node carries a valid sha256-hex ``ctx_hash``. A regression that drops
the stamp (e.g. during the Part B render redesign) fails here.
"""

import string

from ctx.core.conversation import ConversationCore

_HEXDIGITS = set(string.hexdigits.lower())


def _is_hex64(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in _HEXDIGITS for c in value)
    )


async def test_committed_turn_carries_ctx_hash(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["ok"]), workspace)
    core.setup()

    _user, assistant = core.submit("What is the capital of France?")
    async for _ in core.stream(assistant):
        pass
    core.end_turn(assistant)

    assert _is_hex64(assistant.meta.get("ctx_hash"))
