"""Pilot test for the compress *payload* — the single user-visible payoff of 3a
(PRD Sprint 3, Task 13c; ADR-0016).

Committing a compression must actually change what the model sees on the next
turn: the folded children leave the context and their summary ``K`` reaches the
provider wrapped in a ``<conversation_summary>``. The expand direction has a
recording-provider Pilot (``test_app_expand.py``); this is its mirror for the
compress direction, closing the coverage hole where a raw-``prev_id``-walk mutant
of ``stream``'s context build (children sent, K never sent) passed every test.

The oracle is the acceptance criterion, asserted through the messages a recording
provider actually receives on the turn *after* a commit.
"""

from conftest import RecordingProvider
from pilot_helpers import compress_range, two_turns

from ctx.ui.widgets.input_bar import InputBar


async def test_next_turn_sees_summary_not_children_after_compress(app_factory):
    provider = RecordingProvider(["reply"])
    app = app_factory(provider=provider)
    async with app.run_test() as pilot:
        await two_turns(app)
        await compress_range(app, pilot, "THE SUMMARY TEXT")
        # The whole tip range is folded into a single K.
        assert (
            sum(
                1
                for n in app.describe_state()["nodes"]
                if n["node_type"] == "compression"
            )
            == 1
        )

        # Next turn: the recording provider must receive the summary wrapped in a
        # <conversation_summary> and NOT the folded children's content.
        await app.on_input_bar_submitted(InputBar.Submitted("third"))
        await app.workers.wait_for_complete()

        blob = "\n".join(str(m.get("content", "")) for m in provider.captured)
        assert "<conversation_summary>" in blob
        assert "THE SUMMARY TEXT" in blob
        # The folded children's text must be gone (only the summary stands in).
        assert "first" not in blob
        assert "second" not in blob
        # The new turn itself still reaches the model.
        assert "third" in blob
