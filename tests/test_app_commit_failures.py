"""Pilot tests for graceful commit failure (PRD Sprint 3, Task 13a).

A ``Ctrl+S`` commit whose range is rejected by ``_validate_compress_range``
(a range containing an existing K, or a live turn streaming — the non-tip guard
was deleted in task 22, so a middle range now commits and is covered elsewhere)
must **not** let the ``ValueError`` propagate: propagation soft-locks
the editor and the whole app stops processing input (unrecoverable short of a
restart). Instead the app surfaces the guard message as a transient hint
(task 42), keeps the editor open so the user can adjust, and stays responsive.

The oracle is the Task 13a acceptance criterion, asserted through the public
``describe_state()`` snapshot: no exception escapes (the test would error), the
guard message shows as a transient hint, no new K is committed, and a subsequent
keypress still changes app state (the editor closes on Esc).
"""

import asyncio

from textual.widgets import TextArea

from ctx.core.provider import TestProvider as CannedProvider
from ctx.ui.app import ChatApp
from ctx.ui.widgets.input_bar import InputBar


class _BlockingProvider:
    """Yields its first tokens, then blocks on ``gate`` before the next token.

    Models an LLM suspended mid-stream so ``core.streaming`` stays True while the
    test drives the editor — the realistic "commit while a turn is in flight".
    """

    def __init__(self, before: list[str], gate: asyncio.Event) -> None:
        self._before = before
        self._gate = gate

    async def stream(self, messages, model, on_usage=None):  # type: ignore[no-untyped-def]
        for token in self._before:
            yield token
        await self._gate.wait()
        yield "AFTER"

    async def check_connectivity(self, model):  # type: ignore[no-untyped-def]
        return (True, "ok")


def _app(repo, workspace) -> ChatApp:
    return ChatApp(
        provider=CannedProvider(["ok"]),
        workspace=workspace,
        storage=repo,
    )


async def _two_turns(app) -> None:
    await app.on_input_bar_submitted(InputBar.Submitted("first"))
    await app.workers.wait_for_complete()
    await app.on_input_bar_submitted(InputBar.Submitted("second"))
    await app.workers.wait_for_complete()


def _compression_nodes(app) -> list[dict]:
    return [n for n in app.describe_state()["nodes"] if n["node_type"] == "compression"]


def _hint_shown(app, needle: str) -> bool:
    # Refusals surface as transient hints, not graph nodes (task 42).
    hint = app.describe_state()["last_hint"]
    return hint is not None and needle in hint.lower()


async def test_commit_while_streaming_breadcrumbs_and_stays_responsive(repo, workspace):
    # Trigger (2): a real turn is streaming (H2 guard) — `c` has no streaming
    # gate, so the editor opens fine and Ctrl+S then hits the guard.
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _two_turns(app)
        await pilot.press("escape")
        await pilot.press("home")
        await pilot.press("v", "down", "down", "down")  # valid tip range
        await pilot.press("c")
        app.query_one("#compress-output", TextArea).text = "SUMMARY"

        gate = asyncio.Event()
        app.core._provider = _BlockingProvider(["x"], gate)
        await app.on_input_bar_submitted(InputBar.Submitted("third"))
        for _ in range(200):
            if app.core.streaming:
                break
            await pilot.pause()
        assert app.core.streaming

        await pilot.press("ctrl+s")

        assert _compression_nodes(app) == []
        assert app.describe_state()["compression_editor"]["open"] is True
        # The refusal comes from the explicit UI-layer stream guard (task 28),
        # not the core ValueError catch — assert its exact message.
        assert _hint_shown(app, "cannot commit while a response is streaming")

        # Let the blocked stream finish so teardown does not hang.
        gate.set()
        await app.workers.wait_for_complete()


async def test_commit_range_containing_k_breadcrumbs_and_stays_responsive(repo, workspace):
    # Trigger (3): a range that contains an already-committed K (Q7 flat guard).
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _two_turns(app)

        # First fold a valid tip suffix (last two nodes) into a K.
        await pilot.press("escape")
        await pilot.press("home", "down", "down", "down")  # cursor on the tip
        await pilot.press("v", "up")  # range = last two nodes (ends at tip)
        await pilot.press("c")
        app.query_one("#compress-output", TextArea).text = "FIRST K"
        await pilot.press("ctrl+s")
        assert len(_compression_nodes(app)) == 1  # view is now [n0, n1, K]

        # Now select the whole view (which includes the K) and try to compress it.
        await pilot.press("home")
        await pilot.press("v", "down", "down")  # [n0, n1, K]
        await pilot.press("c")
        app.query_one("#compress-output", TextArea).text = "SECOND SUMMARY"
        await pilot.press("ctrl+s")

        # Still exactly one K — the nested commit was rejected, not applied.
        assert len(_compression_nodes(app)) == 1
        assert app.describe_state()["compression_editor"]["open"] is True
        assert _hint_shown(app, "compression node")

        await pilot.press("escape")
        assert app.describe_state()["compression_editor"]["open"] is False
