"""Pilot tests for expand — the Edit-mode ``x`` key (PRD Sprint 3, Task 13b;
originally Task 11; ADR-0016 A#3/A#5).

``x`` on a selected compression node ``K`` restores its folded children in place
(the non-destructive inverse of a commit): the children come back on the line,
``K`` leaves the view, the selection lands on the first restored child, and the
restored view round-trips through storage. A later turn then sees the children
verbatim — no ``<conversation_summary>`` wrapper. ``x`` on any other node
breadcrumbs "Not a compression node" and mutates nothing.

Task 13b removed the dead ``/expand`` slash command: expand is a selection-
dependent action, and a slash command can never carry a selection (entering
Insert to type it clears the selection). These tests therefore drive the real
``x`` key with ``pilot.press`` — deliberately NOT the old
``on_input_bar_submitted("/expand")`` back-door, which was the convention that
masked the CP4 defect.

The oracle is the acceptance criterion, asserted through the public
``describe_state()`` snapshot, ``app.core`` (for the graph), and a recording
provider (for the next turn's context).
"""

from textual.widgets import TextArea

from ctx.core.provider import TestProvider as CannedProvider
from ctx.ui.app import ChatApp
from ctx.ui.widgets.input_bar import InputBar


class _RecordingProvider:
    """Canned provider that captures the messages of the *last* stream call."""

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens
        self.last_messages: list[dict] | None = None

    async def stream(self, messages, model, on_usage=None):  # type: ignore[no-untyped-def]
        self.last_messages = messages
        for token in self._tokens:
            yield token

    async def check_connectivity(self, model):  # type: ignore[no-untyped-def]
        return True


def _app(repo, workspace, provider=None) -> ChatApp:
    return ChatApp(
        provider=provider or CannedProvider(["ok"]),
        workspace=workspace,
        storage=repo,
    )


async def _two_turns(app) -> None:
    await app.on_input_bar_submitted(InputBar.Submitted("first"))
    await app.workers.wait_for_complete()
    await app.on_input_bar_submitted(InputBar.Submitted("second"))
    await app.workers.wait_for_complete()


async def _compress_full_tip_range(app, pilot, summary: str) -> None:
    """Compress the whole (4-node) tip range into one K via the draft editor."""
    await pilot.press("escape")  # → Edit mode
    await pilot.press("home")  # cursor on the first node
    await pilot.press("v", "down", "down", "down")  # range = all 4 nodes (ends at tip)
    await pilot.press("c")  # open the draft editor
    app.query_one("#compress-output", TextArea).text = summary
    await pilot.press("ctrl+s")  # commit → one K in the view (Edit mode, no selection)


async def _select_tip_in_edit(app, pilot) -> None:
    """Land in Edit mode with the selection on the tip node.

    A commit leaves us in Edit mode with the selection cleared, so we bounce out
    to Insert and back: re-entering Edit re-selects the tip (the freshly folded
    K)."""
    if app.mode == "edit":
        await pilot.press("escape")  # → Insert
    await pilot.press("escape")  # → Edit, selects the tip


async def test_expand_restores_children_and_removes_k(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _two_turns(app)
        await _compress_full_tip_range(app, pilot, "SUMMARY")
        assert sum(
            1 for n in app.describe_state()["nodes"] if n["node_type"] == "compression"
        ) == 1

        # Re-enter Edit (selects the tip = K), then expand it with the key.
        await _select_tip_in_edit(app, pilot)
        assert app._get_selected_node().node_type == "compression"
        await pilot.press("x")

        state = app.describe_state()
        # The four children are back and no K survives in the view.
        assert not any(n["node_type"] == "compression" for n in state["nodes"])
        assert len(state["nodes"]) == 4
        # Selection moved to the first restored child.
        assert state["nodes"][0]["selected"] is True


async def test_expand_survives_restart(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _two_turns(app)
        conv_id = app.core.conversation_id
        await _compress_full_tip_range(app, pilot, "SUMMARY")
        await _select_tip_in_edit(app, pilot)
        await pilot.press("x")
        assert not any(
            n["node_type"] == "compression" for n in app.describe_state()["nodes"]
        )

    # A second app on the same DB resolves the identical expanded view (the E
    # event + cleared pointers round-trip).
    app2 = _app(repo, workspace)
    async with app2.run_test():
        app2.core.resume_conversation(conv_id)
        state = app2.describe_state()
        assert not any(n["node_type"] == "compression" for n in state["nodes"])
        assert len(state["nodes"]) == 4


async def test_next_turn_sees_children_verbatim_after_expand(repo, workspace):
    provider = _RecordingProvider(["reply"])
    app = _app(repo, workspace, provider=provider)
    async with app.run_test() as pilot:
        await _two_turns(app)
        await _compress_full_tip_range(app, pilot, "THE SUMMARY TEXT")
        await _select_tip_in_edit(app, pilot)
        await pilot.press("x")

        # Next turn: the recording provider must receive the children verbatim
        # and no compression summary wrapper.
        await app.on_input_bar_submitted(InputBar.Submitted("third"))
        await app.workers.wait_for_complete()

        blob = "\n".join(str(m.get("content", "")) for m in provider.last_messages)
        assert "<conversation_summary>" not in blob
        assert "THE SUMMARY TEXT" not in blob
        # The original turns' text is present again.
        assert "first" in blob
        assert "second" in blob


async def test_expand_on_non_compression_breadcrumbs(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _two_turns(app)
        await pilot.press("escape")  # Edit mode, cursor on the last (assistant) node
        assert app._get_selected_node().node_type != "compression"

        await pilot.press("x")

        state = app.describe_state()
        last = state["nodes"][-1]
        assert last["role"] == "system"
        assert last["content"] == "Not a compression node"
