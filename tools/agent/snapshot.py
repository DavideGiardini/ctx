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
            count = menu.get("count")
            if count is not None:
                menu_detail = f"{count} items"
                if menu.get("occluded"):
                    menu_detail += ", OCCLUDED"
                line += f" ({menu_detail})"
        lines.append(line)

    footer = state.get("footer")
    if footer:
        lines.append(f'footer="{footer}"')

    # Transient UI hint (task 42) — a toast, not a graph node. Shown while set so
    # QA can confirm a hint fired without it appearing among the nodes.
    hint = state.get("last_hint")
    if hint:
        lines.append(f'hint="{hint}"')

    detail = state.get("detail") or {}
    if detail:
        node = detail.get("node_index")
        node_str = f"[{node}]" if node is not None else "-"
        pane = detail.get("pane_mode", "none")
        locked = "yes" if detail.get("locked") else "no"
        line = f"detail: view={detail.get('view')} node={node_str} pane={pane}"
        if pane == "browse":
            line += f" hi={detail.get('highlighted_split') or '-'}"
        elif pane == "maximized":
            line += f" max={detail.get('maximized_split') or '-'}"
        line += f" locked={locked}"
        if detail.get("view") == "context":
            visible = ",".join(detail.get("splits_visible", [])) or "-"
            line += f" splits={visible}"
        lines.append(line)

    # Context gauge — absolute window usage. `~` marks an approximate (uncalibrated
    # or drifted) reading; an unknown pct renders a neutral `?` placeholder.
    gauge = state.get("context_gauge")
    if gauge is not None:
        pct = gauge.get("pct")
        marker = "~" if gauge.get("approximate") else ""
        pct_str = f"{pct}%" if pct is not None else "?"
        lines.append(f"ctx: {marker}{pct_str}")

    colors = state.get("colors") or {}
    if colors:
        legend = " ".join(f"{role}={value}" for role, value in colors.items())
        lines.append(f"colors: {legend}")

    nodes = state.get("nodes", [])
    selected = state.get("selected_index")
    header = f"nodes={len(nodes)}"
    if selected is not None:
        header += f" selected=[{selected}]"
    range_selection = state.get("range_selection") or []
    if range_selection:
        header += f" range=[{','.join(str(i) for i in range_selection)}]"
    lines.append(header)

    for node in nodes:
        marker = "*" if node.get("selected") else " "
        trunc = "~" if node.get("truncated") else " "
        role = f"{node['role']:<9}"
        content = _one_line(node.get("content", ""))
        suffix = f"  (file: {node['source_path']})" if node.get("source_path") else ""
        weight = node.get("weight_pct")
        if weight is not None:
            suffix += f"  w={weight}%"
        if node.get("drift"):
            suffix += "  Δ"
        lines.append(f"{marker}{trunc}[{node['index']}] {role} {content}{suffix}")

    return "\n".join(lines)
