"""Shared keystroke / turn choreography for the Pilot-driven ``test_app_*`` suite.

These are plain importable functions — the second shared-scaffolding home alongside
``tests/conftest.py`` (which owns the provider doubles and the ``app_factory``
fixture). Import them the same way the fixtures' classes are imported, e.g.
``from pilot_helpers import two_turns``.

This module is a de-duplication of choreography that was hand-copied across ~15
files, not a place to "improve" test logic: keep behaviour identical to the copies
it replaces.
"""

from __future__ import annotations

from collections.abc import Callable

from textual.widgets import TextArea

from ctx.ui.widgets.input_bar import InputBar


async def two_turns(app) -> None:
    """Submit two complete turns (``"first"`` then ``"second"``), each awaited to
    completion, building the four-node ``U1, A1, U2, A2`` setup that most
    compression / expand / navigation app tests start from.

    Uses the app's *scripted* default provider — never a blocking one. A fully
    drained turn awaited against a gate that is never set deadlocks the whole pytest
    run (see ``BlockingProvider`` in ``conftest.py``); the blocking provider is only
    ever swapped in for the single turn actually under test, after this setup.
    """
    await app.on_input_bar_submitted(InputBar.Submitted("first"))
    await app.workers.wait_for_complete()
    await app.on_input_bar_submitted(InputBar.Submitted("second"))
    await app.workers.wait_for_complete()


async def turn(app, text: str) -> None:
    """Submit a single turn and await it to completion — the one-turn variant of
    :func:`two_turns`."""
    await app.on_input_bar_submitted(InputBar.Submitted(text))
    await app.workers.wait_for_complete()


async def wait_until(pilot, predicate: Callable[[], bool], *, tries: int = 200) -> bool:
    """Spin ``pilot.pause()`` up to ``tries`` times until ``predicate()`` is truthy;
    return whether it became truthy within the bound.

    **The bound is the whole point.** These waits guard on live async workers, and an
    unbounded wait on a condition that never holds hangs the entire pytest run — which
    is strictly worse than the spin-loop duplication this replaces. Callers assert on
    the return value (or on the underlying state) so an exhausted bound fails loudly
    rather than silently proceeding.
    """
    for _ in range(tries):
        if predicate():
            return True
        await pilot.pause()
    return False


async def wait_until_streaming(app, pilot, *, tries: int = 200) -> None:
    """Bounded-wait until a real turn is streaming (``app.core.streaming``), asserting
    it became live within the bound.

    The common "provider swapped for a ``BlockingProvider``, turn submitted, now wait
    until the stream is genuinely in flight" shape. For draft-worker or
    rendered-content waits, call :func:`wait_until` with an explicit predicate.
    """
    live = await wait_until(pilot, lambda: app.core.streaming, tries=tries)
    assert live, "turn stream never became live within the bound"


async def open_editor_on_range(pilot, *, downs: int = 3) -> None:
    """Enter Edit, anchor a range at the top of the view and extend it ``downs``
    rows down to the tip, then open the compression draft editor on it (form B).

    ``downs=3`` selects the four-node ``U1,A1,U2,A2`` view most compression tests
    start from; the knob absorbs the 2-node variants (``downs=1`` → the top turn
    only). Assumes the app is in *Insert* mode on entry — the leading ``Esc`` toggles
    into Edit. Callers already in Edit (or opening on a single unanchored node) drive
    the keys inline instead.
    """
    await pilot.press("escape")  # → Edit mode
    await pilot.press("home")  # cursor on the first node
    await pilot.press("v", *(["down"] * downs))  # range = downs+1 nodes, ending at tip
    await pilot.press("c")  # open the draft editor


async def compress_range(app, pilot, summary: str, *, downs: int = 3) -> None:
    """Fold a top-anchored range into a single committed K (form A).

    Opens the editor on the range (:func:`open_editor_on_range`, same ``downs``
    knob), writes ``summary`` into the Bottom split, and commits with ``Ctrl+S``.
    A manual commit like this stamps an empty prompt on the K. Leaves the app in
    Edit mode with the selection cleared (a commit clears it); use
    :func:`select_tip_in_edit` to re-select the folded K.
    """
    await open_editor_on_range(pilot, downs=downs)
    app.query_one("#compress-output", TextArea).text = summary
    await pilot.press("ctrl+s")  # commit → one K in the view


async def select_tip_in_edit(app, pilot) -> None:
    """Land in Edit mode with the selection on the tip node.

    A commit leaves the app in Edit mode with the selection cleared, so bounce out
    to Insert and back: re-entering Edit re-selects the tip (e.g. a freshly folded
    K). The leading Esc is mode-guarded so this is a no-op-safe way to reach
    "Edit mode, tip selected" from either mode — replacing the hand-copied
    ``if mode == "edit": escape`` workarounds that had drifted between files.
    """
    if app.mode == "edit":
        await pilot.press("escape")  # → Insert
    await pilot.press("escape")  # → Edit, selects the tip
