"""Throwaway review probes: diff-view gating gaps + dive mount gaps."""

import pytest
from textual.widgets import TextArea

from ctx.core.provider import TestProvider as CannedProvider
from ctx.core.storage import ConversationRepository
from ctx.core.workspace import Workspace
from ctx.ui.app import ChatApp
from ctx.ui.widgets.input_bar import InputBar
from ctx.ui.widgets.message_list import MessageList


@pytest.fixture
def workspace(tmp_path):
    ws = Workspace(tmp_path)
    ws.ensure()
    return ws


@pytest.fixture
def repo(tmp_path):
    repository = ConversationRepository(str(tmp_path / "conversations.db"))
    repository.init()
    return repository



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
    """U1,A1 -> compress [U1,A1] -> U2,A2 -> expand K, then select A2."""
    await _turn(app, "first")
    await pilot.press("escape")
    await pilot.press("home")
    await pilot.press("v", "down")
    await pilot.press("c")
    app.query_one("#compress-output", TextArea).text = "SUMMARY"
    await pilot.press("ctrl+s")
    await _turn(app, "second")
    if app.mode == "edit":
        await pilot.press("escape")
    await pilot.press("escape")
    await pilot.press("home")
    await pilot.press("x")
    await pilot.press("down", "down", "down")


async def test_model_command_mounts_into_dive_frame(repo, workspace):
    """/model while deep-diving mounts its reply widget inside the dive frame
    (13h#2 gated breadcrumb/connectivity/submit but not /model)."""
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _turn(app, "first")
        await pilot.press("escape")
        await pilot.press("home")
        await pilot.press("v", "down")
        await pilot.press("c")
        app.query_one("#compress-output", TextArea).text = "SUMMARY"
        await pilot.press("ctrl+s")
        if app.mode == "insert":
            await pilot.press("escape")
        await pilot.press("home")  # cursor on K
        await pilot.press("g", "d")  # deep-dive
        assert app.describe_state()["deep_dive"]["active"] is True

        ml = app.query_one(MessageList)
        widgets_before = len(list(ml.children))
        await app._handle_model_command("/model")  # query form: adds a system node
        await pilot.pause()
        widgets_after = len(list(ml.children))
        print(f"\nDIVE FRAME WIDGETS: {widgets_before} -> {widgets_after}")
        assert widgets_after == widgets_before, (
            "BUG: /model reply widget mounted inside the read-only dive frame"
        )


async def test_diff_can_open_inside_deep_dive(repo, workspace):
    """U1,A1,U2,A2 -> compress [U1,A1]=K1 -> compress [U2,A2]=K2 -> dive K2 ->
    g d on frame node A2 (drifted: K1 created after A2). Comment on _diff_view
    says diff and dive are 'mutually exclusive'."""
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _turn(app, "first")
        await _turn(app, "second")
        # compress [U1, A1] -> K1
        await pilot.press("escape")
        await pilot.press("home")
        await pilot.press("v", "down")
        await pilot.press("c")
        app.query_one("#compress-output", TextArea).text = "K1"
        await pilot.press("ctrl+s")
        # compress [U2, A2] -> K2 (view is [K1, U2, A2]; select U2..A2)
        if app.mode == "insert":
            await pilot.press("escape")
        await pilot.press("home")
        await pilot.press("down")  # U2
        await pilot.press("v", "down")  # [U2, A2]
        await pilot.press("c")
        app.query_one("#compress-output", TextArea).text = "K2"
        await pilot.press("ctrl+s")
        # dive into K2 (view [K1, K2]; select K2)
        if app.mode == "insert":
            await pilot.press("escape")
        await pilot.press("home")
        await pilot.press("down")  # K2
        await pilot.press("g", "d")  # deep-dive into K2's originals [U2, A2]
        st = app.describe_state()
        assert st["deep_dive"]["active"] is True
        # cursor on U2 (first child); move to A2
        await pilot.press("down")
        sel = app._get_selected_node()
        print(f"\nselected in dive: {sel.role} {sel.content!r}")
        await pilot.press("g", "d")  # diff on a drifted frame assistant?
        st2 = app.describe_state()
        print(f"diff open inside dive: {st2['diff_view']['open']}; "
              f"dive active: {st2['deep_dive']['active']}")
        print(f"breadcrumb: {st2['deep_dive']['breadcrumb']}")
        if st2["diff_view"]["open"]:
            await pilot.press("ctrl+o")  # pop diff
            st3 = app.describe_state()
            print(f"after pop: dive={st3['deep_dive']['active']} "
                  f"selected={st3['selected_index']} "
                  f"ml.display={app.query_one(MessageList).display}")
        assert not st2["diff_view"]["open"], (
            "diff opened while deep-diving (states claimed mutually exclusive)"
        )
