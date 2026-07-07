"""Tests for ctx.core.context.build_compression_transcript.

Contract: tests/specs/compression_transcript.md
Authored code-blind from the interface + PRD acceptance criteria (ADR-0016 A#6).
Assertions trace to contract Expect clauses, never to assumed implementation output.
"""

from ctx.core.context import build_compression_transcript
from ctx.models.nodes import Node

OPEN = "<compress_this>"
CLOSE = "</compress_this>"


def _null_loader(path: str) -> str:  # used where no context node is present
    raise FileNotFoundError(path)


# C1 — the marked range appears between the marker lines
def test_range_nodes_between_markers(make_node):
    before = make_node(role="user", content="before the range starts")
    middle = make_node(role="user", content="middle to be compressed")
    after = make_node(role="user", content="after the range ends")

    out = build_compression_transcript(
        [before, middle, after], [middle.id], _null_loader
    )

    assert OPEN in out and CLOSE in out
    assert out.index(OPEN) < out.index("middle to be compressed") < out.index(CLOSE)


# C2 — out-of-range nodes sit on the correct side of the markers
def test_before_and_after_nodes_outside_markers(make_node):
    before = make_node(role="user", content="before the range starts")
    middle = make_node(role="user", content="middle to be compressed")
    after = make_node(role="user", content="after the range ends")

    out = build_compression_transcript(
        [before, middle, after], [middle.id], _null_loader
    )

    assert out.index("before the range starts") < out.index(OPEN)
    assert out.index("after the range ends") > out.index(CLOSE)


# C3 — a context node contributes the loaded file body, not the "Included:" label
def test_context_node_uses_loaded_body_not_label(stub_loader):
    ctx_node = Node.context("src/service.py", "conv-1")
    load = stub_loader({"src/service.py": "class Service:\n    pass"})

    out = build_compression_transcript([ctx_node], [ctx_node.id], load)

    assert "class Service:" in out
    assert "Included:" not in out
    assert "User:" in out


# C4 — a committed compression node contributes its summary text
def test_compression_node_uses_summary(stub_loader):
    summary = "Earlier the user set up auth and DB config."
    k = Node.compression(summary, "conv-1", range_ids=[])
    load = stub_loader({})

    out = build_compression_transcript([k], [k.id], load)

    assert summary in out
    assert "User:" in out


# C5 — a system breadcrumb emits nothing
def test_system_breadcrumb_dropped(make_node):
    before = make_node(role="user", content="keep before breadcrumb")
    crumb = make_node(role="system", content="INTERNAL BREADCRUMB XYZ")
    after = make_node(role="user", content="keep after breadcrumb")

    out = build_compression_transcript(
        [before, crumb, after], [before.id], _null_loader
    )

    assert "INTERNAL BREADCRUMB XYZ" not in out
    assert "keep before breadcrumb" in out
    assert "keep after breadcrumb" in out


# C6 — turns are labeled by role, bodies ordered under their label
def test_role_labels_and_order(make_node):
    q = make_node(role="user", content="question about pricing")
    a = make_node(role="assistant", content="here is the pricing")

    out = build_compression_transcript([q, a], [], _null_loader)

    assert "User:" in out and "Assistant:" in out
    assert out.index("User:") < out.index("question about pricing")
    assert out.index("Assistant:") < out.index("here is the pricing")
    # node order preserved: user block before assistant block
    assert out.index("question about pricing") < out.index("here is the pricing")


# C7 — empty marked span still emits both markers as an adjacent pair
def test_empty_marked_span_emits_adjacent_markers(make_node):
    before = make_node(role="user", content="context before empty span")
    empty = make_node(role="user", content="")  # dropped: empty body

    out = build_compression_transcript([before, empty], [empty.id], _null_loader)

    assert OPEN in out and CLOSE in out
    between = out[out.index(OPEN) + len(OPEN):out.index(CLOSE)]
    assert between.strip() == ""
    assert out.index("context before empty span") < out.index(OPEN)
