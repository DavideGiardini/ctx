"""Pilot tests for the context-drift indicator (PRD Sprint 3, Task 19;
ADR-0016 concern "b", Q12/A#1).

An **assistant** turn "drifts" when the context it saw at generation time no
longer matches the current now-view (``reconstruction.has_drift``). The UI marks
such turns with a single subtle glyph beside the weight slot, gated by
``ui.show_context_drift``; the flag is also exposed on every node in
``describe_state()`` (``"drift": bool``).

The oracle is the Task 19 acceptance criterion: build ``U1,A1`` → compress the
tip range ``[U1,A1]`` → add ``U2,A2`` (so ``A2`` sees ``K``) → expand ``K`` (the
13b Edit-mode ``x`` key). Now ``A2``'s context drifted (it saw ``K``, gone now)
while ``A1``'s did not. With the config off, no node drifts.
"""

import json

from textual.widgets import Static, TextArea

import ctx.core.config
from ctx.core.provider import TestProvider as CannedProvider
from ctx.ui.app import ChatApp
from ctx.ui.widgets.input_bar import InputBar
from ctx.ui.widgets.message_list import MessageWidget


def _app(repo, workspace) -> ChatApp:
    return ChatApp(
        provider=CannedProvider(["ok"]),
        workspace=workspace,
        storage=repo,
    )


async def _turn(app, text: str) -> None:
    await app.on_input_bar_submitted(InputBar.Submitted(text))
    await app.workers.wait_for_complete()


async def _drift_scenario(app, pilot) -> None:
    """U1,A1 → compress [U1,A1] → U2,A2 → expand K (the acceptance setup)."""
    await _turn(app, "first")  # → U1, A1

    # Compress the whole tip range [U1, A1] into one K via the draft editor.
    await pilot.press("escape")  # → Edit mode
    await pilot.press("home")  # cursor on U1
    await pilot.press("v", "down")  # range = [U1, A1]
    await pilot.press("c")  # open the draft editor
    app.query_one("#compress-output", TextArea).text = "SUMMARY"
    await pilot.press("ctrl+s")  # commit → view = [K], Edit mode, no selection

    await _turn(app, "second")  # → K, U2, A2 (A2 saw K in context)

    # Re-enter Edit, land on K (first node), and expand it with the 13b key.
    if app.mode == "edit":
        await pilot.press("escape")  # → Insert
    await pilot.press("escape")  # → Edit, selects the tip
    await pilot.press("home")  # → the K node
    assert app._get_selected_node().node_type == "compression"
    await pilot.press("x")  # expand → view = [U1, A1, U2, A2]


async def test_expanded_turn_drifts_and_prior_turn_does_not(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)

        nodes = app.describe_state()["nodes"]
        assert len(nodes) == 4
        a1, a2 = nodes[1], nodes[3]
        assert a1["role"] == "assistant" and a1["drift"] is False
        assert a2["role"] == "assistant" and a2["drift"] is True

        # The marker renders on the drifting turn and not the stable one.
        view = app.core.nodes
        a1_w = app.query_one(f"#msg-{view[1].id}", MessageWidget)
        a2_w = app.query_one(f"#msg-{view[3].id}", MessageWidget)
        assert a2_w.has_class("drifted")
        assert str(a2_w.query_one(".drift", Static).render()) != ""
        assert not a1_w.has_class("drifted")
        assert str(a1_w.query_one(".drift", Static).render()) == ""


async def test_no_drift_marker_when_config_disabled(repo, workspace, monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"ui": {"show_context_drift": False}}))
    monkeypatch.setattr(ctx.core.config, "CONFIG_PATH", config_path)

    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)

        nodes = app.describe_state()["nodes"]
        assert all(n["drift"] is False for n in nodes)
        for node in app.core.nodes:
            assert not app.query_one(f"#msg-{node.id}", MessageWidget).has_class("drifted")


async def test_gd_diff_is_noop_on_drifted_turn_when_config_disabled(
    repo, workspace, monkeypatch, tmp_path
):
    """With drift display off, ``g d`` on a drifted assistant turn opens nothing.

    The config flag gates *all* drift UI (task 24): no marker (covered above)
    and no diff drill either — otherwise the diff would open on a turn the UI
    otherwise presents as undrifted.
    """
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"ui": {"show_context_drift": False}}))
    monkeypatch.setattr(ctx.core.config, "CONFIG_PATH", config_path)

    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)  # view = [U1, A1, U2, A2], A2 drifted

        # Land the cursor on the drifted assistant turn A2 (the last node).
        await pilot.press("down", "down", "down")
        assert app._get_selected_node().id == app.core.nodes[3].id

        await pilot.press("g", "d")
        assert app.describe_state()["diff_view"]["open"] is False
