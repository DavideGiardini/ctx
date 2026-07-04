"""Micro-benchmark: _node_drift-style cost (has_drift per assistant node)."""
import time

from ctx.core import reconstruction
from ctx.models.nodes import Node


def build(n_turns: int):
    nodes = []
    prev = None
    seq = 1
    for i in range(n_turns):
        u = Node.user(f"question {i} " + "x" * 100, "c1")
        u.prev_id = prev
        u.created_seq = seq
        seq += 1
        a = Node.assistant(f"answer {i} " + "y" * 300, "c1")
        a.prev_id = u.id
        a.created_seq = seq
        seq += 1
        nodes += [u, a]
        prev = a.id
    # one K folding the first 4 nodes (created mid-way) + one E expanding it later
    k = Node.compression("summary", "c1", [n.id for n in nodes[:4]])
    k.created_seq = seq
    seq += 1
    nodes.append(k)
    return nodes

for n_turns in (50, 200, 500):
    nodes = build(n_turns)
    assistants = [n for n in nodes if n.role == "assistant"]
    t0 = time.perf_counter()
    flags = [reconstruction.has_drift(nodes, a.id) for a in assistants]
    dt = time.perf_counter() - t0
    print(f"turns={n_turns:4d} nodes={len(nodes):5d} assistants={len(assistants):4d} "
          f"drifted={sum(flags):4d} one refresh={dt*1000:8.1f} ms")
