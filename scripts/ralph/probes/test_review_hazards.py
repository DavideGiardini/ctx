"""Throwaway review probes: diff-view gating gaps + dive mount gaps."""

import pytest
from textual.widgets import TextArea

from ctx.core.provider import TestProvider as CannedProvider
from ctx.core.storage import ConversationRepository
from ctx.core.workspace import Workspace
from ctx.ui.app import ChatApp
from ctx.ui.widgets.compression_editor import CompressionEditor
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


async def test_c_in_diff_view_opens_editor_over_diff(repo, workspace):
    """`c` while the diff view is open: gated on dive stack but not diff."""
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)
        await pilot.press("g", "d")
        assert app.describe_state()["diff_view"]["open"] is True

        await pilot.press("c")
        editor_open = app.query_one(CompressionEditor).is_open
        diff_open = app.describe_state()["diff_view"]["open"]
        print(f"\nEDITOR OPEN WHILE DIFF OPEN: editor={editor_open} diff={diff_open}")
        assert not editor_open, "BUG: compression editor opened over the diff view"


async def test_v_in_diff_view_makes_first_esc_dead(repo, workspace):
    """`v` while diff open sets an invisible range anchor; Esc then clears it
    (dead keypress) instead of popping the diff."""
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)
        await pilot.press("g", "d")
        assert app.describe_state()["diff_view"]["open"] is True

        await pilot.press("v")
        anchored = app._range_anchor_id is not None
        await pilot.press("escape")
        diff_still_open = app.describe_state()["diff_view"]["open"]
        print(f"\nANCHORED IN DIFF: {anchored}; diff open after Esc: {diff_still_open}")
        assert not (anchored and diff_still_open), (
            "BUG: v anchored a range inside the diff view and the first Esc "
            "cleared it invisibly instead of popping the diff"
        )


async def test_x_in_diff_view_mutates_under_diff(repo, workspace):
    """`x` (expand) while a diff is open mutates the graph under the open diff."""
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        # Middle compress: U1,A1,U2,A2 -> K,U2,A2; A2 drifts.
        await _turn(app, "first")
        await _turn(app, "second")
        await pilot.press("escape")
        await pilot.press("home")
        await pilot.press("v", "down")
        await pilot.press("c")
        app.query_one("#compress-output", TextArea).text = "SUMMARY"
        await pilot.press("ctrl+s")
        if app.mode == "insert":
            await pilot.press("escape")
        await pilot.press("home")
        await pilot.press("down", "down")  # A2 (drifted)
        await pilot.press("g", "d")
        assert app.describe_state()["diff_view"]["open"] is True

        n_before = len(app.core.nodes)
        # Cursor selection is still the drifted assistant node -> "Not a
        # compression node" breadcrumb at minimum; but select the K first via
        # the live-list selection surviving under the diff? Instead simulate a
        # user pressing x directly (selection = A2).
        await pilot.press("x")
        n_after = len(app.core.nodes)
        state = app.describe_state()
        last = state["nodes"][-1]["content"] if state["nodes"] else ""
        print(f"\nX IN DIFF: nodes {n_before}->{n_after}; last node: {last!r}")
        print(f"diff still open: {state['diff_view']['open']}")
        # Breadcrumb got appended to the (hidden) list while the diff is open
        assert n_after == n_before, "x ran (breadcrumbed/mutated) under an open diff"


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


async def test_c_in_diff_then_commit_full_damage(repo, workspace):
    """Full damage path: c in diff -> edit summary -> Ctrl+S commit."""
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)
        await pilot.press("g", "d")
        assert app.describe_state()["diff_view"]["open"] is True

        await pilot.press("c")
        assert app.query_one(CompressionEditor).is_open
        app.query_one("#compress-output", TextArea).text = "SECOND-K"
        await pilot.press("ctrl+s")
        await pilot.pause()

        st = app.describe_state()
        ks = [n for n in app.core.nodes if n.node_type == "compression"]
        print(f"\nAFTER COMMIT-IN-DIFF: diff_open={st['diff_view']['open']}")
        print(f"message_list.display={app.query_one(MessageList).display}")
        print(f"diff regions now={st['diff_view']['regions']}")
        print(f"editor open={app.query_one(CompressionEditor).is_open}")
        print(f"K nodes in view={len(ks)}")
        print(f"focus={st['focus']} mode={st['mode']}")
        print(f"breadcrumb={st['deep_dive']['breadcrumb']}")
        # Now press Esc twice to see whether the user can get out cleanly.
        await pilot.press("escape")
        st2 = app.describe_state()
        print(f"after Esc: diff_open={st2['diff_view']['open']} "
              f"ml.display={app.query_one(MessageList).display}")
        assert len(ks) == 0, "BUG: a K was committed while the diff view was open"


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
