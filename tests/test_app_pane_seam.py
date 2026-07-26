"""The vertical seam joins the horizontal rules that run into it.

Two CSS borders never meet — ``─`` fills its cell, ``│`` only paints the middle
of the next one — so the seam paints its own column and carries a junction glyph
on every row a rule arrives at. These assertions are on rendered characters
because that is the whole point of the widget; nothing below the glyph level can
tell a joined rule from a gapped one.
"""

from textual.geometry import Region

from ctx.ui.widgets.input_bar import InputBar
from ctx.ui.widgets.pane_seam import PaneSeam


def seam_glyphs(app) -> list[str]:
    """The characters the seam paints, top row to bottom."""
    seam = app.query_one(PaneSeam)
    seam.sync()
    strips = seam.render_lines(Region(0, 0, 1, seam.size.height))
    return [strip.text for strip in strips]


async def import_node(app, pilot):
    """Append an imported-file node — the 3-split inspector view, whose Prompt and
    Source splits each carry a rule running into the seam."""
    app.core.commit_import("notes.txt", "raw file text", extract="the extract", prompt="condense")
    await app._rebuild_message_list()
    app._lock_inspector_to_last()
    await pilot.pause()
    await pilot.pause()


async def test_detail_split_rules_meet_the_seam(app_factory):
    app = app_factory()
    async with app.run_test(size=(80, 24)) as pilot:
        await import_node(app, pilot)
        glyphs = seam_glyphs(app)

        # Prompt and Source each end in a rule, so two rows are left-tees.
        assert glyphs.count("┤") == 2
        assert set(glyphs) <= {"│", "┤", "├", "┼"}


async def test_input_rule_meets_the_seam_and_follows_it(app_factory):
    """The seam has no way to be told the input grew — it re-checks on idle, so
    the junction has to travel with the rule."""
    app = app_factory()
    async with app.run_test(size=(80, 24)) as pilot:
        assert seam_glyphs(app).index("├") > 0
        before = seam_glyphs(app).index("├")

        app.query_one(InputBar).text = "grow me " * 40
        await pilot.pause()
        await pilot.pause()

        assert seam_glyphs(app).index("├") < before


async def test_seam_is_plain_where_no_rule_arrives(app_factory):
    app = app_factory()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        glyphs = seam_glyphs(app)
        # An empty conversation shows the placeholder inspector — one rule, the
        # input's — so every other row is the bare vertical.
        assert glyphs.count("├") == 1
        assert glyphs.count("┤") == 0
        assert glyphs.count("│") == len(glyphs) - 1
