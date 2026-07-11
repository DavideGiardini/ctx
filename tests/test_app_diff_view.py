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

from textual.containers import VerticalScroll
from textual.widgets import TextArea

from ctx.ui.widgets.compression_editor import CompressionEditor
from ctx.ui.widgets.diff_view import DiffView
from ctx.ui.widgets.input_bar import InputBar
from ctx.ui.widgets.message_list import MessageList


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


async def test_gd_on_drifted_assistant_opens_diff_region(app_factory):
    app = app_factory()
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


async def test_diff_is_fullscreen_two_pane_compact_rows(app_factory):
    """Task 37: `g d` opens a full-screen two-pane diff whose panes render the
    turn's context as compact `MessageRow`s (not a plain-text dump). Opening it
    hides the body panes it replaces (the left inspector + input area); `Ctrl+o`
    restores them."""
    from ctx.core import reconstruction
    from ctx.ui.widgets.detail_inspector import DetailInspector
    from ctx.ui.widgets.message_row import MessageRow

    app = app_factory()
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)
        a2 = app._get_selected_node()

        await pilot.press("g", "d")

        diff = app.query_one(DiffView)
        # Full-screen: the panes the diff replaces are hidden.
        assert app.query_one(DetailInspector).display is False
        assert app.query_one("#input-area").display is False
        # Two side-by-side panes, each rendering the turn's context (as-of
        # generation left, now right) as compact rows aligned by node id.
        all_nodes = app.core.all_nodes()
        want_left = [n.id for n in reconstruction.context_at_generation(all_nodes, a2.id)]
        want_right = [n.id for n in reconstruction.now_prefix(all_nodes, a2.id)]
        left_ids = [r.node.id for r in diff.query_one("#diff-left").query(MessageRow)]
        right_ids = [r.node.id for r in diff.query_one("#diff-right").query(MessageRow)]
        assert left_ids == want_left
        assert right_ids == want_right
        assert left_ids != right_ids  # the drift really shows a difference
        # The changed region's rows carry the highlight class.
        assert diff.query(".changed")

        await pilot.press("ctrl+o")

        assert app.query_one(DetailInspector).display is True
        assert app.query_one("#input-area").display is True


async def test_diff_warning_on_tampered_ctx_hash(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)

        # Corrupt the turn's immutable generation-hash, then (re)open the diff.
        app.core.nodes[-1].meta["ctx_hash"] = "tampered-not-a-real-hash"
        await pilot.press("g", "d")

        diff = app.describe_state()["diff_view"]
        assert diff["open"] is True
        assert diff["warning"] is True


async def test_ctrl_o_restores_live_view(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)
        await pilot.press("g", "d")
        assert app.describe_state()["diff_view"]["open"] is True

        await pilot.press("ctrl+o")

        assert app.describe_state()["diff_view"]["open"] is False
        assert app.query_one(DiffView).display is False
        assert app.query_one(MessageList).display is True


async def test_gd_on_non_drifted_assistant_does_nothing(app_factory):
    app = app_factory()
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
    """Concatenated left / right block content of the drilled region's rows."""
    from ctx.ui.widgets.message_row import MessageRow

    def _side(pane_id: str) -> str:
        rows = app.query_one(pane_id).query(MessageRow)
        return " ".join(r._content for r in rows)

    return _side("#diff-drill-left"), _side("#diff-drill-right")


async def test_enter_drills_into_cursored_region(app_factory):
    app = app_factory()
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


async def test_ctrl_o_from_drill_returns_to_overview(app_factory):
    app = app_factory()
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


async def test_i_from_drill_exits_all_the_way(app_factory):
    app = app_factory()
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

async def test_middle_compress_earlier_turn_drifts(app_factory):
    app = app_factory()
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


# --- task 50: equal-height aligned regions (blank-padded shorter side) --------


async def test_diff_regions_are_row_aligned_across_panes(app_factory):
    """Task 50: a changed region whose two sides differ in row count must occupy
    equal vertical space in both panes — the shorter side is blank-padded with
    filler rows. Here the changed region is [U1,A1] (2 rows, left) ⟷ [K] (1 row,
    right), so the right pane gains one filler and both panes hold the same total
    number of row slots."""
    from textual.widgets import Static

    from ctx.ui.widgets.diff_view import DiffView

    app = app_factory()
    async with app.run_test() as pilot:
        await _middle_compress_scenario(app, pilot)  # cursor on drifted A2
        await pilot.press("g", "d")
        assert app.describe_state()["diff_view"]["open"] is True

        diff = app.query_one(DiffView)
        left = list(diff.query_one("#diff-left", VerticalScroll).children)
        right = list(diff.query_one("#diff-right", VerticalScroll).children)

        # Both panes hold the same number of slots per region ⇒ same total.
        assert len(left) == len(right)
        # The shorter (right) side was padded: it gained a blank filler that is
        # not a MessageRow (so never a cursor target).
        fillers = [c for c in right if c.has_class("diff-filler")]
        assert len(fillers) == 1
        assert all(isinstance(f, Static) for f in fillers)
        # The left (taller) side needs no filler.
        assert not any(c.has_class("diff-filler") for c in left)


# --- task 51: locked bidirectional scroll + region-nav scrolls both -----------


async def _two_region_drift_scenario(app, pilot) -> None:
    """Eight turns, then compress two separate middle pairs so the last turn's
    diff overflows the pane and holds two changed regions (one near the top, one
    lower) — enough to exercise a manual scroll and a region-cursor jump."""
    for i in range(8):
        await _turn(app, f"turn {i}")

    await pilot.press("escape")  # → Edit
    view = app.core.nodes  # U0,A0,U1,A1,...,U7,A7
    pairs = [(view[2].id, view[3].id), (view[8].id, view[9].id)]  # turns 1 and 4

    for u_id, _a_id in pairs:
        app._select_message(u_id)
        await pilot.press("v", "down")  # range = [U, A]
        await pilot.press("c")
        app.query_one("#compress-output", TextArea).text = "SUMMARY"
        await pilot.press("ctrl+s")
        if app.mode == "insert":
            await pilot.press("escape")

    last = app.core.nodes[-1]
    assert last.role == "assistant"
    app._select_message(last.id)
    await pilot.press("g", "d")


async def test_diff_panes_scroll_locked_and_region_nav_scrolls_both(app_factory):
    """Task 51: the two overview panes share one vertical offset. Scrolling one
    pane moves the other to match, and a region-cursor move (`down`) scrolls both
    panes to the cursored region — after either, they report the same scroll_y."""
    app = app_factory()
    async with app.run_test() as pilot:
        await _two_region_drift_scenario(app, pilot)
        await pilot.pause()
        assert app.describe_state()["diff_view"]["open"] is True

        diff = app.query_one(DiffView)
        left = diff.query_one("#diff-left", VerticalScroll)
        right = diff.query_one("#diff-right", VerticalScroll)
        assert left.max_scroll_y > 0  # the diff overflows → the offset matters

        # (1) Scrolling one pane mirrors onto the other.
        left.scroll_to(y=left.max_scroll_y, animate=False, immediate=True)
        await pilot.pause()
        assert left.scroll_offset.y > 0
        assert right.scroll_offset.y == left.scroll_offset.y

        # (2) Reset, then a region-cursor jump scrolls BOTH to the lower region.
        left.scroll_to(y=0, animate=False, immediate=True)
        await pilot.pause()
        assert left.scroll_offset.y == right.scroll_offset.y == 0

        await pilot.press("down")  # region 0 → region 1 (lower in the diff)
        await pilot.pause()
        assert right.scroll_offset.y == left.scroll_offset.y


# --- task 27: the diff view inherits the deep-dive read-only gates -------------
# The selection/mutation Edit-mode keys (v/c/x) must be inert while a diff is
# open, exactly as they are while deep-diving — otherwise they anchor an
# invisible range on the hidden message list or mutate the graph under the diff
# (promoted from scripts/ralph/probes/test_review_hazards.py).


async def test_c_in_diff_view_is_a_noop(app_factory):
    """`c` while the diff view is open must not open the compression editor
    over the diff."""
    app = app_factory()
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)
        await pilot.press("g", "d")
        assert app.describe_state()["diff_view"]["open"] is True

        await pilot.press("c")

        assert app.query_one(CompressionEditor).is_open is False
        assert app.describe_state()["diff_view"]["open"] is True


async def test_v_in_diff_view_does_not_anchor_and_first_esc_pops(app_factory):
    """`v` while the diff is open must not set a range anchor, so the first Esc
    pops the diff rather than clearing an invisible selection (dead keypress)."""
    app = app_factory()
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)
        await pilot.press("g", "d")
        assert app.describe_state()["diff_view"]["open"] is True

        await pilot.press("v")
        assert app._range_anchor_id is None

        await pilot.press("escape")
        assert app.describe_state()["diff_view"]["open"] is False


async def test_x_in_diff_view_does_not_mutate(app_factory):
    """`x` (expand) while a diff is open must not mutate the graph or append a
    breadcrumb under the open diff."""
    app = app_factory()
    async with app.run_test() as pilot:
        await _middle_compress_scenario(app, pilot)  # cursor on drifted A2
        await pilot.press("g", "d")
        assert app.describe_state()["diff_view"]["open"] is True

        n_before = len(app.core.nodes)
        await pilot.press("x")

        assert len(app.core.nodes) == n_before
        assert app.describe_state()["diff_view"]["open"] is True


async def test_c_then_commit_in_diff_commits_nothing(app_factory):
    """Full damage path: `c` then `Ctrl+S` while the diff is open must not
    commit a range-of-one K on the drifted turn."""
    app = app_factory()
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)
        await pilot.press("g", "d")
        assert app.describe_state()["diff_view"]["open"] is True

        await pilot.press("c")
        assert app.query_one(CompressionEditor).is_open is False
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert not [n for n in app.core.nodes if n.node_type == "compression"]
        # A single Esc still pops the diff cleanly (no dead keypress).
        await pilot.press("escape")
        assert app.describe_state()["diff_view"]["open"] is False
        assert app.query_one(MessageList).display is True


async def _double_compress_and_dive(app, pilot) -> None:
    """U1,A1,U2,A2 → compress [U1,A1]=K1 → compress [U2,A2]=K2 → dive K2, then
    move the cursor onto the drifted frame node A2.

    A2 was generated seeing [U1,A1,U2] but its now-view folds [U1,A1] into K1,
    so A2 drifts — the `g d` diff branch is genuinely reachable on it (the test
    asserts the drift, so it can only pass because the dive gate blocks it, not
    because the turn happens to be undrifted)."""
    await _turn(app, "first")  # → U1, A1
    await _turn(app, "second")  # → U2, A2

    # compress [U1, A1] → K1
    await pilot.press("escape")
    await pilot.press("home")
    await pilot.press("v", "down")
    await pilot.press("c")
    app.query_one("#compress-output", TextArea).text = "K1"
    await pilot.press("ctrl+s")

    # compress [U2, A2] → K2 (view is [K1, U2, A2]; select U2..A2)
    if app.mode == "insert":
        await pilot.press("escape")
    await pilot.press("home")
    await pilot.press("down")  # U2
    await pilot.press("v", "down")  # [U2, A2]
    await pilot.press("c")
    app.query_one("#compress-output", TextArea).text = "K2"
    await pilot.press("ctrl+s")

    # dive into K2 (view [K1, K2]); land on the frame's second child A2
    if app.mode == "insert":
        await pilot.press("escape")
    await pilot.press("home")
    await pilot.press("down")  # K2
    await pilot.press("g", "d")  # deep-dive → originals [U2, A2]
    await pilot.press("down")  # A2


async def test_diff_does_not_open_inside_deep_dive(app_factory):
    """Task 30 decision: diff and deep-dive are mutually exclusive. `g d` on a
    drifted *frame* assistant turn while diving must NOT open a diff inside the
    dive — the dive stays active and its breadcrumb gains no "Diff" entry."""
    app = app_factory()
    async with app.run_test() as pilot:
        await _double_compress_and_dive(app, pilot)

        selected = app._get_selected_node()
        assert selected.role == "assistant"
        # Discriminating precondition: this frame turn really would drift, so the
        # only reason the diff stays shut is the dive gate.
        assert app._turn_has_drift(selected, app.core.all_nodes()) is True

        await pilot.press("g", "d")  # forbidden: diff inside a dive

        st = app.describe_state()
        assert st["diff_view"]["open"] is False
        assert st["deep_dive"]["active"] is True
        assert not any(bc.startswith("Diff") for bc in st["deep_dive"]["breadcrumb"])
        assert app.query_one(DiffView).display is False


async def test_ctrl_o_from_diff_restores_cursor_and_inspector(app_factory):
    """Task 30 (2): `Ctrl+o` from a diff opened in the live view restores the
    pre-diff cursor *and* the inspector's node, not just the pane display."""
    app = app_factory()
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)  # cursor on the drifted turn A2
        before = app.describe_state()
        sel_index = before["selected_index"]
        assert sel_index is not None
        assert before["selected_role"] == "assistant"

        await pilot.press("g", "d")
        assert app.describe_state()["diff_view"]["open"] is True

        await pilot.press("ctrl+o")

        after = app.describe_state()
        assert after["diff_view"]["open"] is False
        assert after["selected_index"] == sel_index
        assert after["selected_role"] == "assistant"
        # Inspector points back at the restored node (not blanked).
        assert after["detail"]["node_index"] == sel_index
        assert after["detail"]["node_role"] == "assistant"
