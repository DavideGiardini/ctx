from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class Node:
    id: str = field(default_factory=lambda: uuid4().hex)
    conversation_id: str = ""
    role: str = ""
    content: str = ""
    node_type: str = "message"
    meta: dict = field(default_factory=dict)
    # Append-only graph edges (ADR-0016): prev_id = predecessor (None = root;
    # shared prev_id = branch siblings). compressed_into wired up in S3.
    prev_id: str | None = None
    compressed_into: str | None = None
    # Monotonic creation order (ADR-0016 A#2), assigned by ConversationCore when a
    # node enters the graph and never reassigned; the 3b event-enumeration oracle.
    created_seq: int = 0

    @classmethod
    def user(cls, content: str, conversation_id: str) -> Node:
        """Build a user chat turn."""
        return cls(role="user", content=content, conversation_id=conversation_id)

    @classmethod
    def assistant(cls, conversation_id: str, content: str = "") -> Node:
        """Build an assistant chat turn (content is filled in as it streams).

        ``meta`` keys stamped later by ``ConversationCore`` (the canonical
        vocabulary for assistant turns — do not improvise new keys):
          - ``meta["ctx_hash"]`` — digest of the exact context sent to the
            model, stamped at the turn's first tick (ADR-0016 A#3 §4);
          - ``meta["interrupted"]`` — ``True`` when the turn was cancelled
            mid-stream (stamped durably by ``end_turn``);
          - ``meta["error"]`` — the provider/build error message when the turn
            failed (stamped durably by ``end_turn``).
        """
        return cls(role="assistant", content=content, conversation_id=conversation_id)

    @classmethod
    def system(cls, content: str, conversation_id: str = "") -> Node:
        """Build a system breadcrumb (e.g. "Model set to: …").

        The optional ``conversation_id`` decides durability: passed inside an
        active conversation the breadcrumb persists (model-change/connectivity
        notices reappear on resume); left empty it stays session-local, because
        storage skips id-less nodes (ADR 0006 #6).
        """
        return cls(
            role="system",
            content=content,
            node_type="system",
            conversation_id=conversation_id,
        )

    def goes_to_model(self) -> bool:
        """Whether this node's content is sent to the LLM when building context.

        The single source of truth for "which nodes reach the model" —
        ``build_context`` routes its inclusion decision through this predicate
        rather than re-deriving role rules (ADR 0014 #1). User/assistant turns,
        context imports, and compression nodes reach the model; a compression
        node stands in for the folded originals it summarizes (ADR-0016 H6).
        """
        return self.role in {"user", "assistant"} or self.node_type in {
            "context",
            "compression",
        }

    @classmethod
    def compression(
        cls,
        summary: str,
        conversation_id: str,
        range_ids: list[str],
        prompt: str = "",
    ) -> Node:
        """Build a compression node ``K`` that folds a contiguous range of nodes.

        A compression node stands in for the folded originals when context is
        built: the model sees ``summary`` (later wrapped in
        ``<conversation_summary>``) instead of the folded children
        (ADR-0016 A#1/A#2, H6).

        ``role`` and ``node_type`` are both ``"compression"``; ``content`` is the
        ``summary`` text. ``meta`` carries the canonical keys (H1/H5):
          - ``meta["prompt"]`` — the compression instruction that produced the
            summary (``""`` for a hand-written/manual summary).
          - ``meta["range"]`` — the ordered ids of the folded child nodes.

        The node sits **off** the ``prev_id`` line (``prev_id=None``); the core
        adds it straight to the graph, never via the line-append path.
        """
        return cls(
            role="compression",
            content=summary,
            node_type="compression",
            conversation_id=conversation_id,
            meta={"prompt": prompt, "range": list(range_ids)},
        )

    @classmethod
    def expand(
        cls,
        target_id: str,
        anchor_id: str | None,
        conversation_id: str,
    ) -> Node:
        """Build an expand event node ``E`` that deactivates a compression ``K``.

        ``E`` records the *event* of expanding ``K`` back to its folded children
        rather than any conversation content: ``role`` and ``node_type`` are both
        ``"expand"``, ``content`` is empty, and it never reaches the model
        (``goes_to_model()`` stays ``False``). Like a compression node it sits
        **off** the ``prev_id`` line (``prev_id=None``); the core adds it straight
        to the graph, never via the line-append path.

        ``meta`` carries the canonical keys (H5):
          - ``meta["target"]`` — the id of the compression ``K`` this expand
            deactivates.
          - ``meta["anchor"]`` — the active leaf id at expand time (S4
            forward-compat for branch-local expand; 3a resolution ignores it).
        """
        return cls(
            role="expand",
            node_type="expand",
            conversation_id=conversation_id,
            meta={"target": target_id, "anchor": anchor_id},
        )

    @classmethod
    def context(cls, source_path: str, conversation_id: str) -> Node:
        """Build a context-import reference to a workspace file.

        ``meta["source_path"]`` is the path ``build_context`` later loads and
        wraps in ``<context_import>``.
        """
        return cls(
            role="context",
            content=f"Included: {source_path}",
            node_type="context",
            conversation_id=conversation_id,
            meta={"source_path": source_path},
        )
