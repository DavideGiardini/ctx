"""Prompt-line behaviour: the seam above it, growth with wrapped text, and the
Enter / newline / arrow-key split.

These are layout and keystroke invariants, so they live here as Pilot tests
rather than in qa-tester: the headless harness cannot see computed heights or
borders (CLAUDE.md §Agent-driven testing).
"""

from textual.containers import Container, Horizontal

from ctx.ui.widgets.input_bar import InputBar


async def test_seam_separates_the_input_area_from_the_conversation(app_factory):
    """A rule is drawn along the top of the whole input region — above the
    suggestions popup when it is open, so the input never floats against the
    conversation."""
    app = app_factory()
    async with app.run_test():
        edge, _color = app.query_one("#input-area", Container).styles.border_top
        assert edge == "solid"


async def test_input_grows_as_the_text_wraps(app_factory):
    """Past the pane width the box gains a line instead of scrolling the text
    out of sight sideways."""
    app = app_factory()
    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)
        one_line = bar.size.height
        assert one_line == 1

        bar.text = "wrap me " * 30
        await pilot.pause()

        assert bar.size.height > one_line
        # The "> " marker stays put on the first line, shell-prompt style.
        assert app.query_one("#prompt-marker").size.height == 1
        assert app.query_one("#input-line", Horizontal).size.height == bar.size.height


async def test_growth_stops_at_the_cap(app_factory):
    """A very long message stops growing and scrolls inside the box, so it can
    never swallow the conversation above it."""
    app = app_factory()
    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)
        bar.text = "\n".join(f"line {i}" for i in range(60))
        await pilot.pause()

        assert bar.size.height == 10
        assert app.query_one("#messages").size.height > 0


async def test_enter_submits_while_shift_enter_breaks_the_line(app_factory):
    """Enter keeps meaning send; the newline TextArea natively binds it to moves
    to shift+enter (and alt+enter, for terminals that do not report the former)."""
    app = app_factory()
    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)
        bar.focus()

        await pilot.press("f", "i", "r", "s", "t")
        await pilot.press("shift+enter")
        await pilot.press("s", "e", "c", "o", "n", "d")
        await pilot.press("alt+enter")
        await pilot.press("t", "h", "i", "r", "d")
        assert bar.text == "first\nsecond\nthird"
        assert not app.core.nodes  # nothing sent yet

        await pilot.press("enter")
        await app.workers.wait_for_complete()
        assert [n.content for n in app.core.nodes if n.role == "user"] == [
            "first\nsecond\nthird"
        ]
        assert bar.text == ""  # accepted → cleared


async def test_arrows_walk_the_lines_when_no_command_menu_is_open(app_factory):
    """Up/Down are the command menu's keys only while the menu is live; in an
    ordinary message they do what they do in any text box."""
    app = app_factory()
    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)
        bar.focus()
        bar.text = "top\nbottom"
        bar.move_cursor(bar.document.end)
        await pilot.pause()

        await pilot.press("up")
        assert bar.cursor_location[0] == 0
        await pilot.press("down")
        assert bar.cursor_location[0] == 1


async def test_arrows_still_steer_the_command_menu(app_factory):
    """A bare ``/``-prefixed word is a live menu, and there Up/Down move the
    highlight rather than the cursor."""
    app = app_factory()
    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)
        bar.focus()
        await pilot.press("slash")
        assert bar.menu_active
        assert app.describe_state()["command_menu"]["selected"] == InputBar.COMMANDS[0]

        await pilot.press("down")
        assert app.describe_state()["command_menu"]["selected"] == InputBar.COMMANDS[1]

        # An argument closes the menu: the text is no longer a bare command word.
        await pilot.press("m", "space", "x")
        assert not bar.menu_active
        assert app.describe_state()["command_menu"] is None
