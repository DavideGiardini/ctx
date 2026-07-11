"""Layout regression for the drift `Δ` glyph vs. the weight-% slot (task 25).

Both live in a single right-docked ``.meta-slot`` row so they flow side by side
(Δ left of %) instead of overlapping into a garbled "2Δ%" — the bug qa-tester
kept seeing in character-grid screenshots when the two were each ``dock: right``
at the same edge. AGENTS.md limit (b) says the MCP harness cannot adjudicate
layout, so the invariant is locked here against the *computed regions* rather
than a screenshot: the drift cell must sit strictly left of the weight cell with
no overlap.
"""

from textual.app import App, ComposeResult
from textual.widgets import Static

from ctx.models.nodes import Node
from ctx.ui.widgets.message_list import MessageWidget


class _Host(App):
    def __init__(self, node: Node) -> None:
        super().__init__()
        self._node = node

    def compose(self) -> ComposeResult:
        yield MessageWidget(self._node)


async def test_drift_glyph_never_overlaps_weight_slot():
    node = Node.assistant("a reply that is long enough to fill the row", "c1")
    app = _Host(node)
    async with app.run_test(size=(80, 24)):
        widget = app.query_one(MessageWidget)
        widget.set_weight_pct(20)
        widget.set_drift(True)
        await app.workers.wait_for_complete()

        weight = widget.query_one(".weight", Static)
        drift = widget.query_one(".drift", Static)

        assert str(drift.render()) == "Δ"
        # No column overlap, and Δ sits to the left of the %.
        assert drift.region.right <= weight.region.x
        assert drift.region.width >= 1
        assert weight.region.width >= 1


async def test_wide_weight_value_still_clears_the_drift_glyph():
    """A three-digit % (or the "not in context" label) widens the weight slot;
    because both share one flow row, the Δ shifts left to stay clear instead of
    being overwritten by the extra digit."""
    node = Node.assistant("another reply long enough to fill the row width", "c1")
    app = _Host(node)
    async with app.run_test(size=(80, 24)):
        widget = app.query_one(MessageWidget)
        widget.set_weight_pct(100)
        widget.set_drift(True)
        await app.workers.wait_for_complete()

        weight = widget.query_one(".weight", Static)
        drift = widget.query_one(".drift", Static)

        assert str(weight.render()) == "100%"
        assert drift.region.right <= weight.region.x
