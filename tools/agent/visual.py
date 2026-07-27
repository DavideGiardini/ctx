"""Visual-acceptance driver — give the Ralph loop *eyes*.

The one structural blind spot that let the compression UI ship with visual bugs
(violet K bar, no blank line before a K, wrong range-selection style) is that the
loop **cannot see the rendered app**: the semantic ``ctx_snapshot`` honestly
reports state (``nodes=N``) while the pixels are wrong. This module closes
that gap with a thin, dependency-light pipeline the *main* agent can invoke:

    drive HarnessApp via Pilot  ->  export SVG  ->  rasterize to PNG  ->  agent Reads it

Why Pilot-in-a-fresh-subprocess (not the live MCP server): each ``uv run`` is a new
process that imports ``ctx.*`` fresh from disk, so it is immune to the
``sys.modules`` caching that can make a *second* in-process launch show stale code
(HANDOFF-loop-v2 §2.1). The live MCP server stays for behavioral QA.

Rasterization uses ``cairosvg``, which is **not** a permanent dependency — invoke
this module under ``uv run --with cairosvg==2.9.0`` so the install is ephemeral. Snap
``inkscape`` cannot read ``/tmp`` (private sandbox) — do not use it.

Usage (from the repo root)::

    # one state -> one PNG the Read tool renders visually
    uv run --with cairosvg==2.9.0 python -m tools.agent.visual state committed-K out.png \
        --size 160x48

    # force a deliberate defect / fix for both-directions judge calibration
    uv run --with cairosvg==2.9.0 python -m tools.agent.visual state committed-K bad.png \
        --variant k-violet
    uv run --with cairosvg==2.9.0 python -m tools.agent.visual state committed-K good.png \
        --variant k-green

    # render the whole standing fixture (all known-bug good/bad pairs + manifest)
    uv run --with cairosvg==2.9.0 python -m tools.agent.visual fixture /path/to/outdir

The **judge** is the agent's own vision: ``Read`` the PNG and decide PASS/FAIL
against the state's one-line visual intent. A judge that only ever says "pass" is
worse than none — always verify both directions on a known good/bad pair.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

# --- Variants: deliberate defect/fix injections ------------------------------
# Each variant forces a render to be known-broken or known-fixed *regardless of
# whether the real code is currently fixed*, so the standing fixture keeps
# discriminating after the Phase 3e fixes land. Colour variants patch config
# before the app is built; layout variants tweak the live DOM after the state is
# reached.

_CONTEXT_GREEN = "#22c55e"
_COMPRESSION_VIOLET = "#a855f7"


def _apply_pre_variant(variant: str | None) -> None:
    """Config-level injections that must happen before ``HarnessApp()`` builds."""
    if variant in ("k-violet", "k-green"):
        from ctx.core import config

        color = _COMPRESSION_VIOLET if variant == "k-violet" else _CONTEXT_GREEN
        # get_config() deep-copies _DEFAULTS when no user config.json exists, so
        # patching the default is a clean, process-local override.
        config._DEFAULTS["colors"]["compression"] = color


def _separator_neighbours(app):
    """Yield ``(separator, row_above, row_below)`` for each Separator in the list,
    in document order (row_above/row_below may be ``None`` at the edges)."""
    from ctx.ui.widgets.message_list import MessageList, MessageWidget, Separator

    children = list(app.query_one(MessageList).children)
    for i, child in enumerate(children):
        if isinstance(child, Separator):
            above = children[i - 1] if i > 0 else None
            below = children[i + 1] if i + 1 < len(children) else None
            yield (
                child,
                above if isinstance(above, MessageWidget) else None,
                below if isinstance(below, MessageWidget) else None,
            )


async def _apply_post_variant(app, pilot, variant: str | None) -> None:
    """DOM-level injections applied after the named state is reached."""
    if variant in ("k40-nogap", "k40-gap"):
        # The blank line before a K is a Separator the list places (task 40).
        # `k40-gap` is the real (fixed) render; `k40-nogap` removes the separator
        # sitting immediately above the K so it hugs the assistant reply above it.
        if variant == "k40-nogap":
            for sep, _above, below in list(_separator_neighbours(app)):
                if below is not None and below._role == "compression":
                    await sep.remove()
        await pilot.pause()
    if variant in ("range-blue", "range-grey"):
        # Force the task-41 broken look (solid blue, thin bar, gaps unbridged) vs
        # the fixed look (leave the real grey/contiguous styling untouched) so the
        # standing fixture keeps discriminating after the fix lands.
        from textual.color import Color

        from ctx.ui.widgets.message_list import MessageWidget
        from ctx.ui.widgets.message_row import _TALL_ROLES

        if variant == "range-blue":
            for widget in app.query(MessageWidget):
                if widget.has_class("range-selected"):
                    widget.styles.background = Color.parse("#1e3a8a")
                    if widget._role in _TALL_ROLES:
                        widget._row_body().styles.border_left = ("tall", widget._border_color)
            # Break the contiguity: strip the grey bridge off every separator.
            for sep, _above, _below in _separator_neighbours(app):
                sep.set_bridged(False)
        await pilot.pause()

    if variant in ("search-generic", "search-styled"):
        # task-10: a search row must read as part of the assistant's pass and as
        # ordinary injected context. `search-generic` reproduces the pre-task-10
        # look exactly as it shipped in task 9 — no entry in _SIDE, so the row
        # inherited the previous side and opened a spurious separator; no entry in
        # the palette, so it wore the system grey. `search-styled` leaves the real
        # (fixed) rendering untouched.
        if variant == "search-generic":
            from textual.color import Color

            from ctx.ui.widgets.message_list import MessageList, MessageWidget, Separator

            message_list = app.query_one(MessageList)
            for widget in app.query(MessageWidget):
                if widget._role != "search":
                    continue
                widget._row_body().styles.border_left = ("solid", Color.parse("#737373"))
                await message_list.mount(Separator(), before=widget)
        await pilot.pause()

    if variant in ("bar-outer", "bar-inner"):
        # task-49: the grey gap bridging two selected rows must show NO colored
        # left bar. `bar-outer` reproduces the pre-fix bleed by drawing a colored
        # bar down through the bridged separator; `bar-inner` leaves the real
        # (fixed) rendering — a bar-free grey gap — untouched.
        if variant == "bar-outer":
            for sep, above, _below in _separator_neighbours(app):
                if sep.has_class("bridged") and above is not None:
                    sep.styles.border_left = ("thick", above._border_color)
        await pilot.pause()


# --- Named states: keystroke scripts to reach a screen worth looking at ------
# Each returns after the app is parked in the target state; the caller then
# exports the screenshot. Keystrokes mirror the real bindings (ctx/ui/app.py).


async def _submit_turn(pilot, text: str) -> None:
    """Type *text* in Insert mode and submit it; wait out the canned stream."""
    for ch in text:
        await pilot.press(ch)
    await pilot.press("enter")
    # TestProvider streams with zero delay, but the worker still needs ticks to
    # run and the message list to settle.
    for _ in range(4):
        await pilot.pause()


async def _compress_selection(pilot) -> None:
    """From Edit mode with a node selected: open the editor, draft, commit."""
    await pilot.press("c")
    await pilot.pause()
    await pilot.press("ctrl+d")  # draft the canned summary
    for _ in range(3):
        await pilot.pause()
    await pilot.press("ctrl+s")  # commit -> K
    for _ in range(3):
        await pilot.pause()


async def _state_fresh(pilot) -> None:
    """One submitted turn (user + assistant), parked in Edit mode."""
    await _submit_turn(pilot, "hello there")
    await pilot.press("escape")  # -> Edit mode
    await pilot.pause()
    await pilot.press("home")  # select first node
    await pilot.pause()


async def _state_committed_k(pilot) -> None:
    """A committed compression K folding the opening user turn."""
    await _state_fresh(pilot)
    await _compress_selection(pilot)


async def _state_k_after_assistant(pilot) -> None:
    """Two turns, then compress the *second* user turn so the K sits directly
    after the first assistant reply — the task-40 adjacency (blank line before a
    K that follows an assistant turn)."""
    await _submit_turn(pilot, "first question")
    await _submit_turn(pilot, "second question")
    await pilot.press("escape")
    await pilot.pause()
    # Nodes: [user1, assistant1, user2, assistant2]. Select user2 (index 2).
    await pilot.press("home")
    for _ in range(2):
        await pilot.press("down")
        await pilot.pause()
    await _compress_selection(pilot)


async def _state_k_inspector(pilot) -> None:
    """A committed K *selected* so the detail inspector renders its folded
    originals split — the task-38 case (the inspector's message-bearing split
    should be compact rows with dividers, not a plain-text dump)."""
    await _state_committed_k(pilot)
    await pilot.press("home")  # select the K (first node) -> left pane renders it
    for _ in range(2):
        await pilot.pause()


async def _state_search_turn(pilot) -> None:
    """A settled research turn: the ``SEARCH`` trigger drives the harness through
    user -> assistant lead-in -> search -> assistant answer, so the new search row
    sits mid-turn between two assistant bubbles (task 10). Parked in Edit mode
    with nothing selected, so no selection highlight competes with the row's own
    bar for the eye."""
    await _submit_turn(pilot, "SEARCH what is ctx0")
    await pilot.press("escape")  # -> Edit mode
    await pilot.pause()


async def _state_range_selection(pilot) -> None:
    """A multi-node vim-style range selection (``v`` + ``down``) — the task-41
    case: the selected run (and the gaps between rows) should read as one
    contiguous highlighted block, not solid blue with default-colour gaps."""
    await _submit_turn(pilot, "first question")
    await _submit_turn(pilot, "second question")
    await pilot.press("escape")
    await pilot.pause()
    await pilot.press("home")
    await pilot.pause()
    await pilot.press("v")  # anchor the range on the first node
    await pilot.pause()
    for _ in range(2):
        await pilot.press("down")  # extend across the next two rows
        await pilot.pause()


STATES: dict[str, Callable[[object], Awaitable[None]]] = {
    "fresh": _state_fresh,
    "committed-K": _state_committed_k,
    "k-after-assistant": _state_k_after_assistant,
    "k-inspector": _state_k_inspector,
    "range-selection": _state_range_selection,
    "search-turn": _state_search_turn,
}


# --- Fixture: known-missed visual bugs, as good/bad pairs --------------------
# The standing regression net (HANDOFF-loop-v2 WS-C). Each entry is a bug the
# blind loop shipped; rendering its broken/fixed pair and judging both proves the
# visual gate discriminates. Re-run whenever the loop changes so the blind spot
# cannot silently reopen. Intent strings are what the agent judges each PNG
# against — one VLM-checkable sentence apiece.

FIXTURE: list[dict] = [
    {
        "bug": "task-40-blank-line-before-K",
        "state": "k-after-assistant",
        "intent": (
            "A blank margin row must separate the compression (K) row from the "
            "assistant row immediately above it, so the K reads as its own turn "
            "and not as part of the preceding assistant reply."
        ),
        "bad": "k40-nogap",
        "good": "k40-gap",
    },
    {
        "bug": "task-41-range-selection-contiguous-hover-style",
        "state": "range-selection",
        "intent": (
            "A multi-node range selection must read as one continuous block: a "
            "grey (hover-style) background with a bold role-colored left bar on "
            "every selected row, AND the highlight must bridge the gaps between "
            "rows (the inter-row gaps are grey too) — not solid blue rows with "
            "default-colored gaps between them."
        ),
        "bad": "range-blue",
        "good": "range-grey",
    },
    {
        "bug": "task-49-selection-bar-no-bleed-in-gap",
        "state": "range-selection",
        "intent": (
            "Within a multi-node range selection, the grey gap bridging two "
            "selected rows must show NO colored left bar — each row's colored bar "
            "stops at its own content; no bar segment bleeds down through the gap."
        ),
        "bad": "bar-outer",
        "good": "bar-inner",
    },
    {
        # Not a bug the loop shipped but the task-10 acceptance itself, kept here
        # so the pair cannot rot: the flushness half is the same pixel-level class
        # as task-40.
        "bug": "task-10-search-row-inside-the-assistant-turn",
        "state": "search-turn",
        "intent": (
            "The search row must sit flush inside the assistant's turn with no "
            "blank line splitting it off from the reply above it, and must carry "
            "the green left bar of injected context (not the system grey of an "
            "unstyled row, the assistant's orange or the user's blue)."
        ),
        "bad": "search-generic",
        "good": "search-styled",
    },
    # task-39 (K bar colour) is intentionally NOT the primary fixture bug — it is a
    # one-line palette assertion (ctx_snapshot colors:) that needs no vision. It is
    # kept here only as the both-directions *calibration* of the gate mechanism.
    {
        "bug": "task-39-K-bar-colour-CALIBRATION-ONLY",
        "state": "committed-K",
        "intent": (
            "The compression (K) node's left border bar must be the same green as "
            "context imports, not violet/purple (it carries a Σ glyph to stay "
            "distinguishable from a file import)."
        ),
        "bad": "k-violet",
        "good": "k-green",
    },
]


# --- Rasterization -----------------------------------------------------------

_FONT_FACE_RE = re.compile(r"@font-face\s*\{[^}]*\}", re.DOTALL)


def _strip_remote_fonts(svg: str) -> str:
    """Drop ``@font-face`` blocks so cairosvg falls back to a local monospace
    font instead of fetching a remote URL (keeps rasterization offline)."""
    return _FONT_FACE_RE.sub("", svg)


def rasterize(svg: str, png_path: Path) -> None:
    """SVG string -> PNG file at *png_path* (the Read tool renders PNG visually)."""
    import cairosvg  # lazy: only needed under `uv run --with cairosvg==2.9.0`

    png_path.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2png(
        bytestring=_strip_remote_fonts(svg).encode("utf-8"),
        write_to=str(png_path),
    )


# --- Driver ------------------------------------------------------------------


async def capture(
    state: str,
    *,
    variant: str | None = None,
    size: tuple[int, int] = (120, 40),
) -> tuple[str, dict]:
    """Drive ``HarnessApp`` to *state* (optionally with *variant*) and return
    ``(svg, describe_state())``.

    Instantiated *after* the pre-variant patch so config injections take effect.
    """
    if state not in STATES:
        raise ValueError(f"unknown state {state!r}; known: {', '.join(STATES)}")
    _apply_pre_variant(variant)

    from tools.agent.harness import HarnessApp

    app = HarnessApp()
    async with app.run_test(size=size) as pilot:
        await STATES[state](pilot)
        await _apply_post_variant(app, pilot, variant)
        state_dict = app.describe_state()
        svg = app.export_screenshot()
    return svg, state_dict


def _parse_size(text: str) -> tuple[int, int]:
    w, _, h = text.partition("x")
    return int(w), int(h)


def _cmd_state(args: argparse.Namespace) -> None:
    svg, state_dict = asyncio.run(
        capture(args.state, variant=args.variant, size=_parse_size(args.size))
    )
    out = Path(args.out)
    rasterize(svg, out)
    print(f"WROTE {out}")
    if args.print_state:
        print(json.dumps(state_dict, indent=2, default=str))


def _cmd_fixture(args: argparse.Namespace) -> None:
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    for entry in FIXTURE:
        for verdict, variant in (("FAIL", entry["bad"]), ("PASS", entry["good"])):
            name = f"{entry['bug']}__{verdict}.png"
            svg, _ = asyncio.run(capture(entry["state"], variant=variant))
            rasterize(svg, outdir / name)
            manifest.append(
                {
                    "png": name,
                    "bug": entry["bug"],
                    "intent": entry["intent"],
                    "expected_verdict": verdict,
                    "variant": variant,
                }
            )
            print(f"WROTE {outdir / name}  (expected {verdict})")
    (outdir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"WROTE {outdir / 'manifest.json'}")
    print(
        "\nJudge: Read each PNG and decide PASS/FAIL against its intent. "
        "Every *_PASS.png must PASS and every *_FAIL.png must FAIL — otherwise "
        "the visual gate is miscalibrated."
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_state = sub.add_parser("state", help="render one named state to a PNG")
    p_state.add_argument("state", choices=sorted(STATES))
    p_state.add_argument("out", help="output PNG path")
    p_state.add_argument(
        "--variant", default=None, help="force a defect/fix (e.g. k-violet, k40-gap)"
    )
    p_state.add_argument("--size", default="120x40", help="WIDTHxHEIGHT (cells)")
    p_state.add_argument(
        "--print-state", action="store_true", help="also print describe_state()"
    )
    p_state.set_defaults(func=_cmd_state)

    p_fix = sub.add_parser(
        "fixture", help="render all known-bug good/bad pairs + manifest.json"
    )
    p_fix.add_argument("outdir", help="directory to write the fixture into")
    p_fix.set_defaults(func=_cmd_fixture)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
