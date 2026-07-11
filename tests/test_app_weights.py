"""Pilot test for per-node weight % wiring in ChatApp (PRD Sprint 1, Task 3).

The first ``App.run_test()`` test in the repo. It drives a real user turn plus a
canned assistant reply through ChatApp and asserts the observable ``weight_pct``
values in ``describe_state()`` — the public state snapshot the qa-tester harness
also reads. The oracle is the PRD Task 3 acceptance criterion, not the
implementation: model-bound turns carry a numeric percentage, the default
"context"-basis percentages sum to ~100, and a system breadcrumb (which never
reaches the model) carries no weight.
"""

from ctx.ui.widgets.input_bar import InputBar


async def test_user_and_assistant_nodes_have_numeric_context_basis_weights(
    app_factory
):
    app = app_factory(tokens=["Hello", " there", ", friend!"])
    async with app.run_test():
        await app.on_input_bar_submitted(InputBar.Submitted("what is a deep module?"))
        await app.workers.wait_for_complete()
        state = app.describe_state()

    nodes = state["nodes"]
    user = next(n for n in nodes if n["role"] == "user")
    assistant = next(n for n in nodes if n["role"] == "assistant")

    # Both turns reach the model, so both show a real percentage (not the
    # "--%" placeholder that None renders as).
    assert isinstance(user["weight_pct"], int)
    assert isinstance(assistant["weight_pct"], int)

    # Default basis is "context": the share-of-conversation percentages of the
    # model-bound nodes sum to ~100 (modulo integer rounding of each entry).
    present = [n["weight_pct"] for n in nodes if n["weight_pct"] is not None]
    assert present  # at least the two turns contribute
    assert abs(sum(present) - 100) <= 2


async def test_system_breadcrumb_carries_no_weight(app_factory):
    app = app_factory()
    async with app.run_test():
        await app.on_input_bar_submitted(InputBar.Submitted("hello"))
        await app.workers.wait_for_complete()
        # Bare "/model" raises a "Current model: …" system breadcrumb — a node
        # that does not go to the model.
        await app.on_input_bar_submitted(InputBar.Submitted("/model"))
        state = app.describe_state()

    system = next(n for n in state["nodes"] if n["role"] == "system")
    assert system["weight_pct"] is None
