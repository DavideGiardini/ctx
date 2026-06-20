"""Render a ChatApp state snapshot as compact, token-efficient text.

Pure presentation layer: takes the raw dict produced by
``ChatApp.describe_state()`` and formats it for an agent to read. All
truncation/compaction lives here so the UI class stays free of
AI-presentation concerns. No app/Textual imports — trivially testable.
"""

from __future__ import annotations

MAX_CONTENT = 80


def _one_line(text: str, limit: int = MAX_CONTENT) -> str:
    """Collapse whitespace to a single line and truncate to *limit* chars."""
    collapsed = " ".join(text.split())
    if len(collapsed) > limit:
        return collapsed[: limit - 1] + "…"
    return collapsed


def render(state: dict) -> str:
    """Format a ``describe_state()`` dict as a compact, diffable text block.

    The structure is stable so agents can cheaply diff snapshots between
    actions; optional lines (title, input, split) appear only when meaningful.
    """
    lines: list[str] = []

    streaming = "yes" if state.get("streaming") else "no"
    lines.append(
        f"mode={state['mode']} focus={state.get('focus')} "
        f"streaming={streaming} model={state['model']}"
    )

    title = state.get("title")
    if title:
        lines.append(f'title="{title}"')

    # Input line — shown only when there is text or an open command menu.
    menu = state.get("command_menu")
    input_value = state.get("input", "")
    if input_value or menu:
        line = f'input="{input_value}"'
        if menu:
            line += f"  command-menu→{menu['selected']}"
        lines.append(line)

    split = state.get("split") or {}
    if split.get("open"):
        lines.append(f"split=open file={split.get('file')!r}")

    colors = state.get("colors") or {}
    if colors:
        legend = " ".join(f"{role}={value}" for role, value in colors.items())
        lines.append(f"colors: {legend}")

    nodes = state.get("nodes", [])
    selected = state.get("selected_index")
    header = f"nodes={len(nodes)}"
    if selected is not None:
        header += f" selected=[{selected}]"
    lines.append(header)

    for node in nodes:
        marker = "*" if node.get("selected") else " "
        role = f"{node['role']:<9}"
        content = _one_line(node.get("content", ""))
        suffix = f"  (file: {node['source_path']})" if node.get("source_path") else ""
        lines.append(f"{marker} [{node['index']}] {role} {content}{suffix}")

    return "\n".join(lines)
