"""Pilot tests — transient UI hints are toasts, not graph nodes (PRD task 42).

Ephemeral guidance ("Write a summary before committing", …) must surface via a
transient hint (``describe_state()["last_hint"]``) and add **no** node to the
conversation graph the way ``core.add_system_message`` did. A durable breadcrumb
(a ``/model`` change) must still land as a persistent node — the correction must
not turn *every* system message transient.
"""

from pilot_helpers import open_editor_on_range, two_turns


async def test_empty_summary_commit_hints_without_adding_a_node(app_factory):
    app = app_factory()
    async with app.run_test() as pilot:
        await two_turns(app)
        await open_editor_on_range(pilot)  # open the draft editor, summary left empty

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
        await two_turns(app)
        before = len(app.describe_state()["nodes"])

        await app._handle_model_command("/model openai/gpt-4o")
        await app.workers.wait_for_complete()

        nodes = app.describe_state()["nodes"]
        assert len(nodes) > before
        assert any(n["role"] == "system" and "gpt-4o" in n["content"] for n in nodes)
