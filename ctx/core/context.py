from collections.abc import Callable

from ctx.core.log import logger
from ctx.models.nodes import Node


def build_context(
    nodes: list[Node], load_file: Callable[[str], str]
) -> list[dict]:
    """Convert a list of Nodes into LLM message dicts.

    Context nodes (node_type == "context") are expanded in-place: their
    referenced file content is wrapped in <context_import> XML and merged
    into the next user message, or emitted as a standalone user message
    if no user message follows.

    The ``load_file`` callable is injected so this function remains pure
    and testable without filesystem I/O.
    """
    messages: list[dict] = []

    for node in nodes:
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
                continue
            node_content = f'<context_import source="{source_path}">\n{content}\n</context_import>'
            node_role = "user"

        if node_role == "user":
            if messages and messages[-1]["role"] == "user":
                messages[-1]["content"] += node_content
            else:
                messages.append({"role": "user", "content": node_content})
        elif node_role == "assistant":
            messages.append({"role": "assistant", "content": node_content})

    return messages
