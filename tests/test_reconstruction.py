"""Behavioral tests for ctx.core.reconstruction.

Written code-blind from tests/specs/reconstruction.md. Each test cites the
contract item(s) it covers. All nodes set created_seq and prev_id EXPLICITLY;
structural assertions compare id-sequences ([n.id for n in result]).
"""

from ctx.core.reconstruction import (
    context_at_generation,
    has_drift,
    now_prefix,
)
from ctx.models.nodes import Node

CONV = "conv-1"


def msg(node_id: str, prev_id, seq: int, role: str = "user",
        content: str = "some conversational text") -> Node:
    """Ordinary turn with explicit id, prev_id and created_seq."""
    n = Node(id=node_id, role=role, content=content)
    n.prev_id = prev_id
    n.created_seq = seq
    return n


def compression(node_id: str, range_ids, seq: int,
                summary: str = "folded summary") -> Node:
    """Off-line compression node (prev_id=None) with explicit id + created_seq."""
    k = Node.compression(summary, CONV, list(range_ids), prompt="condense")
    k.id = node_id
    k.created_seq = seq
    return k


def expand(node_id: str, target_id: str, seq: int,
           anchor_id: str = "a") -> Node:
    """Off-line expand event (prev_id=None) with explicit id + created_seq."""
    e = Node.expand(target_id, anchor_id, CONV)
    e.id = node_id
    e.created_seq = seq
    return e


def ids(nodes):
    return [n.id for n in nodes]


# --- shared line builders (each test builds its own; no shared mutable state) --

def _line_abc():
    """a<-b<-c on the line, seqs 1,2,3."""
    a = msg("a", None, 1)
    b = msg("b", "a", 2)
    c = msg("c", "b", 3)
    return a, b, c


# =====================================================================
# context_at_generation
# =====================================================================

# C1 — turn generated AFTER a compression sees K.
def test_context_folds_when_k_precedes_turn():
    a, b, c = _line_abc()
    k = compression("K", ["a", "b", "c"], 4)
    t = msg("T", "c", 5)
    result = context_at_generation([a, b, c, k, t], "T")
    assert ids(result) == ["K"]


# C2 — a K created AFTER T is not applied (verbatim).
def test_context_verbatim_when_k_after_turn():
    a, b, c = _line_abc()
    t = msg("T", "c", 4)
    k = compression("K", ["a", "b", "c"], 5)  # created after T
    result = context_at_generation([a, b, c, t, k], "T")
    assert ids(result) == ["a", "b", "c"]


# C3 — K expanded BEFORE T is not applied (verbatim).
def test_context_verbatim_when_expanded_before_turn():
    a, b, c = _line_abc()
    k = compression("K", ["a", "b", "c"], 4)
    e = expand("E", "K", 5)  # expand before T
    t = msg("T", "c", 6)
    result = context_at_generation([a, b, c, k, e, t], "T")
    assert ids(result) == ["a", "b", "c"]


# C4 — K expanded AFTER T is still applied.
def test_context_folds_when_expand_after_turn():
    a, b, c = _line_abc()
    k = compression("K", ["a", "b", "c"], 4)
    t = msg("T", "c", 5)
    e = expand("E", "K", 6)  # expand after T
    result = context_at_generation([a, b, c, k, t, e], "T")
    assert ids(result) == ["K"]


# C5 — range not a subset of L (abandoned-tail) never applies.
def test_context_ignores_k_with_offline_range():
    a, b, c = _line_abc()
    t = msg("T", "c", 5)
    k = compression("K", ["a", "b", "x"], 4)  # "x" not an ancestor of T
    result = context_at_generation([a, b, c, k, t], "T")
    assert ids(result) == ["a", "b", "c"]


# C6 — T itself is excluded (strict ancestors only).
def test_context_excludes_the_turn_itself():
    a = msg("a", None, 1)
    b = msg("b", "a", 2)
    t = msg("T", "b", 3)
    result = context_at_generation([a, b, t], "T")
    assert ids(result) == ["a", "b"]
    assert "T" not in ids(result)
    assert ids(result)[-1] == "b"


# C7 — maximal contiguous middle run folds in place, neighbours preserved.
def test_context_folds_middle_contiguous_run():
    a = msg("a", None, 1)
    b = msg("b", "a", 2)
    c = msg("c", "b", 3)
    d = msg("d", "c", 4)
    e = msg("e", "d", 5)
    t = msg("T", "e", 7)
    k = compression("K", ["b", "c", "d"], 6)
    result = context_at_generation([a, b, c, d, e, t, k], "T")
    assert ids(result) == ["a", "K", "e"]


# C8 — two independent compressions each fold their own run, in order.
def test_context_two_independent_compressions():
    a = msg("a", None, 1)
    b = msg("b", "a", 2)
    c = msg("c", "b", 3)
    d = msg("d", "c", 4)
    k1 = compression("K1", ["a", "b"], 5)
    k2 = compression("K2", ["c", "d"], 6)
    t = msg("T", "d", 7)
    result = context_at_generation([a, b, c, d, k1, k2, t], "T")
    assert ids(result) == ["K1", "K2"]


# C9 — unknown node id → [].
def test_context_unknown_node_id_empty():
    a, b, c = _line_abc()
    t = msg("T", "c", 4)
    assert context_at_generation([a, b, c, t], "does-not-exist") == []


# C9 — root turn (prev_id=None) → [].
def test_context_root_turn_empty():
    a, b, c = _line_abc()
    assert context_at_generation([a, b, c], "a") == []


# C9 — off-line compression/expand node id → [].
def test_context_offline_node_id_empty():
    a, b, c = _line_abc()
    k = compression("K", ["a", "b", "c"], 4)
    e = expand("E", "K", 5)
    t = msg("T", "c", 6)
    nodes = [a, b, c, k, e, t]
    assert context_at_generation(nodes, "K") == []
    assert context_at_generation(nodes, "E") == []


# C10 — era selection: each turn sees the K active at its own seq.
def test_context_era_selection_per_turn():
    a, b, c = _line_abc()
    k1 = compression("K1", ["a", "b", "c"], 4)
    t1 = msg("T1", "c", 5)
    e1 = expand("E1", "K1", 6)
    t2 = msg("T2", "c", 7)
    k2 = compression("K2", ["a", "b", "c"], 8)
    t3 = msg("T3", "c", 9)
    nodes = [a, b, c, k1, t1, e1, t2, k2, t3]
    assert ids(context_at_generation(nodes, "T1")) == ["K1"]
    assert ids(context_at_generation(nodes, "T2")) == ["a", "b", "c"]
    assert ids(context_at_generation(nodes, "T3")) == ["K2"]


# C11 — result is root-first.
def test_context_root_first_order():
    a, b, c = _line_abc()
    t = msg("T", "c", 4)
    result = context_at_generation([a, b, c, t], "T")
    assert ids(result) == ["a", "b", "c"]


# =====================================================================
# now_prefix
# =====================================================================

# C12 — folds a K that exists now even if created after T.
def test_now_folds_k_created_after_turn():
    a, b, c = _line_abc()
    t = msg("T", "c", 4)
    k = compression("K", ["a", "b", "c"], 5)  # created after T
    result = now_prefix([a, b, c, t, k], "T")
    assert ids(result) == ["K"]


# C13 — any expand targeting K restores K → verbatim (regardless of seq).
def test_now_verbatim_when_any_expand_targets_k():
    a, b, c = _line_abc()
    k = compression("K", ["a", "b", "c"], 4)
    t = msg("T", "c", 5)
    e = expand("E", "K", 6)  # expand exists today
    result = now_prefix([a, b, c, k, t, e], "T")
    assert ids(result) == ["a", "b", "c"]


# C14 — range not a subset of L never applies.
def test_now_ignores_k_with_offline_range():
    a, b, c = _line_abc()
    t = msg("T", "c", 5)
    k = compression("K", ["a", "b", "x"], 4)
    result = now_prefix([a, b, c, k, t], "T")
    assert ids(result) == ["a", "b", "c"]


# C15 — unknown / root / off-line node id → [].
def test_now_unknown_root_and_offline_empty():
    a, b, c = _line_abc()
    k = compression("K", ["a", "b", "c"], 4)
    t = msg("T", "c", 5)
    nodes = [a, b, c, k, t]
    assert now_prefix(nodes, "does-not-exist") == []
    assert now_prefix(nodes, "a") == []  # root turn
    assert now_prefix(nodes, "K") == []  # off-line node


# C16 — now-view of an era-selected turn folds the currently-live K.
def test_now_reflects_live_compression_across_eras():
    a, b, c = _line_abc()
    k1 = compression("K1", ["a", "b", "c"], 4)
    t1 = msg("T1", "c", 5)
    e1 = expand("E1", "K1", 6)  # K1 expanded => not live today
    t2 = msg("T2", "c", 7)
    k2 = compression("K2", ["a", "b", "c"], 8)  # K2 live today (no expand)
    t3 = msg("T3", "c", 9)
    nodes = [a, b, c, k1, t1, e1, t2, k2, t3]
    # Today only K2 is live over [a,b,c]; T1's now-view folds to K2.
    assert ids(now_prefix(nodes, "T1")) == ["K2"]


# =====================================================================
# has_drift
# =====================================================================

# C17 — drift True: turn before a compression (verbatim vs folded).
def test_drift_true_turn_before_compression():
    a, b, c = _line_abc()
    t = msg("T", "c", 4)
    k = compression("K", ["a", "b", "c"], 5)  # created after T
    assert has_drift([a, b, c, t, k], "T") is True


# C18 — no drift: turn after a compression, no expand.
def test_drift_false_turn_after_compression():
    a, b, c = _line_abc()
    k = compression("K", ["a", "b", "c"], 4)
    t = msg("T", "c", 5)
    assert has_drift([a, b, c, k, t], "T") is False


# C19 — drift True (reverse direction): saw K, expanded after.
def test_drift_true_reverse_direction():
    a, b, c = _line_abc()
    k = compression("K", ["a", "b", "c"], 4)
    t = msg("T", "c", 5)
    e = expand("E", "K", 6)  # expand after T
    assert has_drift([a, b, c, k, t, e], "T") is True


# C20 — no drift: conversation with no compression/expand events.
def test_drift_false_no_events():
    a, b, c = _line_abc()
    t = msg("T", "c", 4)
    nodes = [a, b, c, t]
    assert has_drift(nodes, "T") is False
    assert ids(context_at_generation(nodes, "T")) == ["a", "b", "c"]
    assert ids(now_prefix(nodes, "T")) == ["a", "b", "c"]


# C21 — unknown / root node never drifts.
def test_drift_false_for_unknown_and_root():
    a, b, c = _line_abc()
    t = msg("T", "c", 4)
    nodes = [a, b, c, t]
    assert has_drift(nodes, "does-not-exist") is False
    assert has_drift(nodes, "a") is False  # root turn, both views []
