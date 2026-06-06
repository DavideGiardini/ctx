from ctx.models.nodes import Node


def build_context(nodes: list[Node]) -> list[dict]:
    return [{"role": node.role, "content": node.content} for node in nodes if node.node_type == "message"]