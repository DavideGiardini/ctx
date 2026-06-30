"""Tests for the header context-window gauge + ``~`` marker (PRD Sprint 1, Task 6).

Two layers:

* A pure unit test on ``AppHeader._gauge`` pins the visible ``~`` honesty marker
  (the crux of the task) without a running app.
* Pilot tests (``App.run_test()``) drive real turns through ChatApp and assert the
  ``context_gauge`` fields in ``describe_state()`` — the public snapshot the
  qa-tester harness also reads. The oracle is the PRD Task 6 acceptance criterion:
  ``approximate`` is True before any usage, False after a streamed turn with canned
  usage, True again (stale) once the node set changes, and an unknown model degrades
  to ``--%``/approximate without crashing.
"""

from ctx.core.provider import TestProvider as CannedProvider
from ctx.core.provider import Usage
from ctx.ui.app import ChatApp
from ctx.ui.widgets.app_header import AppHeader
from ctx.ui.widgets.input_bar import InputBar

# A canned usage close to a short message's local estimate, so the core's
# sanity check (prompt_tokens > 0, within ~10x of the local sum) accepts it and
# calibration is set — exercising the "anchored" gauge path.
_SANE_USAGE = Usage(prompt_tokens=12, completion_tokens=4, total_tokens=16)


def test_gauge_renders_tilde_only_when_approximate_and_numeric():
    # Exact figure: no marker.
    assert AppHeader._gauge(40, approximate=False) == "40% [====      ]"
    # Estimate: leading ~ qualifies the number.
    assert AppHeader._gauge(40, approximate=True) == "~40% [====      ]"
    # Unknown window: there is no number to qualify, so no ~ even when approximate.
    assert AppHeader._gauge(None, approximate=True) == "--% [          ]"
    assert AppHeader._gauge(None, approximate=False) == "--% [          ]"


async def test_gauge_approximate_until_anchored_then_stale_after_include(
    repo, workspace
):
    app = ChatApp(
        provider=CannedProvider(["Hi", " there"], usage=_SANE_USAGE),
        workspace=workspace,
        storage=repo,
    )
    async with app.run_test():
        # Before any turn: no provider anchor → the gauge is an estimate.
        assert app.describe_state()["context_gauge"]["approximate"] is True

        await app.on_input_bar_submitted(InputBar.Submitted("what is a deep module?"))
        await app.workers.wait_for_complete()
        # The turn reported sane usage → calibration set, node set matches the
        # anchor → the gauge is now exact.
        assert app.describe_state()["context_gauge"]["approximate"] is False

        # Adding context without a new turn drifts the node set off the anchor →
        # the absolute figure is an estimate again.
        app.core.include_files(["notes.md"])
        assert app.describe_state()["context_gauge"]["approximate"] is True


async def test_unknown_model_gauge_degrades_to_placeholder(repo, workspace):
    app = ChatApp(
        provider=CannedProvider(["ok"], usage=_SANE_USAGE),
        workspace=workspace,
        storage=repo,
    )
    async with app.run_test():
        app.core.model = "totally/nonexistent-model-xyz"
        gauge = app.describe_state()["context_gauge"]

    # Unknown model → no window → no percentage, marked approximate, no crash.
    assert gauge["pct"] is None
    assert gauge["approximate"] is True
