from collections.abc import Callable

from ctx.core.log import logger
from ctx.models.nodes import Node


def build_context(
    nodes: list[Node], load_file: Callable[[str], str]
) -> list[dict]:
    """Convert a list of Nodes into LLM message dicts.

    Context nodes (node_type == "context") load their file, wrap it in
    <context_import> XML, and count as user-role content. Compression nodes
    (node_type == "compression") wrap their summary content in
    <conversation_summary> XML and likewise count as user-role content, so a
    summary coalesces with adjacent user material exactly like an import
    (ADR-0016 A#1, H6). Adjacent user-role content is coalesced into one user
    message; assistant nodes are appended as their own; other roles (e.g.
    system) are skipped.

    ROLE-ALTERNATION INVARIANT: the returned list never contains two adjacent
    dicts of the same role. Strict role-alternation providers (Anthropic-family
    via litellm) reject consecutive same-role turns, so whenever user-role
    material would follow an already-emitted user message it is *merged* into
    that message with an explicit ``\\n\\n`` separator — never emitted as a
    second user dict and never glued on with no separator. A dropped node (a
    system breadcrumb) emits nothing and does **not** break the merge: two user
    runs separated only by dropped nodes still collapse to one user message.
    Only an assistant message breaks the run, so material after it starts a
    fresh user dict (task 34).

    Failures are made *visible* rather than silent: when a context node's file
    fails to load (``load_file`` raises ``OSError``/``ValueError``), a marked
    ``<context_import source="…" error="…">`` block is emitted as user material
    so the model — and, through it, the user — sees that the import failed,
    instead of the file silently disappearing. A context node with no usable
    ``source_path`` has nothing to import and is dropped.

    Empty ``user``/``assistant`` nodes (``content == ""``) are skipped so no
    empty-content message reaches the provider (several APIs reject those).

    ``load_file`` is injected so this stays pure and testable without I/O.
    """
    messages: list[dict] = []

    for node in nodes:
        if not node.goes_to_model():
            continue

        node_content, node_role = node.content, node.role

        if node.node_type == "context":
            source_path = node.meta.get("source_path")
            if not source_path:
                logger.warning("context node missing source_path | node_id=%s", node.id)
                continue
            try:
                content = load_file(source_path)
            except (OSError, ValueError) as exc:
                logger.warning(
                    "failed to read context file | path=%s | error=%s", source_path, exc
                )
                node_content = (
                    f'<context_import source="{source_path}" error="{exc}">'
                    "</context_import>"
                )
            else:
                node_content = (
                    f'<context_import source="{source_path}">\n{content}\n</context_import>'
                )
            node_role = "user"

        elif node.node_type == "compression":
            node_content = (
                f"<conversation_summary>\n{node_content}\n</conversation_summary>"
            )
            node_role = "user"

        if node_role == "user":
            if not node_content:
                continue
            if messages and messages[-1]["role"] == "user":
                messages[-1]["content"] += "\n\n" + node_content
            else:
                messages.append({"role": "user", "content": node_content})
        elif node_role == "assistant":
            if not node_content:
                continue
            messages.append({"role": "assistant", "content": node_content})

    return messages
