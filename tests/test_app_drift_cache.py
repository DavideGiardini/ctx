"""The per-refresh drift pass is memoized (PRD Sprint 3, Task 32).

``_node_drift`` re-folds the whole graph once per assistant node
(``reconstruction.has_drift``, O(n²)) and is called on every
``_refresh_token_ui`` *and* every ``describe_state()``. Task 32 caches the
parallel ``list[bool]`` keyed on a cheap signature that changes exactly when a
drift input does (a node/K/E enters the graph, a rewind, a conversation swap,
or the ``ui.show_context_drift`` flag flips). This proves the cache:

- two consecutive ``describe_state()`` calls on an unchanged graph → the second
  triggers **no** further ``has_drift`` recompute;
- a new commit (a K enters the graph) → the cache is invalidated and the pass
  recomputes.

The functional drift oracle stays owned by ``test_app_drift.py``; here we count
``reconstruction.has_drift`` calls to observe the memo, using the same setup.
"""

from test_app_drift import _drift_scenario
from textual.widgets import TextArea

import ctx.core.reconstruction as reconstruction_mod
from ctx.core.provider import TestProvider as CannedProvider
from ctx.ui.app import ChatApp


def _app(repo, workspace) -> ChatApp:
    return ChatApp(
        provider=CannedProvider(["ok"]),
        workspace=workspace,
        storage=repo,
    )


class _Counter:
    """Wraps ``reconstruction.has_drift`` preserving behavior while counting."""

    def __init__(self, monkeypatch):
        self.count = 0
        self._real = reconstruction_mod.has_drift
        monkeypatch.setattr(reconstruction_mod, "has_drift", self)

    def __call__(self, *args, **kwargs):
        self.count += 1
        return self._real(*args, **kwargs)


async def test_consecutive_snapshots_do_not_recompute(repo, workspace, monkeypatch):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)  # view = [U1, A1, U2, A2], A2 drifted

        counter = _Counter(monkeypatch)
        app._drift_cache = None  # cold start for a known baseline

        # First (cold) snapshot: a full pass folds the graph per assistant.
        app.describe_state()
        after_first = counter.count
        assert after_first > 0

        # Second snapshot, graph unchanged: served from cache, no recompute.
        app.describe_state()
        assert counter.count == after_first


async def test_new_commit_invalidates_cache(repo, workspace, monkeypatch):
    app = _app(repo, workspace)
    async with app.run_test() as pilot:
        await _drift_scenario(app, pilot)  # view = [U1, A1, U2, A2]

        counter = _Counter(monkeypatch)
        app._drift_cache = None  # cold start
        app.describe_state()  # warm the cache
        warmed = counter.count
        assert warmed > 0

        app.describe_state()  # cache hit
        assert counter.count == warmed

        # A new commit folds [U1, A1] into a fresh K — a node enters the graph,
        # so the signature changes and the next pass must recompute.
        await pilot.press("home")  # cursor on the first visible node
        await pilot.press("v", "down")  # range = first two nodes
        await pilot.press("c")  # open the draft editor
        app.query_one("#compress-output", TextArea).text = "SUMMARY2"
        await pilot.press("ctrl+s")  # commit → K enters the graph

        app.describe_state()  # signature changed → recompute
        assert counter.count > warmed
