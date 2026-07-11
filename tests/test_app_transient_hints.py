"""Pilot tests — transient UI hints are toasts, not graph nodes (PRD task 42).

Ephemeral guidance ("Write a summary before committing", …) must surface via a
transient hint (``describe_state()["last_hint"]``) and add **no** node to the
conversation graph the way ``core.add_system_message`` did. A durable breadcrumb
(a ``/model`` change) must still land as a persistent node — the correction must
not turn *every* system message transient.
"""

from ctx.ui.widgets.input_bar import InputBar


async def _two_turns(app) -> None:
    await app.on_input_bar_submitted(InputBar.Submitted("first"))
    await app.workers.wait_for_complete()
    await app.on_input_bar_submitted(InputBar.Submitted("second"))
    await app.workers.wait_for_complete()


async def test_empty_summary_commit_hints_without_adding_a_node(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await _two_turns(app)
        await pilot.press("escape")
        await pilot.press("home")
        await pilot.press("v", "down", "down", "down")  # select a range
        await pilot.press("c")  # open the draft editor, summary left empty

        before = len(app.describe_state()["nodes"])
        await pilot.press("ctrl+s")  # commit with an empty summary → refused

        state = app.describe_state()
        assert state["last_hint"] == "Write a summary before committing (Ctrl+S)."
        # The hint left no trace in the graph.
        assert len(state["nodes"]) == before
        assert all(n["role"] != "system" for n in state["nodes"])


async def test_model_change_still_adds_a_durable_node(app_factory):
    app = app_factory()
    async with app.run_test():
        await _two_turns(app)
        before = len(app.describe_state()["nodes"])

        await app._handle_model_command("/model openai/gpt-4o")
        await app.workers.wait_for_complete()

        nodes = app.describe_state()["nodes"]
        assert len(nodes) > before
        assert any(n["role"] == "system" and "gpt-4o" in n["content"] for n in nodes)
