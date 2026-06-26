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

    @classmethod
    def user(cls, content: str, conversation_id: str) -> Node:
        """Build a user chat turn.

        ``role="user"``, default ``node_type`` ("message"), the given content,
        and the owning ``conversation_id`` so it persists. ``meta`` is empty.
        """
        return cls(role="user", content=content, conversation_id=conversation_id)

    @classmethod
    def assistant(cls, conversation_id: str, content: str = "") -> Node:
        """Build an assistant chat turn (content is filled in as it streams).

        ``role="assistant"``, default ``node_type`` ("message"), the given
        content (empty by default, before any tokens arrive), and the owning
        ``conversation_id`` so it persists. ``meta`` is empty.
        """
        return cls(role="assistant", content=content, conversation_id=conversation_id)

    @classmethod
    def system(cls, content: str) -> Node:
        """Build a transient system breadcrumb (e.g. "Model set to: …").

        ``role="system"`` and ``node_type="system"`` with the given content.
        It deliberately carries **no** ``conversation_id`` — system breadcrumbs
        are session-local UI notices, not durable conversation turns, and the
        storage layer skips nodes without a ``conversation_id``. ``meta`` empty.
        """
        return cls(role="system", content=content, node_type="system")

    def goes_to_model(self) -> bool:
        """Whether this node's content is sent to the LLM when building context.

        The single source of truth for "which nodes reach the model": user and
        assistant chat turns (``role in {"user", "assistant"}``) and context
        imports (``node_type == "context"``) do; everything else — notably
        ``system`` breadcrumbs — does not. ``build_context`` routes its inclusion
        decision through this predicate so the rule has exactly one definition.
        """
        return self.role in {"user", "assistant"} or self.node_type == "context"

    @classmethod
    def context(cls, source_path: str, conversation_id: str) -> Node:
        """Build a context-import reference to a workspace file.

        ``role="context"`` and ``node_type="context"``, a human-readable
        ``content`` of ``"Included: <source_path>"``, the owning
        ``conversation_id`` so it persists, and ``meta={"source_path": source_path}``
        — the path ``build_context`` later loads and wraps in ``<context_import>``.
        """
        return cls(
            role="context",
            content=f"Included: {source_path}",
            node_type="context",
            conversation_id=conversation_id,
            meta={"source_path": source_path},
        )
