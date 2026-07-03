"""Behavioral tests for ctx.core.reconstruction.

Written code-blind from tests/specs/reconstruction.md. Each test cites the
contract item(s) it covers. All nodes set created_seq and prev_id EXPLICITLY;
structural assertions compare id-sequences ([n.id for n in result]).
"""

from ctx.core.context import build_context
from ctx.core.reconstruction import (
    context_at_generation,
    diff_regions,
    has_drift,
    hash_context,
    now_prefix,
    reconstruction_warning,
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


# =====================================================================
# diff_regions — structural block-alignment of then- vs now-context
# =====================================================================

def _expand_direction_graph():
    """The task-20 shape: T saw K, K expanded after T ran.

    U1=a, A1=b, K folds [a,b], U2=c, A2=T, then E expands K.
    then-context(T) = [K, c]; now-context(T) = [a, b, c].
    """
    a = msg("a", None, 1)
    b = msg("b", "a", 2, role="assistant")
    k = compression("K", ["a", "b"], 3)
    c = msg("c", "b", 4)
    t = msg("T", "c", 5, role="assistant")
    e = expand("E", "K", 6)
    return [a, b, k, c, t, e]


def _changed(regions):
    return [r for r in regions if r.changed]


# D1 — expand direction: the changed region is K (left) ⟷ its originals (right).
def test_diff_regions_expand_direction():
    nodes = _expand_direction_graph()
    regions = diff_regions(nodes, "T")
    changed = _changed(regions)
    assert len(changed) == 1
    assert ids(changed[0].left) == ["K"]
    assert ids(changed[0].right) == ["a", "b"]
    # The shared tail (c) is present as an unchanged region on both sides.
    unchanged = [r for r in regions if not r.changed]
    assert unchanged and ids(unchanged[-1].left) == ["c"]
    assert ids(unchanged[-1].right) == ["c"]


# D2 — compression direction: T ran verbatim, a K created afterwards folds it now.
def test_diff_regions_compression_direction():
    a = msg("a", None, 1)
    b = msg("b", "a", 2, role="assistant")
    c = msg("c", "b", 3)
    t = msg("T", "c", 4, role="assistant")
    k = compression("K", ["a", "b"], 5)  # created after T
    regions = diff_regions([a, b, c, t, k], "T")
    changed = _changed(regions)
    assert len(changed) == 1
    assert ids(changed[0].left) == ["a", "b"]  # what T saw
    assert ids(changed[0].right) == ["K"]  # what it folds to now


# D3 — no drift: every region is unchanged and spans the whole prefix.
def test_diff_regions_no_drift_all_unchanged():
    a, b, c = _line_abc()
    t = msg("T", "c", 4, role="assistant")
    regions = diff_regions([a, b, c, t], "T")
    assert regions  # not empty
    assert all(not r.changed for r in regions)
    left = [n for r in regions for n in r.left]
    right = [n for r in regions for n in r.right]
    assert ids(left) == ["a", "b", "c"]
    assert ids(right) == ["a", "b", "c"]


# D4 — unknown node: both prefixes empty → no regions.
def test_diff_regions_unknown_node_empty():
    a, b, c = _line_abc()
    t = msg("T", "c", 4)
    assert diff_regions([a, b, c, t], "nope") == []


# =====================================================================
# middle-compression sequence (task 22) — a K folds a mid-line range, so a
# turn that ran BEFORE it drifts (saw verbatim, now K) while a turn BORN after
# it does not (its context already folds K). U1,A1,U2,A2 -> compress [U1,A1]
# -> U3,A3.
# =====================================================================

def _middle_compress_graph():
    u1 = msg("U1", None, 1)
    a1 = msg("A1", "U1", 2, role="assistant")
    u2 = msg("U2", "A1", 3)
    a2 = msg("A2", "U2", 4, role="assistant")
    k = compression("K", ["U1", "A1"], 5, summary="head summary")
    # folding is recorded on the children too (pointer set at commit)
    u1.compressed_into = "K"
    a1.compressed_into = "K"
    u3 = msg("U3", "A2", 6)
    a3 = msg("A3", "U3", 7, role="assistant")
    return [u1, a1, u2, a2, k, u3, a3]


# M1 — A2 ran before K (verbatim) but the now-view folds its head into K: drift.
def test_middle_compress_earlier_turn_drifts():
    nodes = _middle_compress_graph()
    assert has_drift(nodes, "A2") is True
    assert ids(context_at_generation(nodes, "A2")) == ["U1", "A1", "U2"]
    assert ids(now_prefix(nodes, "A2")) == ["K", "U2"]


# M2 — the changed diff region shows what A2 saw (U1,A1) vs. what it folds to (K).
def test_middle_compress_diff_region_shape():
    nodes = _middle_compress_graph()
    changed = _changed(diff_regions(nodes, "A2"))
    assert len(changed) == 1
    assert ids(changed[0].left) == ["U1", "A1"]
    assert ids(changed[0].right) == ["K"]


# M3 — A3 was born after K: its generation context already folds K, so no drift
# and the recorded context carries the summary, never the folded children.
def test_middle_compress_later_turn_no_drift_reads_summary():
    nodes = _middle_compress_graph()
    assert has_drift(nodes, "A3") is False
    gen = ids(context_at_generation(nodes, "A3"))
    assert gen == ["K", "U2", "A2", "U3"]
    assert "U1" not in gen and "A1" not in gen


# =====================================================================
# reconstruction_warning — the ctx_hash H4 tripwire
# =====================================================================

def _loader(_path):
    return ""


def _turn_with_hash(nodes, turn_id, hash_value):
    """Stamp meta['ctx_hash'] on the turn node in ``nodes``."""
    for n in nodes:
        if n.id == turn_id:
            n.meta["ctx_hash"] = hash_value


# W1 — matching hash: reconstruction verifies, no warning.
def test_warning_false_when_hash_matches():
    nodes = _expand_direction_graph()
    genuine = hash_context(build_context(context_at_generation(nodes, "T"), _loader))
    _turn_with_hash(nodes, "T", genuine)
    assert reconstruction_warning(nodes, "T", _loader) is False


# W2 — mismatched hash: warns (a reconstruction bug or drifted import).
def test_warning_true_when_hash_mismatches():
    nodes = _expand_direction_graph()
    _turn_with_hash(nodes, "T", "deadbeef")
    assert reconstruction_warning(nodes, "T", _loader) is True


# W3 — missing hash (pre-3b turn): warns rather than claiming exactness.
def test_warning_true_when_hash_absent():
    nodes = _expand_direction_graph()  # T carries no ctx_hash
    assert reconstruction_warning(nodes, "T", _loader) is True


# W4 — unknown node: nothing to warn about.
def test_warning_false_for_unknown_node():
    nodes = _expand_direction_graph()
    assert reconstruction_warning(nodes, "nope", _loader) is False
