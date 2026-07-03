"""Read-only, lazy per-turn context reconstruction (ADR-0016 A#2/A#3, Q11).

Pure functions over a flat node list — **never on the live generation
pipeline**. They answer "what context did turn ``T`` see when it was generated"
by *event enumeration* over the append-only graph (compression ``K`` nodes and
their expand ``E`` events), keyed on the monotonic ``created_seq`` transaction
axis. Framework-free: this module imports only :class:`Node`.

The live now-view lives in ``ConversationCore.current_view`` (task 15); this
module generalizes that resolution in two ways — it works over an arbitrary
``all_nodes`` list rather than the core's graph, and it resolves an **as-of**
time slice (``created_seq(K) < created_seq(T)``) rather than the present.
"""

import hashlib
import json
from collections.abc import Callable
from typing import Any

from ctx.models.nodes import Node


def hash_context(messages: list[dict[str, Any]]) -> str:
    """Canonical, stable digest of a rendered ``build_context`` message list.

    Returns the hex sha256 of ``json.dumps(messages, sort_keys=True,
    ensure_ascii=False)``. The digest depends only on the *content* of the
    messages, not on dict key insertion order (``sort_keys=True``), and is a
    pure function — identical input always yields the identical string, and any
    change to message roles, content, ordering, or count changes it.

    This is the per-turn verification anchor (ADR-0016 A#3 §4): at generation
    time the exact rendered messages are hashed and stored immutably on the
    assistant node's ``meta["ctx_hash"]``; the reconstruction oracle later
    re-derives the turn's context and compares. The hash detects a
    reconstruction bug — it never repairs or drives anything.
    """
    canonical = json.dumps(messages, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _strict_ancestors(index: dict[str, Node], node_id: str) -> list[Node]:
    """Strict ancestors of ``node_id`` by ``prev_id``, root-first (excludes it).

    Defensively stops on an id missing from ``index`` or already seen so a
    malformed chain can never hang (mirrors ``current_view``'s walk).
    """
    node = index.get(node_id)
    if node is None:
        return []
    line: list[Node] = []
    seen: set[str] = set()
    cur = node.prev_id
    while cur is not None and cur in index and cur not in seen:
        seen.add(cur)
        ancestor = index[cur]
        line.append(ancestor)
        cur = ancestor.prev_id
    line.reverse()
    return line


def _fold(all_nodes: list[Node], line: list[Node], applies: Callable[[Node], bool]) -> list[Node]:
    """Fold the strict-ancestor ``line`` by event enumeration.

    A compression ``K`` (anywhere in ``all_nodes``) folds iff ``applies(K)`` holds
    and its whole ``meta["range"]`` lies on ``line``. Each maximal contiguous run
    of one ``K``'s children is then replaced in place by ``K`` (identical to
    ``current_view``). Active compressions never overlap (ADR-0016 A#3), so each
    child maps to exactly one ``K``. Discovery reads only the ``K`` event nodes
    and ``created_seq`` — never child ``compressed_into`` pointers (A#3 §3).
    """
    line_ids = {n.id for n in line}
    folds: dict[str, Node] = {}
    for k in all_nodes:
        if k.node_type != "compression" or not applies(k):
            continue
        range_ids = k.meta.get("range", [])
        if range_ids and all(child_id in line_ids for child_id in range_ids):
            for child_id in range_ids:
                folds[child_id] = k

    resolved: list[Node] = []
    i = 0
    while i < len(line):
        fold_k = folds.get(line[i].id)
        if fold_k is None:
            resolved.append(line[i])
            i += 1
        else:
            resolved.append(fold_k)
            while i < len(line) and folds.get(line[i].id) is fold_k:
                i += 1
    return resolved


def context_at_generation(all_nodes: list[Node], node_id: str) -> list[Node]:
    """The context turn ``node_id`` saw at generation, as ``list[Node]``.

    Reconstructs the exact folded prefix that fed ``build_context`` when the
    turn identified by ``node_id`` (``T``) was generated, using the ADR-0016 A#2
    as-of rule:

    1. Walk ``prev_id`` from ``T`` for its **strict ancestors** ``L`` (root-first;
       ``T`` itself is excluded — a turn's context is the material *before* it).
    2. For every compression ``K`` in ``all_nodes``, apply it (fold its stored
       range within ``L`` into ``K``) iff **all** hold: ``created_seq(K) <
       created_seq(T)`` (``K`` existed when ``T`` ran); ``K.meta["range"]`` ⊆ the
       ids of ``L`` (the whole range lies on ``T``'s line — an abandoned-tail /
       off-line range never applies); and no expand event ``E`` with
       ``E.meta["target"] == K.id`` has ``created_seq(E) < created_seq(T)`` (``K``
       had not been expanded yet at ``T``).
    3. Fold: each **maximal contiguous run** of an applying ``K``'s children in
       ``L`` is replaced in place by ``K`` (matching ``current_view``).

    Result is root-first. An unknown ``node_id``, or one with no ancestors (a
    root turn or an off-line ``K``/``E`` node), yields ``[]``. Resolution reads
    only the ``K``/``E`` event nodes and ``created_seq`` — never child
    ``compressed_into`` pointers (ADR-0016 A#3 §3).
    """
    index = {n.id: n for n in all_nodes}
    turn = index.get(node_id)
    if turn is None:
        return []
    line = _strict_ancestors(index, node_id)
    turn_seq = turn.created_seq
    # E ids expanded strictly before the turn ran (the as-of deactivation set).
    expanded_before = {
        target
        for n in all_nodes
        if n.node_type == "expand"
        and n.created_seq < turn_seq
        and (target := n.meta.get("target")) is not None
    }

    def applies(k: Node) -> bool:
        return k.created_seq < turn_seq and k.id not in expanded_before

    return _fold(all_nodes, line, applies)


def now_prefix(all_nodes: list[Node], node_id: str) -> list[Node]:
    """The same ancestor prefix of ``node_id``, folded under the *now*-rule.

    Identical to :func:`context_at_generation` except the fold set is resolved
    with the task-15 now-view rule instead of the as-of rule: a compression
    ``K`` applies iff **no** ``E`` targets it *at all* (regardless of
    ``created_seq``) and its ``meta["range"]`` ⊆ the ids of the strict ancestors
    ``L``. This is what the turn's context *would* look like given every
    compression/expand event that exists today — so it can fold a ``K`` created
    after ``T`` (which ``T`` never saw) or restore a ``K`` that ``T`` saw but was
    later expanded.

    Result is root-first; an unknown or ancestor-less ``node_id`` yields ``[]``.
    """
    index = {n.id: n for n in all_nodes}
    if node_id not in index:
        return []
    line = _strict_ancestors(index, node_id)
    expanded = {
        target
        for n in all_nodes
        if n.node_type == "expand" and (target := n.meta.get("target")) is not None
    }

    def applies(k: Node) -> bool:
        return k.id not in expanded

    return _fold(all_nodes, line, applies)


def has_drift(all_nodes: list[Node], node_id: str) -> bool:
    """Whether ``node_id``'s reconstructed context differs from the now-view.

    ``True`` iff :func:`context_at_generation` and :func:`now_prefix` produce
    **structurally different** prefixes for ``node_id`` — i.e. their node
    id-sequences differ. A conversation with no compression/expand events, or a
    turn whose folds are unchanged since it ran, never drifts. Drift is
    directionless: it is ``True`` both when a turn saw a range verbatim that is
    now compressed, and when a turn saw a ``K`` that has since been expanded.
    """
    then_ids = [n.id for n in context_at_generation(all_nodes, node_id)]
    now_ids = [n.id for n in now_prefix(all_nodes, node_id)]
    return then_ids != now_ids
