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

    @classmethod
    def user(cls, content: str, conversation_id: str) -> Node:
        """Build a user chat turn."""
        return cls(role="user", content=content, conversation_id=conversation_id)

    @classmethod
    def assistant(cls, conversation_id: str, content: str = "") -> Node:
        """Build an assistant chat turn (content is filled in as it streams)."""
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
        rather than re-deriving role rules (ADR 0014 #1).
        """
        return self.role in {"user", "assistant"} or self.node_type == "context"

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
