"""Deterministic floor under the agent-judged visual fixture.

``tools/agent/visual.py`` drives ``HarnessApp`` via Pilot to a set of *named
states* the main agent renders and looks at (HANDOFF-loop-v2 WS-A). The picture is
the acceptance check, but a picture has no regression net: if a state script
silently stops reaching its screen (a binding changes, the compress flow moves),
the agent would judge a *wrong* render and never know. These tests are that net —
they assert each state reaches the intended ``describe_state()`` and that the
defect/fix variants actually flip the property they claim to, so the standing
fixture keeps discriminating.

They exercise ``capture()`` only (no rasterization), so ``cairosvg`` is not needed.
"""

import pytest

from ctx.core import config
from tools.agent.visual import FIXTURE, STATES, capture


@pytest.fixture(autouse=True)
def _restore_compression_color():
    """capture()'s colour variants patch the process-global config default; keep
    that mutation from leaking into other tests."""
    orig = config._DEFAULTS["colors"]["compression"]
    yield
    config._DEFAULTS["colors"]["compression"] = orig


async def test_fresh_is_a_plain_turn_no_compression():
    _svg, state = await capture("fresh")
    roles = [n["role"] for n in state["nodes"]]
    assert roles == ["user", "assistant"]
    assert state["mode"] == "edit"


async def test_committed_k_yields_exactly_one_compression_node():
    _svg, state = await capture("committed-K")
    comp = [n for n in state["nodes"] if n["node_type"] == "compression"]
    assert len(comp) == 1


async def test_k_after_assistant_places_k_directly_after_an_assistant():
    # The task-40 adjacency: a K whose row sits right below an assistant reply.
    _svg, state = await capture("k-after-assistant")
    roles = [n["role"] for n in state["nodes"]]
    assert roles == ["user", "assistant", "compression", "assistant"]


async def test_k_inspector_selects_the_k():
    # The task-38 inspector case needs the K selected so its splits render.
    _svg, state = await capture("k-inspector")
    selected = state["nodes"][state["selected_index"]]
    assert selected["node_type"] == "compression"


async def test_range_selection_spans_multiple_nodes():
    # The task-41 case: a contiguous multi-node vim-style range.
    _svg, state = await capture("range-selection")
    assert len(state.get("range_selection") or []) >= 2


async def test_drift_diff_opens_the_full_screen_diff():
    _svg, state = await capture("drift-diff")
    assert (state.get("diff_view") or {}).get("open") is True


@pytest.mark.parametrize(
    "variant,expected",
    [("k-violet", "#a855f7"), ("k-green", "#22c55e")],
)
async def test_colour_variants_flip_the_compression_palette(variant, expected):
    _svg, state = await capture("committed-K", variant=variant)
    assert state["colors"]["compression"] == expected


def test_fixture_entries_are_well_formed():
    # The manifest the agent judges against must reference real states/variants.
    known_variants = {
        "k-violet",
        "k-green",
        "k40-nogap",
        "k40-gap",
        "range-blue",
        "range-grey",
        "bar-outer",
        "bar-inner",
    }
    for entry in FIXTURE:
        assert entry["state"] in STATES
        assert entry["bad"] in known_variants
        assert entry["good"] in known_variants
        assert entry["intent"].strip()
