"""Pilot tests for the compression *draft editor* (PRD Sprint 3, Task 7; Q4).

The editor is a left-pane 2-split shown in place of the ``DetailInspector``:
``c`` in Edit mode opens it on the active selection (prefilled default prompt,
empty output); ``/compress`` with no selection breadcrumbs instead of opening;
``Esc`` cancels for free (editor closes, inspector restored, selection kept).

The oracle is the Task 7 acceptance criterion, asserted through the public
``describe_state()`` snapshot (``compression_editor`` = {open, prompt, output})
and the CSS ``display`` state the qa-tester harness can query.
"""

from ctx.core.conversation import DEFAULT_COMPRESSION_PROMPT
from ctx.core.provider import TestProvider as CannedProvider
from ctx.ui.app import ChatApp
from ctx.ui.widgets.compression_editor import CompressionEditor
from ctx.ui.widgets.detail_inspector import DetailInspector
from ctx.ui.widgets.input_bar import InputBar


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


async def test_c_opens_editor_with_default_prompt_and_empty_output(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _two_turns(app)

        await pilot.press("escape")  # → Edit mode
        await pilot.press("home")  # cursor on the first node
        await pilot.press("v", "down")  # anchor a 2-node range
        await pilot.press("c")

        state = app.describe_state()
        editor_state = state["compression_editor"]
        assert editor_state["open"] is True
        assert editor_state["prompt"] == DEFAULT_COMPRESSION_PROMPT
        assert editor_state["output"] == ""
        # The editor occupies the left pane; the inspector is hidden behind it.
        assert app.query_one(CompressionEditor).display is True
        assert app.query_one(DetailInspector).display is False


async def test_c_on_single_node_opens_editor(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _two_turns(app)

        await pilot.press("escape")  # → Edit mode (cursor on last node)
        await pilot.press("c")  # no anchor → range-of-one on the selected node

        assert app.describe_state()["compression_editor"]["open"] is True


async def test_compress_command_no_selection_breadcrumbs_editor_closed(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test():
        await _two_turns(app)  # stays in Insert mode → no selection

        await app.on_input_bar_submitted(InputBar.Submitted("/compress"))

        state = app.describe_state()
        assert state["compression_editor"]["open"] is False
        assert app.query_one(CompressionEditor).display is False
        last = state["nodes"][-1]
        assert last["role"] == "system"
        assert last["content"] == "Select a range first: v in Edit mode"


async def test_esc_closes_editor_restores_inspector_keeps_selection(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _two_turns(app)

        await pilot.press("escape")  # → Edit mode
        await pilot.press("home")
        await pilot.press("v", "down")  # 2-node range
        await pilot.press("c")
        range_before = app.describe_state()["range_selection"]
        assert len(range_before) == 2

        await pilot.press("escape")  # cancels the editor for free

        state = app.describe_state()
        assert state["compression_editor"]["open"] is False
        assert state["mode"] == "edit"  # still in Edit, not toggled to Insert
        assert state["range_selection"] == range_before  # selection preserved
        assert app.query_one(DetailInspector).display is True
        assert app.query_one(CompressionEditor).display is False
