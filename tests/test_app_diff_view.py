"""Pilot tests for the full-screen context-diff view (PRD Sprint 3, Task 20;
ADR-0016 concern "b", Q12, A#3 §4).

``g d`` on a **drifted assistant** turn opens a right-pane replacement that
block-aligns the turn's generation-time context (left) against the now-view
(right) by node id; a K still deep-dives (one navigation family). On open the
H4 tripwire recomputes the turn's context hash and, on mismatch or a missing
hash, shows a "reconstruction may be inexact" banner. ``Ctrl+o`` / ``Esc`` pop
one level (restoring the live view); ``i`` exits fully.

The acceptance oracle reuses the Task 19 drift setup: ``U1,A1`` → compress
``[U1,A1]`` → ``U2,A2`` → expand ``K``. ``A2`` then saw ``K`` (folded) but the
now-view is ``[U1,A1,U2]``, so ``g d`` on ``A2`` shows one changed region
``left=[K]`` ⟷ ``right=[U1,A1]``.
"""

from textual.widgets import TextArea

from ctx.core.provider import TestProvider as CannedProvider
from ctx.ui.app import ChatApp
from ctx.ui.widgets.diff_view import DiffView
from ctx.ui.widgets.input_bar import InputBar
from ctx.ui.widgets.message_list import MessageList


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
    """U1,A1 → compress [U1,A1] → U2,A2 → expand K, then select A2."""
    await _turn(app, "first")  # → U1, A1

    await pilot.press("escape")  # → Edit
    await pilot.press("home")  # cursor on U1
    await pilot.press("v", "down")  # range = [U1, A1]
    await pilot.press("c")  # open the draft editor
    app.query_one("#compress-output", TextArea).text = "SUMMARY"
    await pilot.press("ctrl+s")  # commit → view = [K]

    await _turn(app, "second")  # → K, U2, A2 (A2 saw K)

    if app.mode == "edit":
        await pilot.press("escape")  # → Insert
    await pilot.press("escape")  # → Edit, tip selected
    await pilot.press("home")  # → K
    await pilot.press("x")  # expand → view = [U1, A1, U2, A2]

    # Land the cursor on the drifted assistant turn A2 (the last node).
    await pilot.press("down", "down", "down")


async def _middle_compress_scenario(app, pilot) -> tuple[str, str]:
    """U1,A1,U2,A2 → middle-compress [U1,A1] → view [K,U2,A2]; select A2.

    Returns (u1_id, a1_id) — the folded (off-view) children, captured before the
    compress. This exercises task 22's deleted tip guard: the range [U1,A1] does
    NOT end at the active leaf (A2), yet now folds.
    """
    await _turn(app, "first")  # → U1, A1
    await _turn(app, "second")  # → U2, A2; view = [U1, A1, U2, A2]

    view0 = app.core.nodes
    u1, a1 = view0[0].id, view0[1].id

    await pilot.press("escape")  # → Edit
    await pilot.press("home")  # cursor on U1
    await pilot.press("v", "down")  # range = [U1, A1] — NOT the tip
    await pilot.press("c")  # open the draft editor
    app.query_one("#compress-output", TextArea).text = "SUMMARY"
    await pilot.press("ctrl+s")  # commit → view = [K, U2, A2]

    if app.mode == "insert":
        await pilot.press("escape")  # → Edit
    await pilot.press("home")  # → K
    await pilot.press("down", "down")  # → U2 → A2 (the drifted turn)
    return u1, a1


def _k_id(app) -> str:
    return str(next(n.id for n in app.core.all_nodes() if n.node_type == "compression"))


async def test_gd_on_drifted_assistant_opens_diff_region(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)
        assert app._get_selected_node().role == "assistant"

        await pilot.press("g", "d")

        view = app.core.nodes  # [U1, A1, U2, A2]
        u1, a1 = view[0].id, view[1].id
        k = _k_id(app)

        diff = app.describe_state()["diff_view"]
        assert diff["open"] is True
        assert diff["warning"] is False
        assert diff["regions"] == [{"left": [k], "right": [u1, a1]}]

        # The DiffView is shown in place of the message list.
        assert app.query_one(DiffView).display is True
        assert app.query_one(MessageList).display is False
        # Breadcrumb reflects the diff family.
        assert app.describe_state()["deep_dive"]["breadcrumb"][-1].startswith("Diff")


async def test_diff_warning_on_tampered_ctx_hash(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)

        # Corrupt the turn's immutable generation-hash, then (re)open the diff.
        app.core.nodes[-1].meta["ctx_hash"] = "tampered-not-a-real-hash"
        await pilot.press("g", "d")

        diff = app.describe_state()["diff_view"]
        assert diff["open"] is True
        assert diff["warning"] is True


async def test_ctrl_o_restores_live_view(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)
        await pilot.press("g", "d")
        assert app.describe_state()["diff_view"]["open"] is True

        await pilot.press("ctrl+o")

        assert app.describe_state()["diff_view"]["open"] is False
        assert app.query_one(DiffView).display is False
        assert app.query_one(MessageList).display is True


async def test_gd_on_non_drifted_assistant_does_nothing(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)
        # A1 (index 1) never drifted; g d there must not open the diff.
        await pilot.press("home")  # U1
        await pilot.press("down")  # A1
        assert app._get_selected_node().role == "assistant"

        await pilot.press("g", "d")

        assert app.describe_state()["diff_view"]["open"] is False
        assert app.query_one(MessageList).display is True


def _drill_text(app) -> tuple[str, str]:
    """Concatenated left / right block text of the drilled region as rendered."""
    from textual.widgets import Static

    sides = app.query_one(DiffView).query("#diff-drill .diff-side")
    cols = [" ".join(str(s.render()) for s in side.query(Static)) for side in sides]
    return cols[0], cols[1]


async def test_enter_drills_into_cursored_region(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)
        await pilot.press("g", "d")  # diff overview on A2

        view = app.core.nodes  # [U1, A1, U2, A2]
        u1, a1 = view[0].id, view[1].id
        k = _k_id(app)

        assert app.describe_state()["diff_view"]["drill"] is None

        await pilot.press("enter")  # drill into the region

        diff = app.describe_state()["diff_view"]
        assert diff["open"] is True
        assert diff["drill"] == {"left": [k], "right": [u1, a1]}
        # A breadcrumb level is pushed for the drilled region.
        assert app.describe_state()["deep_dive"]["breadcrumb"][-1] == "Region"

        # The drilled region renders K's summary on the left, the verbatim
        # originals on the right (H6 many-to-many block sequences).
        left, right = _drill_text(app)
        assert "SUMMARY" in left
        assert "first" in right and "ok" in right


async def test_ctrl_o_from_drill_returns_to_overview(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)
        await pilot.press("g", "d")
        await pilot.press("enter")  # drill in
        assert app.describe_state()["diff_view"]["drill"] is not None

        await pilot.press("ctrl+o")  # back to the overview, one level

        diff = app.describe_state()["diff_view"]
        assert diff["open"] is True  # still in the diff, not the live view
        assert diff["drill"] is None
        assert diff["regions"]  # overview regions intact
        assert app.query_one(DiffView).display is True
        assert app.query_one(MessageList).display is False


async def test_i_from_drill_exits_all_the_way(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)
        await pilot.press("g", "d")
        await pilot.press("enter")  # drill in
        assert app.describe_state()["diff_view"]["drill"] is not None

        await pilot.press("i")  # exit the whole family

        assert app.describe_state()["diff_view"]["open"] is False
        assert app.mode == "insert"
        assert app.query_one(MessageList).display is True


# --- task 22: middle compress makes an earlier turn drift ---------------------

async def test_middle_compress_earlier_turn_drifts(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        u1, a1 = await _middle_compress_scenario(app, pilot)
        # The selected turn is the drifted A2 (last node of the folded view).
        assert app._get_selected_node().role == "assistant"
        k = _k_id(app)

        await pilot.press("g", "d")

        diff = app.describe_state()["diff_view"]
        assert diff["open"] is True
        assert diff["warning"] is False
        # A2 saw [U1, A1] verbatim; the now-view folds them into K.
        assert diff["regions"] == [{"left": [u1, a1], "right": [k]}]
        assert app.query_one(DiffView).display is True
        assert app.query_one(MessageList).display is False
