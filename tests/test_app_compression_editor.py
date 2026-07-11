"""Pilot tests for the compression *draft editor* (PRD Sprint 3, Task 7; Q4).

The editor is a left-pane 2-split shown in place of the ``DetailInspector``:
``c`` in Edit mode opens it on the active selection (prefilled default prompt,
empty output); ``Esc`` cancels for free (editor closes, inspector restored,
selection kept).

The oracle is the Task 7 acceptance criterion, asserted through the public
``describe_state()`` snapshot (``compression_editor`` = {open, prompt, output})
and the CSS ``display`` state the qa-tester harness can query.
"""

from ctx.core.conversation import DEFAULT_COMPRESSION_PROMPT
from ctx.ui.widgets.app_footer import _HINTS
from ctx.ui.widgets.compression_editor import CompressionEditor
from ctx.ui.widgets.detail_inspector import DetailInspector
from ctx.ui.widgets.input_bar import InputBar


async def _two_turns(app) -> None:
    await app.on_input_bar_submitted(InputBar.Submitted("first"))
    await app.workers.wait_for_complete()
    await app.on_input_bar_submitted(InputBar.Submitted("second"))
    await app.workers.wait_for_complete()


async def test_c_opens_editor_with_default_prompt_and_empty_output(app_factory):
    app = app_factory()
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


async def test_c_prefills_editor_with_config_override(app_factory, monkeypatch, tmp_path):
    # Task 18: the editor's Top prefill reads the user-overridable
    # get_config()["compression"]["default_prompt"], not the hard-coded constant.
    import json

    import ctx.core.config

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"compression": {"default_prompt": "custom override"}}))
    monkeypatch.setattr(ctx.core.config, "CONFIG_PATH", config_path)

    app = app_factory()
    async with app.run_test() as pilot:
        await _two_turns(app)

        await pilot.press("escape")  # → Edit mode
        await pilot.press("c")  # open editor on the selected node

        assert app.describe_state()["compression_editor"]["prompt"] == "custom override"


async def test_c_on_single_node_opens_editor(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await _two_turns(app)

        await pilot.press("escape")  # → Edit mode (cursor on last node)
        await pilot.press("c")  # no anchor → range-of-one on the selected node

        assert app.describe_state()["compression_editor"]["open"] is True


async def test_esc_closes_editor_restores_inspector_keeps_selection(app_factory):
    app = app_factory()
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


async def test_footer_shows_editor_hint_while_open_then_restores(app_factory):
    """13i: the editor's own keys must be advertised while it is open, and the
    Edit-mode hint restored the moment it closes."""
    app = app_factory()
    async with app.run_test() as pilot:
        await _two_turns(app)

        await pilot.press("escape")  # → Edit mode
        assert app.describe_state()["footer"] == _HINTS["edit"]

        await pilot.press("c")  # open the editor
        assert app.describe_state()["compression_editor"]["open"] is True
        assert app.describe_state()["footer"] == _HINTS["editor"]

        await pilot.press("escape")  # cancels the editor
        assert app.describe_state()["compression_editor"]["open"] is False
        assert app.describe_state()["footer"] == _HINTS["edit"]
