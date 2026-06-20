"""Semantic snapshot of the running ``ChatApp`` for AI agents.

A pure reader: it observes the live app through its public interfaces — core
conversation state, the app's observation accessors (``mode``,
``selected_node_id``, ``is_streaming``), and the widgets' public accessors
(``DetailInspector.view_state``, ``InputBar.value``) — and returns a compact,
JSON-serializable description. It never mutates the app and never reaches into
private attributes.

This mirrors the spirit of :func:`ctx.core.context.build_context`: a
side-effect-free translator from app state into a consumable representation, so
an agent can "see" the UI without spending vision tokens on screenshots.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from textual.widgets import Static

from ctx.core.config import get_config
from ctx.ui.widgets.detail_inspector import DetailInspector
from ctx.ui.widgets.input_bar import InputBar

if TYPE_CHECKING:
    from ctx.ui.app import ChatApp

CONTENT_PREVIEW_CHARS = 120
"""Max characters of a node's content kept in the snapshot (small for token efficiency)."""


def _preview(text: str, limit: int = CONTENT_PREVIEW_CHARS) -> str:
    """Collapse whitespace and truncate to a compact single-line preview."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit] + "…"


def _inspector_state(app: ChatApp) -> dict[str, Any]:
    """The Detail Inspector's view, with the displayed node resolved to a list index."""
    try:
        view = app.query_one(DetailInspector).view_state
    except Exception:
        return {"node_id": None, "view_mode": None, "full_split": None, "node_index": None}
    node_index = next(
        (i for i, n in enumerate(app.core.nodes) if n.id == view["node_id"]), None
    )
    return {**view, "node_index": node_index}


def _input_state(app: ChatApp) -> dict[str, Any]:
    """The input bar's text, cursor, and (if open) the matching command candidates."""
    try:
        bar = app.query_one(InputBar)
    except Exception:
        return {"value": "", "cursor": 0, "command_menu": None}

    menu_open = False
    with contextlib.suppress(Exception):
        menu_open = bool(app.query_one("#command-suggestions", Static).display)

    command_menu = (
        [cmd for cmd in InputBar.COMMANDS if cmd.startswith(bar.value)] if menu_open else None
    )
    return {"value": bar.value, "cursor": bar.cursor_position, "command_menu": command_menu}


def describe_state(app: ChatApp) -> dict[str, Any]:
    """Return a compact, JSON-serializable description of the app's UI state."""
    core = app.core
    usage = core.token_usage()
    colors = get_config()["colors"]
    selected_id = app.selected_node_id

    nodes: list[dict[str, Any]] = []
    selection: dict[str, Any] | None = None
    for index, node in enumerate(core.nodes):
        tokens = usage.per_node.get(node.id, 0)
        color = colors.get(node.role, colors["system"])
        is_selected = node.id == selected_id

        entry: dict[str, Any] = {
            "index": index,
            "role": node.role,
            "node_type": node.node_type,
            "content": _preview(node.content),
            "tokens": tokens,
            "share_pct": round((tokens / usage.total) * 100) if usage.total else 0,
            "selected": is_selected,
            "color": color,
        }
        if node.node_type == "context":
            entry["context"] = {
                "has_prompt": bool(node.prompt),
                "has_content": bool(node.raw_content),
                "has_output": bool(node.output),
            }
        nodes.append(entry)

        if is_selected:
            selection = {"index": index, "id": node.id, "role": node.role, "color": color}

    return {
        "mode": app.mode,
        "streaming": app.is_streaming,
        "conversation": {
            "id": core.conversation_id,
            "title": core.conversation_title,
            "model": core.model,
            "tokens": {
                "total": usage.total,
                "limit": usage.limit,
                "percent": min(100, round(usage.fraction * 100)),
            },
        },
        "selection": selection,
        "inspector": _inspector_state(app),
        "input": _input_state(app),
        "nodes": nodes,
    }
