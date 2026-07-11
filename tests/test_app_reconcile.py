"""Pilot test for incremental message-list reconcile (PRD Sprint 3, Task 44).

A structural change (here: a compression commit) must mutate only the rows that
changed — the surviving rows keep their *same widget instances* rather than
being torn down and re-mounted (which blanked and repopulated the whole pane).
The oracle is the Task 44 acceptance: after a commit that folds the tail range,
the untouched leading rows are the identical objects they were before and the K
appears in place.
"""

from textual.widgets import TextArea

from ctx.core.provider import TestProvider as CannedProvider
from ctx.ui.app import ChatApp
from ctx.ui.widgets.input_bar import InputBar
from ctx.ui.widgets.message_list import MessageList, MessageWidget


def _app(repo, workspace) -> ChatApp:
    return ChatApp(
        provider=CannedProvider(["ok"]),
        workspace=workspace,
        storage=repo,
    )


async def _two_turns(app) -> None:
    await app.on_input_bar_submitted(InputBar.Submitted("first"))
    await app.workers.wait_for_complete()
    await app.on_input_bar_submitted(InputBar.Submitted("second"))
    await app.workers.wait_for_complete()


async def test_commit_preserves_surviving_widget_instances(repo, workspace):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _two_turns(app)  # view: [u1, a1, u2, a2]

        # Widget instances keyed by node id, before the commit.
        message_list = app.query_one(MessageList)
        before = {w.node.id: w for w in message_list.query(MessageWidget)}
        survivor_ids = [n.id for n in app.core.nodes[:2]]  # u1, a1 stay

        # Select the trailing two nodes and fold them into one K.
        await pilot.press("escape")  # → Edit mode
        await pilot.press("home", "down", "down")  # cursor on u2 (index 2)
        await pilot.press("v", "down")  # range = {u2, a2}
        await pilot.press("c")  # open editor
        app.query_one("#compress-output", TextArea).text = "SUMMARY"
        await pilot.press("ctrl+s")
        await pilot.pause()

        after = {w.node.id: w for w in message_list.query(MessageWidget)}
        # The leading rows survived as the *same* instances (not recreated).
        for nid in survivor_ids:
            assert after[nid] is before[nid]
        # Exactly the two survivors plus one new K row remain, K last & in place.
        assert len(after) == 3
        comp = [w for w in message_list.query(MessageWidget)
                if w.node.node_type == "compression"]
        assert len(comp) == 1
        assert comp[0] is message_list.query(MessageWidget).last()
